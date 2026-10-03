// Фільтри звіту: рік, календар і тривалість робочого дня.
frappe.query_reports["UA-Норма робочого часу"] = {
	filters: [
		{
			fieldname: "year",
			label: __("Рік"),
			fieldtype: "Int",
			default: new Date().getFullYear(),
			reqd: 1,
			// Календар року підставляється сам — той, що будує кнопка «Побудувати календар».
			on_change(report) {
				const year = report.get_filter_value("year");
				report.set_filter_value("holiday_list", year ? __("Робочий календар {0}", [year]) : "");
			},
		},
		{
			fieldname: "holiday_list",
			label: __("Календар"),
			fieldtype: "Link",
			options: "Holiday List",
			default: __("Робочий календар {0}", [new Date().getFullYear()]),
		},
		{
			fieldname: "hours_per_day",
			label: __("Годин на день"),
			fieldtype: "Float",
			default: 8,
		},
	],
};
