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


def warn_about_updates():
	"""Три попередження з контракту (FR-038). Мовчазної давнини не буває."""
	settings = frappe.get_single("UA Compliance Settings")
	if not settings.packages_enabled:
		return

	warnings = []

	threshold = int(settings.stale_warning_days or 45)
	last_applied = frappe.get_all(
		"UA Update Package",
		filters={"state": "Застосовано"},
		fields=["applied_on"],
		order_by="applied_on desc",
		limit=1,
	)
	if not last_applied:
		warnings.append("Оновлення законодавства ще жодного разу не застосовувалися")
	elif getdate(last_applied[0].applied_on) < getdate(add_days(today(), -threshold)):
		days = (getdate(today()) - getdate(last_applied[0].applied_on)).days
		warnings.append(f"Оновлення законодавства не надходили {days} днів")

	expired = frappe.get_all(
		"UA Update Package",
		# Frappe підставляє замість порожньої дати 0001-01-01: без «is set» пакет без строку
		# (щойно заведений, ще не перевірений) вважався б простроченим.
		filters=[
			["state", "in", ["Отримано", "До застосування"]],
			["expires_on", "is", "set"],
			["expires_on", "<", today()],
		],
		pluck="name",
	)
	for name in expired:
		warnings.append(f"Строк придатності пакета {name} минув")

	waiting = frappe.get_all("UA Update Package", filters={"state": "До застосування"}, pluck="name")
	for name in waiting:
		due = frappe.get_all(
			"UA Update Package Change",
			filters={"parent": name, "valid_from": ["<=", today()]},
			pluck="name",
		)
		if due:
			warnings.append(f"Є непримінений пакет {name}, дата дії якого вже настала")

	if warnings:
		# Попередження — не збій приймання: свій вид і результат «Увага», щоб журнал не
		# лякав щоденною «Помилкою» там, де нічого не зламалося.
		journal.write("Попередження", "Увага", "\n".join(warnings))
	return warnings
