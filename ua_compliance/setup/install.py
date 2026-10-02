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
			"description": "Як в as-is регістрі «Курси валют»: скільки одиниць валюти котирується",
		},
		{
			"fieldname": "ua_source",
			"label": "Джерело завантаження",
			"fieldtype": "Data",
			"insert_after": "ua_multiplicity",
			"read_only": 1,
		},
	]
}


def after_install():
	setup_fields()
	disable_external_rate_provider()


def after_migrate():
	setup_fields()
	# Постачальник вимикається і на міграції, а не лише на встановленні: якщо його
	# знову увімкнули, документи почнуть рахувати за неофіційним курсом мовчки.
	# Факт вимкнення пишемо в журнал, щоб дія не була невидимою.
	if disable_external_rate_provider():
		_log_provider_disabled()


def setup_fields():
	create_custom_fields(CURRENCY_EXCHANGE_FIELDS, ignore_validate=True)


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
