"""Завдання каналу оновлень: попередження про давність і прострочення."""

import frappe
from frappe.utils import add_days, getdate, today

from ua_compliance import journal


def warn_about_updates():
	"""Три попередження з контракту (FR-038). Мовчазної давнини не буває."""
	settings = frappe.get_single("UA Compliance Settings")
	if not settings.packages_enabled:
		return

	warnings = []

	threshold = int(settings.stale_warning_days or 45)
	last_applied = frappe.get_all(
		"UA Update Package",
		filters={"state": "Застосовано"},
		fields=["applied_on"],
		order_by="applied_on desc",
		limit=1,
	)
	if not last_applied:
		warnings.append("Оновлення законодавства ще жодного разу не застосовувалися")
	elif getdate(last_applied[0].applied_on) < getdate(add_days(today(), -threshold)):
		days = (getdate(today()) - getdate(last_applied[0].applied_on)).days
		warnings.append(f"Оновлення законодавства не надходили {days} днів")

	expired = frappe.get_all(
		"UA Update Package",
		filters={"state": ["in", ["Отримано", "До застосування"]], "expires_on": ["<", today()]},
		pluck="name",
	)
	for name in expired:
		warnings.append(f"Строк придатності пакета {name} минув")

	waiting = frappe.get_all("UA Update Package", filters={"state": "До застосування"}, pluck="name")
	for name in waiting:
		due = frappe.get_all(
			"UA Update Package Change",
			filters={"parent": name, "valid_from": ["<=", today()]},
			pluck="name",
		)
		if due:
			warnings.append(f"Є непримінений пакет {name}, дата дії якого вже настала")

	if warnings:
		journal.write("Приймання пакета", "Помилка", "\n".join(warnings))
	return warnings
