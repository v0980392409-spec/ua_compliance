"""Канал «Календар»: правила свят із пакета — зіставлення, передпоказ і застосування.

Правило зіставляється з наявним за місцем у році (slot_key), а не за назвою чи датами:
закон перейменовує свята, а ручний запис міг почати відлік з іншого дня. Передпоказ і
застосування беруть ту саму функцію зіставлення — людина затверджує рівно те, що буде
записано. Функції не роблять commit: це справа того, хто викликає.
"""

import frappe
from frappe.utils import add_days, formatdate, getdate

FIELDS = [
	"name",
	"holiday_name",
	"rule_type",
	"day",
	"month",
	"offset_days",
	"is_day_off",
	"valid_from",
	"valid_to",
	"source",
]


def _slot_records(row):
	"""Наявні правила того самого місця в році, за датою початку."""
	filters = {"rule_type": row["rule_type"]}
	if row["rule_type"] == "Фіксована дата":
		filters.update(day=int(row["day"]), month=int(row["month"]))
	records = frappe.get_all("UA Holiday Rule", filters=filters, fields=FIELDS, order_by="valid_from")
	if row["rule_type"] != "Фіксована дата":
		offset = int(row.get("offset_days") or 0)
		records = [record for record in records if int(record.offset_days or 0) == offset]
	return records


def match(row):
	"""Що пакет зробить із рядком: ("update", запис) | ("close", запис) | ("add", None).

	- запис того самого місця з тією самою датою початку — оновлюється;
	- запис, що почався пізніше й перекривається з періодом рядка, пакет перебирає на
	  себе: інакше того року діяли б два правила одного свята (так виглядає ручний запис
	  «з 2000 року» проти пакета з історією від 1972-го);
	- чинний запис, що почався раніше, закривається днем перед початком рядка.
	"""
	valid_from = getdate(row["valid_from"])
	valid_to = getdate(row["valid_to"]) if row.get("valid_to") else None
	records = _slot_records(row)
	for record in records:
		if getdate(record.valid_from) == valid_from:
			return "update", record
	for record in records:
		start = getdate(record.valid_from)
		if start > valid_from and (valid_to is None or start <= valid_to):
			return "update", record
	for record in reversed(records):
		if getdate(record.valid_from) < valid_from and (
			not record.valid_to or getdate(record.valid_to) >= valid_from
		):
			return "close", record
	return "add", None


def rule_text(record):
	"""Правило одним рядком для передпоказу: назва, період і, якщо так, «не вихідний»."""
	text = f"{record.get('holiday_name')}, з {formatdate(record.get('valid_from'))}"
	if record.get("valid_to"):
		text += f" до {formatdate(record.get('valid_to'))}"
	if not int(record.get("is_day_off") or 0):
		text += " — не вихідний"
	return text


def _same(record, row):
	return (
		record.holiday_name == row["holiday_name"]
		and int(record.is_day_off or 0) == int(row["is_day_off"])
		and getdate(record.valid_from) == getdate(row["valid_from"])
		and (getdate(record.valid_to) if record.valid_to else None)
		== (getdate(row["valid_to"]) if row.get("valid_to") else None)
	)


def preview(rows):
	"""Рядки передпоказу для таблиці пакета; розходження з ручними записами позначені."""
	changes = []
	for row in rows:
		action, record = match(row)
		valid_from = getdate(row["valid_from"])
		base = {"entity": "Свято", "code": row["code"]}
		if action == "update":
			changes.append(
				{
					**base,
					"action": "Змінюється",
					"valid_from": valid_from,
					"old_value": rule_text(record),
					"new_value": rule_text(row),
					"conflict": 1 if record.source == "Введено вручну" and not _same(record, row) else 0,
				}
			)
			continue
		if action == "close":
			changes.append(
				{
					**base,
					"action": "Закривається",
					"valid_from": add_days(valid_from, -1),
					"old_value": rule_text(record),
					"new_value": "",
					"conflict": 1 if record.source == "Введено вручну" else 0,
				}
			)
		changes.append(
			{
				**base,
				"action": "Додається",
				"valid_from": valid_from,
				"old_value": "",
				"new_value": rule_text(row),
				"conflict": 0,
			}
		)
	return changes


def _fill(doc, row, source_reference):
	fixed = row["rule_type"] == "Фіксована дата"
	doc.holiday_name = row["holiday_name"]
	doc.rule_type = row["rule_type"]
	doc.day = int(row["day"]) if fixed else None
	doc.month = int(row["month"]) if fixed else None
	doc.offset_days = None if fixed else int(row.get("offset_days") or 0)
	doc.is_day_off = int(row["is_day_off"])
	# Дати з пакета — рядки; приводимо одразу (урок параметрів 04.10.2026)
	doc.valid_from = getdate(row["valid_from"])
	doc.valid_to = getdate(row["valid_to"]) if row.get("valid_to") else None
	doc.basis_type = row["basis_type"]
	doc.basis_number = row["basis_number"]
	doc.basis_date = getdate(row["basis_date"])
	doc.basis_url = row["basis_url"]
	doc.source = "З пакета"
	doc.source_reference = source_reference


def apply(rows, source_reference):
	"""Застосовує рядки каналу «Календар». Повертає зведення."""
	created = closed = updated = 0
	frappe.flags.ua_applying_package = True
	try:
		for row in rows:
			action, record = match(row)
			if action == "update":
				doc = frappe.get_doc("UA Holiday Rule", record.name)
				_fill(doc, row, source_reference)
				doc.save(ignore_permissions=True)
				updated += 1
				continue
			if action == "close":
				previous = frappe.get_doc("UA Holiday Rule", record.name)
				previous.valid_to = add_days(getdate(row["valid_from"]), -1)
				previous.save(ignore_permissions=True)
				closed += 1
			doc = frappe.new_doc("UA Holiday Rule")
			_fill(doc, row, source_reference)
			doc.insert(ignore_permissions=True)
			created += 1
	finally:
		frappe.flags.ua_applying_package = False
	return {"created": created, "closed": closed, "updated": updated}
