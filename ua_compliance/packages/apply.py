"""Застосування пакета — однією транзакцією.

Функція не робить `commit`: це справа того, хто викликає. Частково застосованого
пакета не буває — при помилці не застосовується нічого (FR-033).
"""

import frappe
from frappe.utils import add_days, getdate

VALUE_FIELD = {
	"Сума": "value_number",
	"Число": "value_number",
	"Відсоток": "value_number",
	"Дата": "value_date",
	"Рядок": "value_text",
	"Ознака": "value_flag",
}


def apply_parameters(rows, source_reference):
	"""Застосовує рядки каналу «Параметри». Повертає зведення."""
	created = closed = updated = 0
	frappe.flags.ua_applying_package = True
	try:
		for row in rows:
			code, valid_from = row["code"], getdate(row["valid_from"])

			existing = frappe.db.get_value(
				"UA Legal Parameter", {"code": code, "valid_from": valid_from}, "name"
			)
			if existing:
				doc = frappe.get_doc("UA Legal Parameter", existing)
				_fill(doc, row, source_reference)
				doc.save(ignore_permissions=True)
				updated += 1
				continue

			open_record = frappe.db.sql(
				"""
				select name from `tabUA Legal Parameter`
				where code = %(code)s and valid_from < %(valid_from)s
				  and (valid_to is null or valid_to >= %(valid_from)s)
				order by valid_from desc limit 1
				""",
				{"code": code, "valid_from": valid_from},
			)
			if open_record:
				previous = frappe.get_doc("UA Legal Parameter", open_record[0][0])
				previous.valid_to = add_days(valid_from, -1)
				previous.save(ignore_permissions=True)
				closed += 1

			doc = frappe.new_doc("UA Legal Parameter")
			doc.code = code
			doc.valid_from = valid_from
			_fill(doc, row, source_reference)
			doc.insert(ignore_permissions=True)
			created += 1
	finally:
		frappe.flags.ua_applying_package = False

	return {"created": created, "closed": closed, "updated": updated}


def _fill(doc, row, source_reference):
	doc.parameter_name = row["parameter_name"]
	doc.value_type = row["value_type"]
	doc.set(VALUE_FIELD[row["value_type"]], row["value"])
	doc.unit = row.get("unit")
	doc.valid_to = row.get("valid_to") or None
	doc.basis_type = row["basis_type"]
	doc.basis_number = row["basis_number"]
	doc.basis_date = row["basis_date"]
	doc.basis_clause = row.get("basis_clause")
	doc.basis_url = row["basis_url"]
	doc.verified_on = row["verified_on"]
	doc.source = "З пакета"
	doc.source_reference = source_reference


def apply_classifiers(rows, source_reference):
	"""Застосовує рядки каналу «Класифікатори».

	Нові коди вставляються **пакетно**, а не документами по одному: класифікатор —
	довідник лише для читання без власної логіки, а на обсязі КАТОТТГ (понад 30 тисяч
	кодів) вставка документами розриває зʼєднання з СУБД (спіймано харнесом 02.10.2026).
	Транзакція при цьому лишається однією.

	Виведений з обігу код **закривається датою**, а не видаляється: посилання на нього
	в документах лишається читабельним (FR-049, FR-050).
	"""
	created = closed = updated = 0
	now = frappe.utils.now()
	user = frappe.session.user
	fields = [
		"name",
		"creation",
		"modified",
		"owner",
		"modified_by",
		"classifier",
		"code",
		"entry_name",
		"parent_code",
		"level",
		"valid_from",
		"valid_to",
		"source_reference",
	]
	fresh = []

	frappe.flags.ua_applying_package = True
	try:
		for row in rows:
			name = f"{row['classifier']}-{row['code']}"
			level = int(row["level"]) if (row.get("level") or "").isdigit() else None
			valid_to = row.get("valid_to") or None

			if frappe.db.exists("UA Classifier Entry", name):
				was_open = not frappe.db.get_value("UA Classifier Entry", name, "valid_to")
				doc = frappe.get_doc("UA Classifier Entry", name)
				doc.update(
					{
						"entry_name": row["entry_name"],
						"parent_code": row.get("parent_code") or None,
						"level": level,
						"valid_from": row["valid_from"],
						"valid_to": valid_to,
						"source_reference": source_reference,
					}
				)
				doc.save(ignore_permissions=True)
				if was_open and valid_to:
					closed += 1
				else:
					updated += 1
				continue

			fresh.append(
				(
					name,
					now,
					now,
					user,
					user,
					row["classifier"],
					row["code"],
					row["entry_name"],
					row.get("parent_code") or None,
					level,
					row["valid_from"],
					valid_to,
					source_reference,
				)
			)

		if fresh:
			frappe.db.bulk_insert("UA Classifier Entry", fields, fresh, chunk_size=2000)
			created = len(fresh)
	finally:
		frappe.flags.ua_applying_package = False

	return {"created": created, "closed": closed, "updated": updated}


def active_codes(classifier, on_date, search=None, limit=50):
	"""Коди, чинні на дату: закриті до вибору не пропонуються (FR-051)."""
	filters = [
		["classifier", "=", classifier],
		["valid_from", "<=", on_date],
	]
	if search:
		filters.append(["code", "like", f"%{search}%"])
	return frappe.get_all(
		"UA Classifier Entry",
		filters=filters,
		or_filters=[["valid_to", "is", "not set"], ["valid_to", ">=", on_date]],
		fields=["code", "entry_name"],
		order_by="code",
		limit=limit,
	)
