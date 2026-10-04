"""Підстава запису: посилання на текст норми."""

import frappe
from frappe import _


def validate_basis_url(doc):
	"""Посилання на текст норми — повна адреса з https://. Без схеми посилання в картці
	не відкривається, і звірити значення з першоджерелом неможливо (SC-004)."""
	url = (doc.get("basis_url") or "").strip()
	if url and not url.lower().startswith(("https://", "http://")):
		frappe.throw(
			_("Посилання на текст норми має бути повною адресою, що починається з https://: {0}").format(url)
		)
