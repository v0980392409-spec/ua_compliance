# Copyright (c) 2026, Riverside and Contributors
# See license.txt
"""Пакет оновлень: прийняття, перевірка, передпоказ, застосування.

Автоматичного застосування немає свідомо: у 2017 році через сервер оновлень
українського бухгалтерського ПЗ пройшла атака, і клієнти ставили все, що приходило.
Тут рішення приймає людина, а система лише показує, що саме зміниться.
"""

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import now_datetime

from ua_compliance import journal
from ua_compliance.packages import apply as package_apply
from ua_compliance.packages import parse as package_parse
from ua_compliance.packages import preview as package_preview
from ua_compliance.packages import verify as package_verify
from ua_compliance.packages.reader import PackageError

APPROVER_ROLE = "Відповідальний за законодавство"
# Передпоказ має допомогти людині ухвалити рішення, а не відтворити весь пакет:
# у класифікаторі змін бувають десятки тисяч, і документ з такою кількістю рядків
# не зберігається (спіймано харнесом 02.10.2026 на 32 000 кодів КАТОТТГ).
PREVIEW_LIMIT = 200
FINAL_STATES = ("Застосовано",)
DECISION_ACCEPT = "Прийняти з пакета"
DECISION_KEEP = "Залишити ручне"


class UAUpdatePackage(Document):
	def _set_channel_code(self):
		# Код каналу — похідний від обраного каналу: у формі людина обирає лише канал.
		codes = {title: code for code, title in package_parse.CHANNEL_BY_CODE.items()}
		self.channel_code = codes.get(self.channel)

	def before_insert(self):
		# Ім'я складається з коду каналу, а присвоюється раніше за validate.
		self._set_channel_code()
		# Пакет народжується лише отриманим, що б не надіслали у формі чи через API.
		self.state = "Отримано"

	def validate(self):
		self._set_channel_code()
		if not self.is_new():
			previous = self.get_doc_before_save()
			if previous and previous.state in FINAL_STATES and self.state != previous.state:
				# Застосований пакет не «відміняється» заднім числом: виправлення йде
				# наступним пакетом, інакше захист від відкоту версії втрачає сенс (FR-035).
				frappe.throw(
					_("Застосований пакет не скасовується — виправлення приходить наступним пакетом")
				)
			if not self.flags.ua_action:
				# Стан і передпоказ пише лише сервер у діях пакета. Інакше «Застосовано»
				# виставлялося б руками без застосування (і обманювало захист від відкоту),
				# а знятий прапорець «Розходиться» обходив би блокування затвердження.
				frappe.throw(
					_("Пакет змінюється лише діями «Перевірити», «Затвердити», «Відхилити»")
				)
		if self.state == "Відхилено" and not self.reject_reason:
			frappe.throw(_("Вкажіть причину відхилення"))

	def save_by_action(self):
		"""Збереження з дії пакета. Дозвіл одноразовий: після збереження прапорець
		знімається, інакше наступне ручне збереження того самого об'єкта пройшло б
		(спіймано харнесом 03.10.2026)."""
		self.flags.ua_action = True
		try:
			self.save(ignore_permissions=True)
		finally:
			self.flags.ua_action = False

	def on_trash(self):
		frappe.throw(_("Пакет оновлень не видаляється — він є слідом рішення"))

	def _verify(self, raw):
		"""Перевірка за контрактом плюс збіг каналу маніфесту з каналом документа.

		Без збігу захист від відкоту рахував би версію по чужому каналу, а застосування
		пішло б не тим шляхом: класифікатор розібрали б як параметри.
		"""
		result = package_verify.verify(
			raw,
			package_verify.last_applied_version(self.channel_code),
			allow_expired=bool(self.expiry_override),
		)
		manifest_channel = result["manifest"].get("channel")
		if manifest_channel != self.channel_code:
			raise PackageError(
				f"Пакет не прийнято: канал пакета {manifest_channel}, а документ заведено "
				f"на канал {self.channel_code}"
			)
		return result

	def _fill_header(self, result):
		"""Шапка пакета з маніфесту: підписи, строки, опис."""
		manifest = result["manifest"]
		self.manifest_hash = result["manifest_hash"]
		self.key_ids = package_verify.describe_keys(result["key_ids"])
		self.signatures_ok = len(result["key_ids"])
		self.expires_on = manifest.get("expires")
		self.min_app_version = manifest.get("min_app_version")
		self.notes = manifest.get("notes")

	def run_verification(self, raw):
		"""Перевірка за контрактом. Будь-яка невдача — стан «Відхилено» з причиною."""
		started = now_datetime()
		try:
			result = self._verify(raw)
		except PackageError as error:
			self.state = "Відхилено"
			self.reject_reason = str(error)
			seen = package_verify.inspect_signatures(raw)
			if seen:
				self._fill_header(seen)
			self.save_by_action()
			journal.write("Приймання пакета", "Помилка", str(error), package=self.name, started_at=started)
			return False

		self._fill_header(result)
		self.set("files", [])
		for row in result["files"]:
			self.append("files", row)
		self.set("preview", [])
		shown = result["rows"][:PREVIEW_LIMIT]
		for row in package_preview.build(shown, self.channel_code):
			self.append("preview", row)
		total = len(result["rows"])
		if total > len(shown):
			self.notes = (self.notes or "") + _(
				"\nЗмін усього: {0}, у передпоказі показано перші {1}"
			).format(total, len(shown))
		# «Перевірено» — перевірки пройдені, але є розходження з ручними записами, які
		# чекають рішення людини; без них пакет одразу готовий до затвердження (FR-029).
		self.state = "Перевірено" if self.undecided_conflicts() else "До застосування"
		self.save_by_action()
		journal.write(
			"Приймання пакета",
			"Успішно",
			f"Підписів {self.signatures_ok}, рядків {len(result['rows'])}",
			package=self.name,
			started_at=started,
			counts={"checked": len(result["rows"])},
		)
		return True

	def approve(self):
		"""Затвердження людиною: «До застосування» → «Затверджено» (FR-029, FR-030).

		Саме застосування — окремий крок (`apply`), у фоновому завданні після фіксації
		затвердження: так затвердження лишається слідом рішення, навіть якщо застосування
		впаде, а пакет можна відхилити й після невдалої спроби.
		"""
		if APPROVER_ROLE not in frappe.get_roles() and frappe.session.user != "Administrator":
			frappe.throw(_("Затверджувати пакет може лише роль «{0}»").format(APPROVER_ROLE))
		undecided = self.undecided_conflicts()
		if undecided:
			frappe.throw(
				_("Є розходження з записами, введеними вручну ({0}). Прийміть рішення по кожному").format(
					", ".join(sorted({row.code for row in undecided}))
				)
			)
		if self.state != "До застосування":
			frappe.throw(_("Пакет у стані «{0}» не затверджується").format(self.state))
		self.state = "Затверджено"
		self.approved_by = frappe.session.user
		self.approved_on = now_datetime()
		self.save_by_action()

	def apply(self, raw):
		"""Застосування затвердженого пакета однією транзакцією (FR-033): «Затверджено» → «Застосовано»."""
		if self.state != "Затверджено":
			frappe.throw(_("Застосовується лише затверджений пакет, а цей у стані «{0}»").format(self.state))
		started = now_datetime()
		result = self._verify(raw)
		reference = f"{self.channel} {self.version}"
		# Код, за яким людина вирішила залишити ручний запис, пакет не чіпає зовсім:
		# і закриття ручного періоду, і новий період з пакета пропускаються разом,
		# інакше новий період перетнувся б із залишеним ручним (FR-017).
		keep_manual = self.codes_kept_manual()
		rows = [row for row in result["rows"] if row.get("code") not in keep_manual]
		if self.channel_code == "classifiers":
			summary = package_apply.apply_classifiers(rows, reference)
		elif self.channel_code == "calendar":
			from ua_compliance.packages import holidays

			summary = holidays.apply(rows, reference)
		else:
			summary = package_apply.apply_parameters(rows, reference)

		self.state = "Застосовано"
		self.applied_on = now_datetime()
		self.save_by_action()
		kept = f"; залишено ручні: {', '.join(sorted(keep_manual))}" if keep_manual else ""
		journal.write(
			"Застосування пакета",
			"Успішно",
			f"Створено {summary['created']}, закрито {summary['closed']}, оновлено {summary['updated']}{kept}",
			package=self.name,
			started_at=started,
			counts={"created": summary["created"], "updated": summary["updated"] + summary["closed"]},
		)
		return summary

	def approve_and_apply(self, raw):
		"""Затвердження й застосування одним викликом — для перевірок і внутрішніх шляхів."""
		self.approve()
		return self.apply(raw)

	def decide(self, decisions):
		"""Рішення людини щодо розходжень із ручними записами (US3/AC8, FR-032).

		decisions — {назва рядка передпоказу: «Прийняти з пакета» | «Залишити ручне»}.
		Коли вирішено всі розходження, пакет переходить у «До застосування».
		"""
		if APPROVER_ROLE not in frappe.get_roles() and frappe.session.user != "Administrator":
			frappe.throw(_("Вирішувати розходження може лише роль «{0}»").format(APPROVER_ROLE))
		if self.state not in ("Перевірено", "До застосування"):
			frappe.throw(_("Пакет у стані «{0}» не чекає рішень").format(self.state))
		allowed = (DECISION_ACCEPT, DECISION_KEEP)
		taken = []
		for row in self.preview:
			if not row.conflict or row.name not in decisions:
				continue
			decision = decisions[row.name]
			if decision not in allowed:
				frappe.throw(_("Невідоме рішення «{0}»").format(decision))
			row.decision = decision
			row.decided_by = frappe.session.user
			taken.append(f"{row.code} з {frappe.utils.formatdate(row.valid_from)}: {decision}")
		if not taken:
			frappe.throw(_("Не вибрано жодного рішення"))
		if not self.undecided_conflicts():
			self.state = "До застосування"
		self.save_by_action()
		journal.write("Рішення щодо пакета", "Успішно", "; ".join(taken), package=self.name)
		return self.state

	def unlock_expired(self, raw):
		"""Зняття блокування за строком придатності адміністратором (FR-037, US3/AC6).

		Для ізольованого контуру, куди свіжий пакет не дістається вчасно. Дія явна,
		лишає слід у журналі, а пакет проходить перевірку знову — без відмови за строком.
		"""
		if not ({"System Manager", "Administrator"} & set(frappe.get_roles())):
			frappe.throw(_("Зняти блокування за строком може лише адміністратор"))
		if self.state != "Відхилено" or "строк придатності маніфесту минув" not in (self.reject_reason or ""):
			frappe.throw(_("Пакет не заблоковано за строком придатності"))
		previous_reason = self.reject_reason
		self.expiry_override = 1
		self.expiry_override_by = frappe.session.user
		self.reject_reason = None
		journal.write(
			"Рішення щодо пакета",
			"Успішно",
			f"Знято блокування за строком придатності ({previous_reason})",
			package=self.name,
		)
		return self.run_verification(raw)

	def undecided_conflicts(self):
		return [row for row in self.preview if row.conflict and not row.decision]

	def codes_kept_manual(self):
		return {row.code for row in self.preview if row.conflict and row.decision == DECISION_KEEP}


def receive(raw: bytes, channel_code: str, version, file_name=""):
	"""Приймає пакет у систему: створює документ у стані «Отримано»."""
	doc = frappe.new_doc("UA Update Package")
	doc.channel = package_parse.CHANNEL_BY_CODE[channel_code]
	doc.channel_code = channel_code
	doc.version = str(version)
	doc.state = "Отримано"
	doc.notes = file_name
	doc.insert(ignore_permissions=True)
	return doc
