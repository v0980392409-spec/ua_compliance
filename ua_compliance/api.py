"""Серверні методи застосунку."""

import frappe
from frappe import _
from frappe.utils import getdate

from ua_compliance.rates.writer import LOCAL_CURRENCY


@frappe.whitelist()
def get_parameter(code, on_date=None):
	"""Значення законодавчого параметра на дату (FR-015).

	Беремо запис із найбільшою датою початку, не пізнішою за задану, у якого дата
	закінчення порожня або не раніша за цю дату. Якщо такого немає — помилка, а не
	нуль і не найближче значення: мовчазний нуль у розрахунку помітити неможливо (FR-016).
	"""
	on_date = getdate(on_date)
	rows = frappe.get_all(
		"UA Legal Parameter",
		filters=[["code", "=", code], ["valid_from", "<=", on_date]],
		or_filters=[["valid_to", "is", "not set"], ["valid_to", ">=", on_date]],
		fields=["name"],
		order_by="valid_from desc",
		limit=1,
	)
	if not rows:
		frappe.throw(_("Параметр {0} на {1} не визначено").format(code, on_date.strftime("%d.%m.%Y")))
	return frappe.get_doc("UA Legal Parameter", rows[0].name).typed_value()


@frappe.whitelist()
def get_rate(currency, on_date=None):
	"""Офіційний курс валюти за одиницю на дату.

	Якщо запису немає, повертаємо помилку з тим самим текстом, що бачить користувач
	у документі, а не нуль і не чужий курс (FR-005).
	"""
	on_date = getdate(on_date)
	rate = frappe.db.get_value(
		"Currency Exchange",
		{"date": on_date, "from_currency": currency, "to_currency": LOCAL_CURRENCY},
		"exchange_rate",
	)
	if rate is None:
		frappe.throw(
			_("Офіційний курс НБУ на {0} не завантажено").format(on_date.strftime("%d.%m.%Y"))
		)
	return rate
