"""Демонстраційні дані: параметри, свята, календар, курс.

Щоб подивитися застосунок у роботі, не чекаючи першого справжнього пакета:

    env/bin/python apps/ua_compliance/demo/seed_demo.py <site>
    env/bin/python apps/ua_compliance/demo/seed_demo.py <site> --clean

**Значення тут — демонстраційні.** Вони зібрані з відкритих джерел станом на
02.10.2026 і перед робочим застосуванням їх має підтвердити методолог: саме в цьому
сенс шару — автоматика приносить дані, а відповідає за них людина.
"""
# ruff: noqa: E402 — скрипт спершу підключається до сайту, а вже потім імпортує
# модулі застосунку: інакше їх нема де взяти.
import sys

import frappe

SITE = sys.argv[1]
CLEAN = "--clean" in sys.argv
MARK = "ДЕМО"

frappe.init(site=SITE, sites_path=".")
frappe.connect()
frappe.set_user("Administrator")

PARAMETERS = [
	# код, назва, вид, значення, одиниця, з, по, норма, номер, дата, пункт, посилання
	("MIN_WAGE", "Мінімальна заробітна плата", "Сума", 8000, "грн", "2025-01-01", "2025-12-31",
	 "Закон", "4059-IX", "2024-11-19", "ст. 8", "https://zakon.rada.gov.ua/laws/show/4059-20"),
	("MIN_WAGE", "Мінімальна заробітна плата", "Сума", 8647, "грн", "2026-01-01", None,
	 "Закон", "4695-IX", "2025-12-03", "ст. 8", "https://zakon.rada.gov.ua/laws/show/4695-20"),
	("SUBSISTENCE_WORKING", "Прожитковий мінімум для працездатних осіб", "Сума", 3028, "грн",
	 "2025-01-01", "2025-12-31", "Закон", "4059-IX", "2024-11-19", "ст. 7",
	 "https://zakon.rada.gov.ua/laws/show/4059-20"),
	("SUBSISTENCE_WORKING", "Прожитковий мінімум для працездатних осіб", "Сума", 3328, "грн",
	 "2026-01-01", None, "Закон", "4695-IX", "2025-12-03", "ст. 7",
	 "https://zakon.rada.gov.ua/laws/show/4695-20"),
	("PIT_RATE", "Ставка податку на доходи фізичних осіб", "Відсоток", 18, "%", "2016-01-01", None,
	 "Закон", "2755-VI", "2010-12-02", "п. 167.1", "https://zakon.rada.gov.ua/laws/show/2755-17"),
	("MILITARY_LEVY_RATE", "Ставка військового збору", "Відсоток", 1.5, "%", "2014-08-03", "2024-11-30",
	 "Закон", "2755-VI", "2010-12-02", "п. 16-1 підрозд. 10",
	 "https://zakon.rada.gov.ua/laws/show/2755-17"),
	("MILITARY_LEVY_RATE", "Ставка військового збору", "Відсоток", 5, "%", "2024-12-01", None,
	 "Закон", "4015-IX", "2024-10-10", "п. 16-1 підрозд. 10",
	 "https://zakon.rada.gov.ua/laws/show/4015-20"),
	("ESV_RATE", "Ставка єдиного внеску", "Відсоток", 22, "%", "2016-01-01", None,
	 "Закон", "2464-VI", "2010-07-08", "ч. 5 ст. 8", "https://zakon.rada.gov.ua/laws/show/2464-17"),
	("MARTIAL_LAW", "Воєнний стан", "Ознака", 1, None, "2022-03-15", None,
	 "Закон", "2136-IX", "2022-03-15", "ст. 6", "https://zakon.rada.gov.ua/laws/show/2136-20"),
]

HOLIDAYS = [
	("Новий рік", 1, 1, "Закон", "322-08", "1971-12-10"),
	("Міжнародний жіночий день", 8, 3, "Закон", "322-08", "1971-12-10"),
	("День праці", 1, 5, "Закон", "322-08", "1971-12-10"),
	("День памʼяті та перемоги над нацизмом у Другій світовій війні", 8, 5, "Закон", "3107-IX", "2023-05-29"),
	("День Конституції України", 28, 6, "Закон", "322-08", "1971-12-10"),
	("День Української Державності", 15, 7, "Закон", "3258-IX", "2023-07-14"),
	("День Незалежності України", 24, 8, "Закон", "322-08", "1971-12-10"),
	("День захисників і захисниць України", 1, 10, "Закон", "3258-IX", "2023-07-14"),
	("Різдво Христове", 25, 12, "Закон", "3258-IX", "2023-07-14"),
]

if CLEAN:
	frappe.db.delete("UA Legal Parameter", {"code": ["in", [p[0] for p in PARAMETERS]]})
	frappe.db.delete("UA Holiday Rule", {"holiday_name": ["in", [h[0] for h in HOLIDAYS]]})
	for title in ("Робочий календар 2026", "Робочий календар 2027"):
		if frappe.db.exists("Holiday List", title):
			frappe.delete_doc("Holiday List", title, force=True, ignore_permissions=True)
	frappe.db.delete("UA Update Package", {"version": ["like", "2026%"]})
	frappe.db.commit()
	print("демонстрационные данные удалены")
	frappe.destroy()
	sys.exit()

created = 0
for code, name, value_type, value, unit, since, until, basis, number, basis_date, clause, url in PARAMETERS:
	if frappe.db.exists("UA Legal Parameter", {"code": code, "valid_from": since}):
		continue
	doc = frappe.new_doc("UA Legal Parameter")
	doc.update(
		{
			"code": code,
			"parameter_name": name,
			"value_type": value_type,
			"unit": unit,
			"valid_from": since,
			"valid_to": until,
			"basis_type": basis,
			"basis_number": number,
			"basis_date": basis_date,
			"basis_clause": clause,
			"basis_url": url,
			"source": "Введено вручну",
			"verified_on": "2026-10-02",
		}
	)
	field = {"Сума": "value_number", "Число": "value_number", "Відсоток": "value_number",
	         "Дата": "value_date", "Рядок": "value_text", "Ознака": "value_flag"}[value_type]
	doc.set(field, value)
	doc.insert(ignore_permissions=True)
	created += 1

rules = 0
for name, day, month, basis, number, basis_date in HOLIDAYS:
	if frappe.db.exists("UA Holiday Rule", {"holiday_name": name}):
		continue
	frappe.get_doc(
		{
			"doctype": "UA Holiday Rule",
			"holiday_name": name,
			"rule_type": "Фіксована дата",
			"day": day,
			"month": month,
			"is_day_off": 1,
			"valid_from": "2023-07-28" if number == "3258-IX" else "2000-01-01",
			"basis_type": basis,
			"basis_number": number,
			"basis_date": basis_date,
			"basis_url": f"https://zakon.rada.gov.ua/laws/show/{number.lower().replace('-ix', '-20').replace('-08', '-08')}",
			"source": "Введено вручну",
		}
	).insert(ignore_permissions=True)
	rules += 1

for rule_type, name in (("Великдень", "Великдень (Пасха)"), ("Трійця", "Трійця")):
	if not frappe.db.exists("UA Holiday Rule", {"holiday_name": name}):
		frappe.get_doc(
			{
				"doctype": "UA Holiday Rule",
				"holiday_name": name,
				"rule_type": rule_type,
				"is_day_off": 1,
				"valid_from": "2000-01-01",
				"basis_type": "Закон",
				"basis_number": "322-08",
				"basis_date": "1971-12-10",
				"basis_url": "https://zakon.rada.gov.ua/laws/show/322-08",
				"source": "Введено вручну",
			}
		).insert(ignore_permissions=True)
		rules += 1

frappe.db.commit()

from ua_compliance.calendar.build import build_holiday_list
from ua_compliance.rates.job import load_rates

calendar_2026 = build_holiday_list(2026)
rates = load_rates(days=14)
frappe.db.commit()

print(f"параметров создано: {created}, правил праздников: {rules}")
print("календарь 2026:", calendar_2026)
print("курсы: проверено дат", rates["checked"], "создано", rates["created"], "обновлено", rates["updated"])
print("всего в системе: параметров", frappe.db.count("UA Legal Parameter"),
      "| записей курса", frappe.db.count("Currency Exchange"),
      "| записей журнала", frappe.db.count("UA Operation Log"))
frappe.destroy()
