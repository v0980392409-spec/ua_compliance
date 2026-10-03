// Кнопки форми пакета. Порядок — за конвенціями: основна дія, потім відмова.
// Жодного бізнес-правила тут немає: усе рішення приймає сервер, клієнт лише викликає.
frappe.ui.form.on("UA Update Package", {
	refresh(frm) {
		if (frm.is_new()) return;
		// Збережений пакет змінюють лише дії нижче; кнопка «Зберегти» тут нічого не дала б,
		// крім відмови сервера.
		frm.disable_save();

		if (["Отримано", "Відхилено"].includes(frm.doc.state)) {
			frm.add_custom_button(__("Перевірити"), () =>
				frappe
					.call({ method: "ua_compliance.api.verify_package", args: { name: frm.doc.name }, freeze: true })
					.then(() => frm.reload_doc())
			);
		}

		if (frm.doc.state === "До застосування") {
			frm.add_custom_button(__("Затвердити"), () =>
				frappe.confirm(__("Застосувати зміни з пакета?"), () =>
					frappe
						.call({ method: "ua_compliance.api.approve_package", args: { name: frm.doc.name }, freeze: true })
						.then(() => frm.reload_doc())
				)
			).addClass("btn-primary");

			frm.add_custom_button(__("Відхилити"), () =>
				frappe.prompt(
					[{ fieldname: "reason", fieldtype: "Small Text", label: __("Причина відхилення"), reqd: 1 }],
					({ reason }) =>
						frappe
							.call({
								method: "ua_compliance.api.reject_package",
								args: { name: frm.doc.name, reason },
								freeze: true,
							})
							.then(() => frm.reload_doc()),
					__("Відхилити пакет")
				)
			);
		}
	},
});
