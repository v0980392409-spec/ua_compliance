"""Журнал операцій — одне місце запису для всіх операцій застосунку (принцип IV)."""

import frappe
from frappe.utils import now_datetime


def write(kind, result, message="", package=None, started_at=None, counts=None):
	counts = counts or {}
	return frappe.get_doc(
		{
			"doctype": "UA Operation Log",
			"kind": kind,
			"result": result,
			"started_at": started_at or now_datetime(),
			"finished_at": now_datetime(),
			"checked_count": counts.get("checked") or 0,
			"created_count": counts.get("created") or 0,
			"updated_count": counts.get("updated") or 0,
			"message": message,
			"package": package,
			"triggered_by": frappe.session.user,
		}
	).insert(ignore_permissions=True)
