// Фільтри звіту: рік, календар і тривалість робочого дня.
frappe.query_reports["UA-Норма робочого часу"] = {
	filters: [
		{
			fieldname: "year",
			label: __("Рік"),
			fieldtype: "Int",
			default: new Date().getFullYear(),
			reqd: 1,
		},
		{
			fieldname: "holiday_list",
			label: __("Календар"),
			fieldtype: "Link",
			options: "Holiday List",
		},
		{
			fieldname: "hours_per_day",
			label: __("Годин на день"),
			fieldtype: "Float",
			default: 8,
		},
	],
};
