# Copyright (c) 2026, Riverside and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document

# Деревом показуються ієрархічні класифікатори (контракт екранів, екран 9); ДК 003 — списком.
TREE_CLASSIFIERS = ("КАТОТТГ", "КВЕД")


class UAClassifierEntry(Document):
	# Класифікатор лише для читання незалежно від ролі (FR-048), і Адміністратора це теж
	# стосується: права DocPerm він оминає, тож межа тримається тут, на сервері, — як у
	# записів параметрів із пакета. Пакет ставить прапорець запиту на час застосування.
	def validate(self):
		if frappe.flags.get("ua_applying_package"):
			return
		frappe.throw(_("Класифікатор змінюється лише пакетом оновлень — записи доступні тільки для читання"))

	def on_trash(self):
		frappe.throw(_("Код класифікатора не видаляється — виведений з обігу код закривається датою"))


@frappe.whitelist()
def get_children(doctype=None, parent=None, is_root=False, classifier=None, **kwargs):
	"""Вузли дерева класифікатора: діти одного запису або корені класифікатора.

	Ієрархію задає «Код батьківського запису» — так, як його привіз пакет. Вкладених
	множин немає свідомо: вони тримали б ту саму ієрархію другим полем, яке треба
	перераховувати після кожного пакета, а дубль — джерело розходження.
	Корінь дерева — сама назва класифікатора з фільтра.
	"""
	if classifier not in TREE_CLASSIFIERS:
		frappe.throw(_("Дерево є лише для класифікаторів: {0}").format(", ".join(TREE_CLASSIFIERS)))

	if frappe.utils.sbool(is_root) or not parent or parent == classifier:
		parent_filter = ["parent_code", "is", "not set"]
	else:
		parent_code = frappe.db.get_value("UA Classifier Entry", {"name": parent, "classifier": classifier}, "code")
		if not parent_code:
			return []
		parent_filter = ["parent_code", "=", parent_code]

	# get_list, а не get_all: дерево показує лише те, що користувач має право читати.
	rows = frappe.get_list(
		"UA Classifier Entry",
		filters=[["classifier", "=", classifier], parent_filter],
		fields=["name as value", "entry_name as title", "code", "classifier", "valid_to"],
		order_by="code asc",
		limit_page_length=0,
	)
	codes = [row.code for row in rows]
	with_children = (
		set(
			frappe.get_all(
				"UA Classifier Entry",
				filters={"classifier": classifier, "parent_code": ["in", codes]},
				pluck="parent_code",
				group_by="parent_code",
			)
		)
		if codes
		else set()
	)
	for row in rows:
		row.expandable = 1 if row.code in with_children else 0
	return rows
