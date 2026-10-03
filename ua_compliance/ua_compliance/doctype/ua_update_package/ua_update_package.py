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
		result = package_verify.verify(raw, package_verify.last_applied_version(self.channel_code))
		manifest_channel = result["manifest"].get("channel")
		if manifest_channel != self.channel_code:
			raise PackageError(
				f"Пакет не прийнято: канал пакета {manifest_channel}, а документ заведено "
				f"на канал {self.channel_code}"
			)
		return result

	def run_verification(self, raw):
		"""Перевірка за контрактом. Будь-яка невдача — стан «Відхилено» з причиною."""
		started = now_datetime()
		try:
			result = self._verify(raw)
		except PackageError as error:
			self.state = "Відхилено"
			self.reject_reason = str(error)
			self.save_by_action()
			journal.write("Приймання пакета", "Помилка", str(error), package=self.name, started_at=started)
			return False

		manifest = result["manifest"]
		self.manifest_hash = result["manifest_hash"]
		self.key_ids = ", ".join(result["key_ids"])
		self.signatures_ok = len(result["key_ids"])
		self.expires_on = manifest.get("expires")
		self.min_app_version = manifest.get("min_app_version")
		self.notes = manifest.get("notes")
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
		self.state = "До застосування"
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

	def approve_and_apply(self, raw):
		"""Затвердження людиною і застосування однією транзакцією."""
		if APPROVER_ROLE not in frappe.get_roles() and frappe.session.user != "Administrator":
			frappe.throw(_("Затверджувати пакет може лише роль «{0}»").format(APPROVER_ROLE))
		if self.state != "До застосування":
			frappe.throw(_("Пакет у стані «{0}» не затверджується").format(self.state))

		conflicts = [row for row in self.preview if row.conflict]
		if conflicts:
			frappe.throw(
				_("Є розходження з записами, введеними вручну ({0}). Прийміть рішення по кожному").format(
					", ".join(sorted({row.code for row in conflicts}))
				)
			)

		started = now_datetime()
		result = self._verify(raw)
		reference = f"{self.channel} {self.version}"
		if self.channel_code == "classifiers":
			summary = package_apply.apply_classifiers(result["rows"], reference)
		else:
			summary = package_apply.apply_parameters(result["rows"], reference)

		self.state = "Застосовано"
		self.approved_by = frappe.session.user
		self.approved_on = now_datetime()
		self.applied_on = now_datetime()
		self.save_by_action()
		journal.write(
			"Застосування пакета",
			"Успішно",
			f"Створено {summary['created']}, закрито {summary['closed']}, оновлено {summary['updated']}",
			package=self.name,
			started_at=started,
			counts={"created": summary["created"], "updated": summary["updated"] + summary["closed"]},
		)
		return summary


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
