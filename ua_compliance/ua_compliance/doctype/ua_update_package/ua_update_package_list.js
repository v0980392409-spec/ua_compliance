// Список «Пакети оновлень» за контрактом екранів (екран 4): колір стану —
// за ui-conventions § 3, щоб відхилений пакет не губився сірим серед отриманих.

const UA_PACKAGE_STATE_COLORS = {
	"Отримано": "gray",
	"Перевірено": "blue",
	"До застосування": "yellow",
	"Затверджено": "green",
	"Застосовано": "green",
	"Відхилено": "red",
};

frappe.listview_settings["UA Update Package"] = {
	add_fields: ["state"],
	hide_name_column: true,
	get_indicator(doc) {
		return [__(doc.state), UA_PACKAGE_STATE_COLORS[doc.state] || "gray", `state,=,${doc.state}`];
	},
};
