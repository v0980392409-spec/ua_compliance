# Copyright (c) 2026, Riverside and contributors
# For license information, please see license.txt

from frappe.model.document import Document

from ua_compliance.basis import validate_basis_url


class UAHolidayRule(Document):
	def validate(self):
		validate_basis_url(self)
