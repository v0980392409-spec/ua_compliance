"""Передпоказ: що саме зміниться, з якої дати і де розходження з ручними записами."""

import frappe
from frappe.utils import add_days, getdate


def build(rows, channel_code="parameters"):
	"""Повертає список рядків передпоказу для таблиці пакета."""
	if channel_code == "classifiers":
		return build_classifiers(rows)
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


def build_classifiers(rows):
	"""Передпоказ для класифікаторів: що додається і який код закривається датою."""
	changes = []
	for row in rows:
		name = f"{row['classifier']}-{row['code']}"
		existing = frappe.db.get_value(
			"UA Classifier Entry", name, ["entry_name", "valid_to"], as_dict=True
		)
		if not existing:
			action, old_value = "Додається", ""
		elif row.get("valid_to") and not existing.valid_to:
			action, old_value = "Закривається", existing.entry_name
		else:
			action, old_value = "Змінюється", existing.entry_name
		changes.append(
			{
				"entity": "Код класифікатора",
				"code": row["code"],
				"action": action,
				"valid_from": row["valid_from"],
				"old_value": old_value,
				"new_value": row["entry_name"],
				"conflict": 0,
			}
		)
	return changes
