# Copyright (c) 2026, Riverside and Contributors
# See license.txt
"""Законодавчий параметр: значення норми з періодом дії та підставою.

Правила живуть на сервері (конвенції § 4.7): клієнтський скрипт лише допомагає
вводити, а перевірка, продубльована в інтерфейсі, вважається дефектом.
"""

import re

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import getdate

from ua_compliance.basis import validate_basis_url

CODE_PATTERN = re.compile(r"^[A-Z][A-Z0-9_]*$")

VALUE_FIELD_BY_TYPE = {
	"Сума": "value_number",
	"Число": "value_number",
	"Відсоток": "value_number",
	"Дата": "value_date",
	"Рядок": "value_text",
	"Ознака": "value_flag",
}


class UALegalParameter(Document):
	def validate(self):
		self.validate_code()
		validate_basis_url(self)
		self.validate_period()
		self.validate_value()
		self.validate_overlap()
		self.validate_package_record_is_not_edited()

	def validate_code(self):
		"""Ідентифікатори — лише латиницею (принцип III)."""
		if not CODE_PATTERN.match(self.code or ""):
			frappe.throw(_("Код параметра пишеться латиницею великими літерами: MIN_WAGE"))

	def validate_period(self):
		if self.valid_to and getdate(self.valid_to) < getdate(self.valid_from):
			frappe.throw(_("Дата закінчення дії раніша за дату початку"))

	def validate_value(self):
		"""Заповнене має бути саме те поле, яке відповідає виду значення."""
		expected = VALUE_FIELD_BY_TYPE[self.value_type]
		if expected != "value_flag" and self.get(expected) in (None, ""):
			frappe.throw(_("Для виду значення «{0}» значення не заповнене").format(self.value_type))

		for field in set(VALUE_FIELD_BY_TYPE.values()) - {expected}:
			if field == "value_flag":
				continue
			if self.get(field) not in (None, "", 0):
				self.set(field, None)

	def validate_overlap(self):
		"""Періоди одного коду не перетинаються — інакше «значення на дату» перестає бути однозначним."""
		conflict = frappe.db.sql(
			"""
			select name, valid_from, valid_to
			from `tabUA Legal Parameter`
			where code = %(code)s and name != %(name)s
			  and (%(valid_from)s <= ifnull(valid_to, '9999-12-31'))
			  and (ifnull(%(valid_to)s, '9999-12-31') >= valid_from)
			limit 1
			""",
			{
				"code": self.code,
				"name": self.name or "",
				"valid_from": self.valid_from,
				"valid_to": self.valid_to,
			},
			as_dict=True,
		)
		if conflict:
			row = conflict[0]
			# Дата у повідомленні — завжди DD.MM.YYYY (ui-conventions § 3), незалежно від
			# того, який формат стоїть у налаштуваннях сайту.
			frappe.throw(
				_("Період дії параметра {0} перетинається з наявним записом {1} — {2}").format(
					self.code,
					getdate(row.valid_from).strftime("%d.%m.%Y"),
					getdate(row.valid_to).strftime("%d.%m.%Y") if row.valid_to else _("безстроково"),
				)
			)

	def validate_package_record_is_not_edited(self):
		"""Запис, що приїхав пакетом, не правиться руками: нове значення приходить новим записом."""
		if self.is_new() or self.source != "З пакета":
			return
		if frappe.flags.get("ua_applying_package"):
			return
		frappe.throw(_("Запис із пакета не редагується — нове значення приходить наступним пакетом"))

	def on_trash(self):
		"""Фізичного видалення немає (принцип III)."""
		frappe.throw(_("Параметр не видаляється — закрийте період датою"))

	def typed_value(self):
		field = VALUE_FIELD_BY_TYPE[self.value_type]
		return self.get(field)
