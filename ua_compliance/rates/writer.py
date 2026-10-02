"""Запис курсу у штатний запис курсу валюти.

Чому саме туди: підстановка курсу в документі спершу шукає збережений запис і лише
потім звертається до зовнішнього постачальника (erpnext/setup/utils.py::get_exchange_rate).
Отже, досить покласти правильний запис — і документи, звіти й переоцінка працюють
за офіційним курсом без жодної правки ядра.
"""

import frappe

LOCAL_CURRENCY = "UAH"
SOURCE_NBU = "НБУ"


def upsert_rate(on_date, currency, rate, multiplicity=1, source=SOURCE_NBU):
	"""Створює або оновлює запис курсу. Повертає ("created"|"updated"|"unchanged", попереднє значення).

	У штатне поле йде курс, зведений до однієї одиниці: курс / кратність. Інакше
	джерело, яке котирує за сотню одиниць, завищило б усі суми документів у сто разів.
	"""
	per_unit = float(rate) / (int(multiplicity) or 1)
	existing = frappe.db.get_value(
		"Currency Exchange",
		{"date": on_date, "from_currency": currency, "to_currency": LOCAL_CURRENCY},
		["name", "exchange_rate"],
		as_dict=True,
	)

	if existing:
		if _same(existing.exchange_rate, per_unit):
			return "unchanged", existing.exchange_rate
		doc = frappe.get_doc("Currency Exchange", existing.name)
		doc.exchange_rate = per_unit
		_set_source_fields(doc, rate, multiplicity, source)
		doc.save(ignore_permissions=True)
		return "updated", existing.exchange_rate

	doc = frappe.get_doc(
		{
			"doctype": "Currency Exchange",
			"date": on_date,
			"from_currency": currency,
			"to_currency": LOCAL_CURRENCY,
			"exchange_rate": per_unit,
			"for_buying": 1,
			"for_selling": 1,
		}
	)
	_set_source_fields(doc, rate, multiplicity, source)
	doc.insert(ignore_permissions=True)
	return "created", None


def _same(stored, incoming):
	"""Курс джерела має до шести знаків, тому порівнюємо з цією ж точністю."""
	return round(float(stored or 0), 6) == round(float(incoming), 6)


def _set_source_fields(doc, rate, multiplicity, source):
	doc.ua_source_rate = float(rate)
	doc.ua_multiplicity = int(multiplicity) or 1
	doc.ua_source = source
