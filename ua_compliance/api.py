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


def _package_bytes(package):
	"""Читає вкладений файл пакета. Пакет завжди приходить файлом — і з каналу роздачі,
	і в ізольованому контурі, тому шлях читання один (FR-036)."""
	attachments = frappe.get_all(
		"File",
		filters={"attached_to_doctype": "UA Update Package", "attached_to_name": package.name},
		fields=["name", "file_name"],
		order_by="creation desc",
		limit=1,
	)
	if not attachments:
		frappe.throw(_("До пакета не прикріплено файл"))
	return frappe.get_doc("File", attachments[0].name).get_content(encodings=[])


@frappe.whitelist()
def verify_package(name):
	"""Перевіряє прикріплений пакет за контрактом і будує передпоказ."""
	package = frappe.get_doc("UA Update Package", name)
	ok = package.run_verification(_package_bytes(package))
	package.reload()
	return {"ok": ok, "state": package.state, "reason": package.reject_reason}


@frappe.whitelist()
def approve_package(name):
	"""Затвердження людиною і застосування однією транзакцією."""
	package = frappe.get_doc("UA Update Package", name)
	summary = package.approve_and_apply(_package_bytes(package))
	return {"state": "Застосовано", **summary}


@frappe.whitelist()
def reject_package(name, reason):
	"""Відхилення з обов'язковою причиною."""
	if not (reason or "").strip():
		frappe.throw(_("Вкажіть причину відхилення"))
	package = frappe.get_doc("UA Update Package", name)
	package.state = "Відхилено"
	package.reject_reason = reason
	package.save_by_action()
	from ua_compliance import journal

	journal.write("Приймання пакета", "Помилка", f"Відхилено вручну: {reason}", package=package.name)
	return {"state": package.state}


CALENDAR_ROLES = ("Відповідальний за законодавство", "System Manager")


@frappe.whitelist()
def rebuild_calendar(year, confirm_past=0):
	"""Будує робочий календар року з правил свят і ознаки воєнного стану.

	Якщо перебудова змінює минулі дати, повертає запит на підтвердження замість
	помилки: кнопка показує його людині й повторює виклик з confirm_past (FR-046).
	"""
	from ua_compliance.calendar.build import PastDatesChange, build_holiday_list

	if not set(CALENDAR_ROLES) & set(frappe.get_roles()):
		frappe.throw(_("Будувати календар може лише роль «{0}»").format(CALENDAR_ROLES[0]))
	try:
		return build_holiday_list(int(year), confirm_past=bool(int(confirm_past or 0)))
	except PastDatesChange as error:
		return {"needs_confirmation": str(error)}
