// Список «Законодавчі параметри» за контрактом екранів (екран 2).
// Значення лежить у полі свого виду: ознака — у прапорці, дата — у полі дати. Колонка
// списку показує числове поле, тож без форматера чинний воєнний стан виглядав як
// «0.000000» (спіймано на демо 03.10.2026). Нічого не зберігаємо вдруге — лише показуємо.

frappe.listview_settings["UA Legal Parameter"] = {
	add_fields: ["value_type", "value_flag", "value_date", "value_text", "unit", "source"],
	hide_name_column: true,

	// Ручний запис помітний одразу: контракт вимагає індикатора «введено вручну».
	get_indicator(doc) {
		if (doc.source === "Введено вручну") {
			return [__("Введено вручну"), "orange", "source,=,Введено вручну"];
		}
		return [__("З пакета"), "green", "source,=,З пакета"];
	},

	formatters: {
		// Форматер має повертати розмітку, а не голий текст: список міряє ширину колонки
		// викликом $(html), і jQuery сприймає текст без тегів як CSS-селектор — «5 %»
		// кидає виняток, і відмальовка рветься на п'ятому рядку (спіймано на демо).
		value_number(value, df, doc) {
			return `<span class="ellipsis">${ua_parameter_value(doc)}</span>`;
		},
	},
};

function ua_parameter_value(doc) {
	switch (doc.value_type) {
		case "Ознака":
			return cint(doc.value_flag) ? __("Так") : __("Ні");
		case "Дата":
			return frappe.datetime.str_to_user(doc.value_date);
		case "Рядок":
			return frappe.utils.escape_html(doc.value_text || "");
	}
	// Число без хвостових нулів: 1,5 %, а не 1.500000.
	const number = flt(doc.value_number);
	const decimals = (String(number).split(".")[1] || "").length;
	const shown = format_number(number, null, Math.min(decimals, 6));
	return doc.unit ? `${shown} ${frappe.utils.escape_html(doc.unit)}` : shown;
}
