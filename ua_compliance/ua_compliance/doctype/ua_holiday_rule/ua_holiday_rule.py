# Copyright (c) 2026, Riverside and contributors
# For license information, please see license.txt

from datetime import date

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import getdate

from ua_compliance.basis import validate_basis_url


class UAHolidayRule(Document):
	def validate(self):
		validate_basis_url(self)
		self.validate_period()
		self.validate_fixed_date()
		self.validate_package_record_is_not_edited()

	def validate_period(self):
		if self.valid_to and getdate(self.valid_to) < getdate(self.valid_from):
			frappe.throw(_("Дата закінчення дії раніша за дату початку"))

	def validate_fixed_date(self):
		"""Фіксоване свято без дня чи місяця календар мовчки пропустив би."""
		if self.rule_type != "Фіксована дата":
			return
		try:
			date(2000, int(self.month or 0), int(self.day or 0))  # 2000 — високосний: 29.02 допустиме
		except ValueError:
			frappe.throw(_("Для фіксованої дати потрібні справжні день і місяць"))

	def validate_package_record_is_not_edited(self):
		"""Правило, що приїхало пакетом, не правиться руками — нова редакція приходить пакетом.

		Межа на сервері, а не в правах: Адміністратор права оминає (так було з
		класифікатором на перевірці 04.10.2026). Пакет ставить прапорець запиту.
		"""
		if self.is_new() or frappe.flags.get("ua_applying_package"):
			return
		before = self.get_doc_before_save()
		if before and before.source == "З пакета":
			frappe.throw(_("Правило з пакета не редагується — нова редакція приходить наступним пакетом"))

	def on_trash(self):
		"""Фізичного видалення немає (принцип III): правило закривається датою."""
		frappe.throw(_("Правило свята не видаляється — закрийте період датою"))
