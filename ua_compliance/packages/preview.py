"""Передпоказ: що саме зміниться, з якої дати і де розходження з ручними записами."""

import frappe
from frappe.utils import add_days, getdate


def build(rows):
	"""Повертає список рядків передпоказу для таблиці пакета."""
	changes = []
	for row in rows:
		code, valid_from = row["code"], getdate(row["valid_from"])
		same = frappe.db.get_value(
			"UA Legal Parameter",
			{"code": code, "valid_from": valid_from},
			["name", "value_number", "value_text", "value_date", "value_flag", "value_type", "source"],
			as_dict=True,
		)
		if same:
			changes.append(
				{
					"entity": "Параметр",
					"code": code,
					"action": "Змінюється",
					"valid_from": valid_from,
					"old_value": _as_text(same),
					"new_value": row["value"],
					"conflict": 1 if same.source == "Введено вручну" and str(_as_text(same)) != str(row["value"]) else 0,
				}
			)
			continue

		# Чинний запис, який цей рядок закриває датою.
		open_record = frappe.db.sql(
			"""
			select name, value_number, value_text, value_date, value_flag, value_type, source, valid_from
			from `tabUA Legal Parameter`
			where code = %(code)s and valid_from < %(valid_from)s
			  and (valid_to is null or valid_to >= %(valid_from)s)
			order by valid_from desc limit 1
			""",
			{"code": code, "valid_from": valid_from},
			as_dict=True,
		)
		if open_record:
			previous = open_record[0]
			changes.append(
				{
					"entity": "Параметр",
					"code": code,
					"action": "Закривається",
					"valid_from": add_days(valid_from, -1),
					"old_value": _as_text(previous),
					"new_value": "",
					"conflict": 1 if previous.source == "Введено вручну" else 0,
				}
			)

		changes.append(
			{
				"entity": "Параметр",
				"code": code,
				"action": "Додається",
				"valid_from": valid_from,
				"old_value": "",
				"new_value": row["value"],
				"conflict": 0,
			}
		)
	return changes


def _as_text(record):
	field = {
		"Сума": "value_number",
		"Число": "value_number",
		"Відсоток": "value_number",
		"Дата": "value_date",
		"Рядок": "value_text",
		"Ознака": "value_flag",
	}[record.value_type]
	value = record.get(field)
	return "" if value is None else str(value)
