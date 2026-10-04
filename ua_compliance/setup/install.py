"""Встановлення й міграція: свої поля запису курсу і вимкнення стороннього постачальника."""

import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

CURRENCY_EXCHANGE_FIELDS = {
	"Currency Exchange": [
		{
			"fieldname": "ua_source_rate",
			"label": "Курс джерела",
			"fieldtype": "Float",
			"precision": "6",
			"insert_after": "exchange_rate",
			"read_only": 1,
			"description": "Значення, як його віддало джерело, до зведення до однієї одиниці",
		},
		{
			"fieldname": "ua_multiplicity",
			"label": "Кратність",
			"fieldtype": "Int",
			"default": "1",
			"insert_after": "ua_source_rate",
			"read_only": 1,
			"in_list_view": 1,
			"description": "Як в as-is регістрі «Курси валют»: скільки одиниць валюти котирується",
		},
		{
			"fieldname": "ua_source",
			"label": "Джерело завантаження",
			"fieldtype": "Data",
			"insert_after": "ua_multiplicity",
			"read_only": 1,
			"in_list_view": 1,
		},
	]
}


def after_install():
	setup_fields()
	setup_warnings_block()
	disable_external_rate_provider()


def after_migrate():
	setup_fields()
	setup_warnings_block()
	# Постачальник вимикається і на міграції, а не лише на встановленні: якщо його
	# знову увімкнули, документи почнуть рахувати за неофіційним курсом мовчки.
	# Факт вимкнення пишемо в журнал, щоб дія не була невидимою.
	if disable_external_rate_provider():
		_log_provider_disabled()


def setup_fields():
	create_custom_fields(CURRENCY_EXCHANGE_FIELDS, ignore_validate=True)
	# Список курсів — за датою, новіші вгорі (контракт екранів, екран 1): так їх
	# дивляться в as-is регістрі «Курси валют», а штатно список іде за ідентифікатором.
	# «У валюту» в обліку завжди гривня — колонка в списку нічого не каже.
	if frappe.db.get_value(
		"Property Setter", {"doc_type": "Currency Exchange", "field_name": "to_currency", "property": "in_list_view"}, "value"
	) != "0":
		frappe.make_property_setter(
			{"doctype": "Currency Exchange", "fieldname": "to_currency", "property": "in_list_view", "value": "0", "property_type": "Check"},
			validate_fields_for_doctype=False,
		)
	for prop, value in (("sort_field", "date"), ("sort_order", "DESC")):
		if frappe.db.get_value(
			"Property Setter", {"doc_type": "Currency Exchange", "doctype_or_field": "DocType", "property": prop}, "value"
		) == value:
			continue
		frappe.make_property_setter(
			{"doctype": "Currency Exchange", "doctype_or_field": "DocType", "property": prop, "value": value},
			validate_fields_for_doctype=False,
		)


def disable_external_rate_provider():
	"""Курс береться лише з першоджерела (FR-004): штатного постачальника вимикаємо.

	Він змішує котирування кількох центробанків, а бухгалтерський облік ведеться
	за офіційним курсом НБУ (НП(С)БО 21).
	"""
	settings = frappe.get_single("Currency Exchange Settings")
	if settings.disabled:
		return False
	settings.disabled = 1
	settings.save(ignore_permissions=True)
	return True


def _log_provider_disabled():
	from frappe.utils import now_datetime

	frappe.get_doc(
		{
			"doctype": "UA Operation Log",
			"kind": "Завантаження курсу",
			"result": "Успішно",
			"started_at": now_datetime(),
			"finished_at": now_datetime(),
			"message": "Зовнішнього постачальника курсів вимкнено: курс береться лише з першоджерела (FR-004)",
			"triggered_by": "Administrator",
		}
	).insert(ignore_permissions=True)


WARNINGS_BLOCK = "Попередження законодавства"
WARNINGS_HTML = '<div class="ua-warnings alert alert-warning" style="display:none;margin:0"></div>'
# Блок показує ті самі попередження, що й журнал і картка пакета (FR-038); коли їх немає,
# він ховається й не займає місця в розділі.
WARNINGS_SCRIPT = """
frappe.call("ua_compliance.api.get_update_warnings").then(({ message }) => {
	const box = root_element.querySelector(".ua-warnings");
	if (!message || !message.length) return;
	box.innerHTML = message.map((text) => "<div>" + frappe.utils.escape_html(text) + "</div>").join("");
	box.style.display = "block";
});
"""


def setup_warnings_block():
	"""Блок попереджень у розділі «Законодавство». Custom HTML Block не має файла модуля,
	тож заводимо його тут, ідемпотентно."""
	values = {"html": WARNINGS_HTML, "script": WARNINGS_SCRIPT, "style": "", "private": 0}
	if frappe.db.exists("Custom HTML Block", WARNINGS_BLOCK):
		block = frappe.get_doc("Custom HTML Block", WARNINGS_BLOCK)
		block.update(values)
		block.save(ignore_permissions=True)
		return
	block = frappe.new_doc("Custom HTML Block")
	block.update(values)
	block.set("__newname", WARNINGS_BLOCK)  # ім'я задається вручну (autoname: prompt)
	block.insert(ignore_permissions=True)
