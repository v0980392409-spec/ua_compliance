"""Серверні методи застосунку."""

import frappe
from frappe import _
from frappe.utils import getdate

from ua_compliance.rates.writer import LOCAL_CURRENCY


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
