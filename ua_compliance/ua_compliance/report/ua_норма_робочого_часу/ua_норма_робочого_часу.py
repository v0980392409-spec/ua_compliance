# Copyright (c) 2026, Riverside and Contributors
# See license.txt
"""Норма робочого часу: місяць, робочих днів, передсвяткових днів, годин.

Величина **рахується** за календарем вихідних і тривалістю робочого дня; передсвятковий
день на годину коротший (ч. 1 ст. 53 КЗпП) — лише за нормальної тривалості, 8 годин.
Зберігати її окремим числом не можна: будь-яке збережене число розійдеться
з календарем після першої ж правки (FR-044).
"""

import frappe
from frappe import _
from frappe.utils import getdate, nowdate

from ua_compliance.calendar.build import working_time

MONTHS = (
	"Січень", "Лютий", "Березень", "Квітень", "Травень", "Червень",
	"Липень", "Серпень", "Вересень", "Жовтень", "Листопад", "Грудень",
)


def execute(filters=None):
	filters = frappe._dict(filters or {})
	year = int(filters.year or getdate(nowdate()).year)
	hours_per_day = float(filters.hours_per_day or 8)
	title = filters.holiday_list or _("Робочий календар {0}").format(year)

	result = working_time(year, hours_per_day=hours_per_day, title=title)

	columns = [
		{"fieldname": "month_name", "label": _("Місяць"), "fieldtype": "Data", "width": 160},
		{"fieldname": "working_days", "label": _("Робочих днів"), "fieldtype": "Int", "width": 140},
		{"fieldname": "pre_holiday_days", "label": _("Передсвяткових днів"), "fieldtype": "Int", "width": 170},
		{"fieldname": "hours", "label": _("Годин"), "fieldtype": "Float", "precision": 2, "width": 140},
	]
	data = [
		{
			"month_name": MONTHS[row["month"] - 1],
			"working_days": row["working_days"],
			"pre_holiday_days": row["pre_holiday_days"],
			"hours": row["hours"],
		}
		for row in result["months"]
	]
	return columns, data
