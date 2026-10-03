// Кнопка «Побудувати календар»: правила свят → штатний календар вихідних року.
// Жодного правила тут немає: що будувати й чи зачеплено минулі дати, вирішує сервер,
// клієнт лише питає рік і, якщо сервер просить, — підтвердження (FR-046).

frappe.listview_settings["UA Holiday Rule"] = {
	onload(listview) {
		listview.page.add_inner_button(__("Побудувати календар"), () => {
			frappe.prompt(
				{
					fieldname: "year",
					fieldtype: "Int",
					label: __("Рік"),
					reqd: 1,
					default: new Date().getFullYear(),
				},
				({ year }) => build(year, 0),
				__("Побудувати робочий календар"),
				__("Побудувати")
			);
		});
	},
};

function build(year, confirm_past) {
	frappe
		.call({
			method: "ua_compliance.api.rebuild_calendar",
			args: { year, confirm_past },
			freeze: true,
		})
		.then(({ message }) => {
			if (message.needs_confirmation) {
				frappe.confirm(message.needs_confirmation, () => build(year, 1));
				return;
			}
			frappe.msgprint({
				title: message.title,
				indicator: "green",
				message: __("Днів відпочинку: {0}, з них свят: {1}.", [message.total, message.holidays]) +
					(message.martial_law ? "<br>" + __("Воєнний стан: свята не є вихідними.") : "") +
					"<br>" + `<a href="/app/holiday-list/${encodeURIComponent(message.title)}">` +
					__("Відкрити календар") + "</a>",
			});
		});
}
