"""Завдання каналу оновлень: забір пакетів і попередження про давність."""

import frappe
from frappe.utils import add_days, getdate, now_datetime, today

from ua_compliance import journal
from ua_compliance.packages import feed
from ua_compliance.packages import parse as package_parse
from ua_compliance.packages.reader import PackageError, open_package


def poll_packages():
	"""Забирає нові пакети з каналу роздачі, перевіряє й будує передпоказ (FR-039).

	**Не застосовує**: рішення приймає людина кнопкою «Затвердити». Кожен забраний
	пакет стає документом з вкладеним файлом — далі той самий шлях, що й для пакета,
	прикріпленого вручну в ізольованому контурі (FR-036).
	"""
	settings = frappe.get_single("UA Compliance Settings")
	if not settings.packages_enabled or not settings.packages_feed_url:
		return []

	started = now_datetime()
	try:
		releases = feed.fetch_releases(settings.packages_feed_url)
	except feed.FeedError as error:
		journal.write("Приймання пакета", "Помилка", str(error), started_at=started)
		return []

	known = set(
		frappe.get_all("UA Update Package", filters={"source_url": ["is", "set"]}, pluck="source_url")
	)
	received = []
	for asset in feed.pick_new_assets(releases, known):
		try:
			raw = feed.download(asset)
		except feed.FeedError as error:
			journal.write("Приймання пакета", "Помилка", str(error), started_at=started)
			continue
		frappe.db.savepoint("ua_poll_package")
		try:
			received.append(_take(raw, asset))
		except Exception as error:
			# Збій на одному пакеті не зупиняє решту, не стирає попередні й не минає мовчки.
			frappe.db.rollback(save_point="ua_poll_package")
			journal.write(
				"Приймання пакета", "Помилка", f"Пакет {asset['name']}: {error}", started_at=started
			)
	return received


def _take(raw, asset):
	"""Документ пакета з вкладенням і перевірка. Канал і версія — із заголовка маніфесту;
	їм ще не довіряємо, довіру дає перевірка підписів у run_verification."""
	from ua_compliance.ua_compliance.doctype.ua_update_package.ua_update_package import receive

	channel_code, version = "parameters", asset["tag"] or asset["name"]
	try:
		manifest = open_package(raw)[0]
		if manifest.get("channel") in package_parse.CHANNEL_BY_CODE:
			channel_code = manifest["channel"]
		version = manifest.get("version") or version
	except PackageError:
		# Нерозбірний архів однаково стає документом: відмова лишає слід і більше не
		# забирається щодня (реліз у каналі незмінний).
		pass

	package = receive(raw, channel_code, version, file_name=asset["name"])
	package.db_set("source_url", asset["url"])
	frappe.get_doc(
		{
			"doctype": "File",
			"file_name": asset["name"],
			"attached_to_doctype": "UA Update Package",
			"attached_to_name": package.name,
			"content": raw,
			"is_private": 1,
			"decode": False,
		}
	).insert(ignore_permissions=True)
	package.run_verification(raw)
	return package.name


def current_warnings():
	"""Попередження, які зараз чинні (FR-038, крайній випадок «джерело недоступне»).

	Одна функція на всіх: щоденне завдання пише їх у журнал, а форма пакета й розділ
	«Законодавство» показують людині — так текст не розходиться між місцями.
	"""
	settings = frappe.get_single("UA Compliance Settings")
	warnings = []
	if settings.packages_enabled:
		warnings += _package_warnings(settings)
	if settings.rates_enabled:
		warnings += rate_failure_warnings(settings)
	return warnings


def stale_threshold(settings):
	"""Поріг давності в днях. 0 — законне значення («попереджати одразу»), тож не
	«or 45»: так нуль мовчки ставав 45 (спіймано на перевірці на екрані 04.10.2026)."""
	return frappe.utils.cint(settings.stale_warning_days)


def _package_warnings(settings):
	warnings = []
	threshold = stale_threshold(settings)
	last_applied = frappe.get_all(
		"UA Update Package",
		filters={"state": "Застосовано"},
		fields=["applied_on", "expires_on"],
		order_by="applied_on desc",
		limit=1,
	)
	if not last_applied:
		warnings.append("Оновлення законодавства ще жодного разу не застосовувалися")
	else:
		if getdate(last_applied[0].applied_on) < getdate(add_days(today(), -threshold)):
			days = (getdate(today()) - getdate(last_applied[0].applied_on)).days
			warnings.append(f"Оновлення законодавства не надходили {days} днів")
		# Строк придатності останнього застосованого маніфесту — видавець обіцяв новий
		# пакет до цієї дати; минула, а нового немає — дані, ймовірно, застаріли.
		expires = last_applied[0].expires_on
		if expires and getdate(expires) < getdate(today()):
			warnings.append(f"Строк придатності останнього пакета минув {getdate(expires).strftime('%d.%m.%Y')}")

	expired = frappe.get_all(
		"UA Update Package",
		# Frappe підставляє замість порожньої дати 0001-01-01: без «is set» пакет без строку
		# (щойно заведений, ще не перевірений) вважався б простроченим.
		filters=[
			["state", "in", ["Отримано", "Перевірено", "До застосування"]],
			["expires_on", "is", "set"],
			["expires_on", "<", today()],
		],
		pluck="name",
	)
	for name in expired:
		warnings.append(f"Строк придатності пакета {name} минув")

	waiting = frappe.get_all(
		"UA Update Package", filters={"state": ["in", ["Перевірено", "До застосування"]]}, pluck="name"
	)
	for name in waiting:
		due = frappe.get_all(
			"UA Update Package Change",
			filters={"parent": name, "valid_from": ["<=", today()]},
			pluck="name",
		)
		if due:
			warnings.append(f"Є непримінений пакет {name}, дата дії якого вже настала")
	return warnings


def rate_failure_warnings(settings=None):
	"""Курс не завантажується N разів поспіль — попередити відповідального (крайній випадок спеки)."""
	settings = settings or frappe.get_single("UA Compliance Settings")
	limit = int(settings.rates_failure_warning or 0)
	if limit <= 0:
		return []
	last = frappe.get_all(
		"UA Operation Log",
		filters={"kind": "Завантаження курсу"},
		fields=["result", "message"],
		order_by="started_at desc, creation desc",
		limit=limit,
	)
	if len(last) == limit and all(row.result == "Помилка" for row in last):
		reason = (last[0].message or "").splitlines()[0][:200]
		return [f"Курс НБУ не завантажується {limit} разів поспіль: {reason}"]
	return []


def warn_about_updates():
	"""Щоденне завдання: чинні попередження — у журнал. Мовчазної давнини не буває."""
	warnings = current_warnings()
	if warnings:
		# Попередження — не збій приймання: свій вид і результат «Увага», щоб журнал не
		# лякав щоденною «Помилкою» там, де нічого не зламалося.
		journal.write("Попередження", "Увага", "\n".join(warnings))
	return warnings
