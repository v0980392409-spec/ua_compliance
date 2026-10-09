"""Робочий календар і норма часу — з параметрів, а не з чужої бібліотеки.

Чому не штатна кнопка підстановки свят: вона бере сторонню бібліотеку, у якій
воєнний стан зашитий умовою по року, а оновлюється бібліотека лише з перезбиранням
образу. Тут правило — дані: свято є записом з періодом дії, а ознака воєнного стану —
звичайним законодавчим параметром з датою.
"""

from datetime import date, timedelta

import frappe
from frappe import _
from frappe.utils import getdate, today

from ua_compliance.api import get_parameter
from ua_compliance.calendar.easter import TRINITY_OFFSET, orthodox_easter
from ua_compliance.calendar.rules import compose_days_off

MARTIAL_LAW_CODE = "MARTIAL_LAW"


class PastDatesChange(frappe.ValidationError):
	"""Перебудова зачіпає минулі дати й чекає явного підтвердження (FR-046)."""


def martial_law_active(on_date, code=MARTIAL_LAW_CODE):
	"""Ознака воєнного стану — звичайний параметр: не визначена, значить невідома.

	Код параметра можна підмінити — цим користується харнес, щоб не писати
	вигадану історію в робочий параметр.
	"""
	return bool(get_parameter(code, on_date))


def holidays_for_year(year: int):
	"""Повертає [(дата, назва, вихідний)] за правилами, чинними того року."""
	start, end = date(year, 1, 1), date(year, 12, 31)
	rules = frappe.get_all(
		"UA Holiday Rule",
		filters=[["valid_from", "<=", end]],
		or_filters=[["valid_to", "is", "not set"], ["valid_to", ">=", start]],
		fields=["holiday_name", "rule_type", "day", "month", "offset_days", "is_day_off", "valid_from", "valid_to"],
	)

	easter = orthodox_easter(year)
	result = []
	for rule in rules:
		if rule.rule_type == "Фіксована дата":
			if not (rule.day and rule.month):
				continue
			occurrence = date(year, int(rule.month), int(rule.day))
		elif rule.rule_type == "Великдень":
			occurrence = easter + timedelta(days=int(rule.offset_days or 0))
		else:
			occurrence = easter + timedelta(days=TRINITY_OFFSET + int(rule.offset_days or 0))

		if occurrence < getdate(rule.valid_from):
			continue
		if rule.valid_to and occurrence > getdate(rule.valid_to):
			continue
		result.append((occurrence, rule.holiday_name, bool(rule.is_day_off)))
	return sorted(result)


def build_holiday_list(year: int, title=None, confirm_past=False, martial_law_code=MARTIAL_LAW_CODE):
	"""Збирає штатний календар вихідних на рік. Повертає зведення.

	Повторний запуск на тих самих параметрах дає той самий склад і не створює дублів.
	Зміна, що зачіпає минулі дати, потребує явного підтвердження (FR-046).
	"""
	title = title or _("Робочий календар {0}").format(year)
	start, end = date(year, 1, 1), date(year, 12, 31)
	# Ознака на початок року лишається умовою: невідома — значить, будувати не з чого.
	martial_law = martial_law_active(start, martial_law_code)

	# Воєнний стан звіряється на дату кожного свята: якщо він закінчиться посеред року,
	# свята після цієї дати знову вихідні (спека, крайні випадки US4). Свято на вихідний
	# поза воєнним станом переносить вихідний (ч. 3 ст. 67 КЗпП) — див. compose_days_off.
	weekly_off = _("Вихідний день")
	entries, kinds = [], {}
	for occurrence, kind, names in compose_days_off(
		year, holidays_for_year(year), lambda day: martial_law_active(day, martial_law_code)
	):
		if kind == "weekend":
			description = weekly_off
		elif kind == "transfer":
			description = _("Перенесений вихідний: {0}").format("; ".join(names))
		else:
			description = "; ".join(names)
		entries.append((occurrence, description, kind == "weekend"))
		kinds[kind] = kinds.get(kind, 0) + 1
	existing = frappe.db.exists("Holiday List", title)
	if existing:
		doc = frappe.get_doc("Holiday List", title)
		previous = {(getdate(row.holiday_date), row.description) for row in doc.holidays}
		incoming = {(occurrence, name) for occurrence, name, _off in entries}
		touched_past = {row for row in previous ^ incoming if row[0] < getdate(today())}
		if touched_past and not confirm_past:
			frappe.throw(
				_("Перебудова змінює {0} минулих дат у календарі {1}. Потрібне явне підтвердження").format(
					len(touched_past), title
				),
				PastDatesChange,
			)
		doc.set("holidays", [])
	else:
		doc = frappe.new_doc("Holiday List")
		doc.holiday_list_name = title
		doc.name = title

	doc.from_date = start
	doc.to_date = end
	for occurrence, name, is_weekly_off in entries:
		doc.append(
			"holidays",
			{
				"holiday_date": occurrence,
				"description": name,
				"weekly_off": 1 if is_weekly_off else 0,
			},
		)
	doc.save(ignore_permissions=True)

	summary = {
		"title": title,
		"total": len(entries),
		"martial_law": martial_law,
		"holidays": kinds.get("holiday", 0),
		"transferred": kinds.get("transfer", 0),
		"past_changed": len(touched_past) if existing else 0,
	}
	# Кожна побудова — у журналі; підтверджена зміна минулих дат названа окремо (FR-046).
	from ua_compliance import journal

	message = _("{0}: днів відпочинку {1}, з них свят {2}, перенесених вихідних {3}{4}").format(
		title,
		summary["total"],
		summary["holidays"],
		summary["transferred"],
		_(", воєнний стан — свята не вихідні") if martial_law else "",
	)
	if summary["past_changed"]:
		message += _("; підтверджено зміну минулих дат: {0}").format(summary["past_changed"])
	journal.write("Перебудова календаря", "Успішно", message, counts={"created": summary["total"]})
	return summary


def build_next_year():
	"""Щорічне завдання: календар наступного року будується заздалегідь, у грудні.

	Наступний рік — лише майбутні дати, тож підтвердження не потрібне; поточний рік
	перебудовує людина кнопкою, бо там можуть змінитися минулі дати.
	"""
	try:
		return build_holiday_list(getdate(today()).year + 1)
	except Exception as error:
		from ua_compliance import journal

		journal.write("Перебудова календаря", "Помилка", str(error))


def working_time(year: int, hours_per_day=8.0, title=None):
	"""Норма часу **рахується** за календарем, а не зберігається окремим числом."""
	title = title or _("Робочий календар {0}").format(year)
	if not frappe.db.exists("Holiday List", title):
		frappe.throw(_("Календар {0} не побудовано").format(title))

	off_days = {
		getdate(row.holiday_date)
		for row in frappe.get_all(
			"Holiday", filters={"parent": title}, fields=["holiday_date"], limit=400
		)
	}

	months = []
	for month in range(1, 13):
		days = 0
		current = date(year, month, 1)
		while current.month == month:
			if current not in off_days:
				days += 1
			current += timedelta(days=1)
		months.append({"month": month, "working_days": days, "hours": round(days * hours_per_day, 2)})

	return {
		"months": months,
		"working_days": sum(m["working_days"] for m in months),
		"hours": round(sum(m["hours"] for m in months), 2),
	}
