// Дерево «Класифікатори» за контрактом екранів (екран 9): КАТОТТГ і КВЕД ієрархією, як в
// ієрархічному довіднику 1С. Список лишається поруч (перемикач «Вигляд списку»): пошук і
// фільтри — там, дерево — для огляду структури. Лише читання: ні додавання, ні правки.

frappe.provide("frappe.treeview_settings");

frappe.treeview_settings["UA Classifier Entry"] = {
	get_tree_nodes:
		"ua_compliance.ua_compliance.doctype.ua_classifier_entry.ua_classifier_entry.get_children",
	// Штатний заголовок вийшов би «Код класифікатора Дерево».
	title: __("Класифікатори"),

	// Корінь — сам класифікатор із фільтра; запиту «знайди єдиний корінь» не треба.
	get_tree_root: false,
	root_label: "КАТОТТГ",
	filters: [
		{
			fieldname: "classifier",
			fieldtype: "Select",
			options: "КАТОТТГ\nКВЕД",
			label: __("Класифікатор"),
			default: "КАТОТТГ",
			reqd: 1,
		},
	],

	// «Розгорнути все» на КАТОТТГ — ~2 000 запитів на сервер і 31 тисяча вузлів у браузері.
	show_expand_all: false,
	disable_add_node: true,
	toolbar: [
		{
			label: __("Відкрити"),
			condition: (node) => !node.is_root,
			click: (node) => frappe.set_route("Form", "UA Classifier Entry", node.data.value),
		},
	],

	// КВЕД читають кодом («62.01 Комп'ютерне програмування»), КАТОТТГ — назвою, а
	// дев'ятнадцятизначний код лише довідково, сірим. Закритий код — сірим і
	// перекресленим (контракт, екран 9): з дерева він не зникає, бо класифікатор не
	// видаляє записів (FR-049).
	get_label(node) {
		const data = node.data || {};
		if (node.is_root || !data.code) {
			return frappe.utils.escape_html(node.label);
		}
		const title = frappe.utils.escape_html(data.title);
		const code = frappe.utils.escape_html(data.code);
		const html =
			data.classifier === "КВЕД" ? `${code} ${title}` : `${title} <span class="text-muted">${code}</span>`;
		if (data.valid_to && data.valid_to < frappe.datetime.get_today()) {
			return `<s class="text-muted">${html}</s>`;
		}
		return html;
	},
};
