// Кнопки форми пакета. Порядок — за конвенціями: основна дія, потім відмова.
// Жодного бізнес-правила тут немає: усе рішення приймає сервер, клієнт лише викликає.
const UA_DECISIONS = ["Прийняти з пакета", "Залишити ручне"];

frappe.ui.form.on("UA Update Package", {
	refresh(frm) {
		if (frm.is_new()) return;
		// Збережений пакет змінюють лише дії нижче; кнопка «Зберегти» тут нічого не дала б,
		// крім відмови сервера.
		frm.disable_save();
		ua_show_warnings(frm);

		const state = frm.doc.state;
		const undecided = (frm.doc.preview || []).filter((row) => row.conflict && !row.decision);

		if (["Отримано", "Відхилено"].includes(state)) {
			frm.add_custom_button(__("Перевірити"), () => ua_call(frm, "verify_package"));
		}

		// Зняття блокування за строком — лише адміністратор, і лише для пакета,
		// зупиненого саме строком придатності (FR-037).
		if (
			state === "Відхилено" &&
			(frm.doc.reject_reason || "").includes("строк придатності маніфесту минув") &&
			frappe.user.has_role("System Manager")
		) {
			frm.add_custom_button(__("Зняти блокування за строком"), () =>
				frappe.confirm(
					__("Пакет прострочений. Зняти блокування й перевірити його знову? Дія потрапить у журнал."),
					() => ua_call(frm, "unlock_expired_package")
				)
			);
		}

		if (state === "Перевірено" && undecided.length) {
			frm.set_intro(
				__("Є розходження з записами, введеними вручну: {0}. Затвердити пакет можна після рішення по кожному.", [
					undecided.map((row) => row.code).join(", "),
				]),
				"orange"
			);
			frm.add_custom_button(__("Вирішити розходження"), () => ua_decide(frm, undecided)).addClass(
				"btn-primary"
			);
		}

		if (state === "До застосування") {
			frm.add_custom_button(__("Затвердити"), () =>
				frappe.confirm(__("Застосувати зміни з пакета?"), () =>
					frappe
						.call({ method: "ua_compliance.api.approve_package", args: { name: frm.doc.name }, freeze: true })
						.then(() => {
							frappe.show_alert({ message: __("Затверджено. Застосування виконується у фоні"), indicator: "green" });
							setTimeout(() => frm.reload_doc(), 3000);
						})
				)
			).addClass("btn-primary");
		}

		if (state === "Затверджено") {
			frm.set_intro(
				__("Пакет затверджено, застосування виконується у фоні. Результат — у журналі операцій."),
				"blue"
			);
		}

		if (["Перевірено", "До застосування", "Затверджено"].includes(state)) {
			frm.add_custom_button(__("Відхилити"), () =>
				frappe.prompt(
					[{ fieldname: "reason", fieldtype: "Small Text", label: __("Причина відхилення"), reqd: 1 }],
					({ reason }) => ua_call(frm, "reject_package", { reason }),
					__("Відхилити пакет")
				)
			);
		}
	},
});

function ua_call(frm, method, args = {}) {
	return frappe
		.call({ method: `ua_compliance.api.${method}`, args: { name: frm.doc.name, ...args }, freeze: true })
		.then(() => frm.reload_doc());
}

// Рішення по кожному розходженню: рядок передпоказу → «Прийняти з пакета» / «Залишити ручне».
function ua_decide(frm, rows) {
	const fields = rows.map((row) => ({
		fieldname: row.name,
		fieldtype: "Select",
		label: `${row.code} з ${frappe.datetime.str_to_user(row.valid_from)}: ${row.old_value || "—"} → ${row.new_value || "—"} (${row.action})`,
		options: ["", ...UA_DECISIONS].join("\n"),
	}));
	frappe.prompt(
		fields,
		(values) => {
			const decisions = Object.fromEntries(Object.entries(values).filter(([, value]) => value));
			ua_call(frm, "decide_conflicts", { decisions });
		},
		__("Розходження з записами, введеними вручну"),
		__("Зберегти рішення")
	);
}

// Попередження про давність і прострочення (FR-038) — у картці пакета, не лише в журналі.
function ua_show_warnings(frm) {
	frappe.call({ method: "ua_compliance.api.get_update_warnings" }).then(({ message }) => {
		if (message && message.length) {
			frm.dashboard.set_headline_alert(message.map(ua_link_packages).join("<br>"), "orange");
		}
	});
}

// Ім'я пакета в попередженні — посилання на сам пакет, щоб не шукати його в списку.
function ua_link_packages(text) {
	return frappe.utils
		.escape_html(text)
		.replace(/UA-PKG-[^\s,]+/g, (name) => `<a href="/app/ua-update-package/${encodeURIComponent(name)}">${name}</a>`);
}
