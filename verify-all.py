"""Перевірка застосунку ua_compliance на живому сайті.

Запускати з каталогу `sites`:
    env/bin/python apps/ua_compliance/verify-all.py <site>

Правила, вистраждані на попередніх фічах:
- перевірки **діяльні**: створюють документ і читають **збережений** стан, а не
  значення, яке повернула функція;
- пісочниця: синтетичні записи робляться на давній даті й на валюті, якої немає
  в роботі, а в кінці все зайве прибирається за списком, знятим ДО прогону
  (відкоту транзакції мало: будь-який commit усередині зафіксує і створене);
- жодна перевірка не покладається на те, що хтось прибрав за собою раніше.
"""

import sys
import warnings
from datetime import date

import frappe

warnings.filterwarnings("ignore")

SITE = sys.argv[1] if len(sys.argv) > 1 else frappe.read_default_site()
SANDBOX_CURRENCY = "JPY"  # валюта, якої немає в роботі стенда
SANDBOX_DATE = date(2001, 1, 1)

frappe.init(site=SITE, sites_path=".")
frappe.connect()
frappe.set_user("Administrator")

RESULTS = []


def chk(name, ok, note=""):
	RESULTS.append(("✔" if ok else "✗", name, note))


# Знімок того, що існувало ДО прогону.
BEFORE = {
	dt: set(frappe.get_all(dt, pluck="name"))
	for dt in ("Currency Exchange", "UA Operation Log", "UA Legal Parameter")
	if frappe.db.exists("DocType", dt)
}

# 1. Застосунок і структура
apps = frappe.get_installed_apps()
chk("застосунок ua_compliance встановлено", "ua_compliance" in apps, str(apps))

from ua_compliance import api  # noqa: E402
from ua_compliance.rates import job, parse, source, writer  # noqa: E402

doctypes = frappe.get_all("DocType", filters={"module": "UA Compliance"}, fields=["name", "custom"])
chk(
	"доктайпи стандартні, модуль UA Compliance",
	len(doctypes) >= 3 and all(d.custom == 0 for d in doctypes),
	f"{len(doctypes)}: " + ", ".join(sorted(d.name for d in doctypes)),
)

fields = set(frappe.get_all("Custom Field", filters={"dt": "Currency Exchange"}, pluck="fieldname"))
chk(
	"свої поля запису курсу на місці",
	{"ua_source_rate", "ua_multiplicity", "ua_source"} <= fields,
	str(sorted(fields)),
)

chk(
	"зовнішнього постачальника курсів вимкнено (FR-004)",
	bool(frappe.db.get_single_value("Currency Exchange Settings", "disabled")),
)

# 2. Звернення до джерела: формат дати
url = source.build_url(date(2026, 9, 18))
chk(
	"дата в запиті у форматі YYYYMMDD (FR-007)",
	"date=20260918" in url and "2026-09-18" not in url,
	url,
)

# 3. Розбір відповіді: джерело відповідає кодом 200 навіть на помилку
ok_body = '[{"r030":840,"txt":"Долар США","rate":44.6648,"cc":"USD","exchangedate":"18.09.2026"}]'
rates = parse.parse(ok_body, date(2026, 9, 18))
chk(
	"коректна відповідь розбирається, шість знаків збережено",
	rates["USD"]["rate"] == 44.6648 and rates["USD"]["multiplicity"] == 1,
	str(rates["USD"]),
)

for name, body in (
	("тіло «Wrong date format» не вважається даними", "[\n{ \nWrong date format\n }\n]"),
	("порожня відповідь не вважається даними", "[]"),
	("відповідь без курсу не вважається даними", '[{"cc":"USD"}]'),
):
	try:
		parse.parse(body, date(2026, 9, 18))
		chk(name, False, "розбір не дав помилки")
	except parse.SourceAnswerError as error:
		chk(name, "без курсу на 18.09.2026" in str(error), str(error))

# 4. Запис курсу: нормалізація на кратність і ідемпотентність
frappe.db.delete("Currency Exchange", {"date": SANDBOX_DATE, "from_currency": SANDBOX_CURRENCY})

action, _previous = writer.upsert_rate(SANDBOX_DATE, SANDBOX_CURRENCY, 50.0, multiplicity=100)
saved = frappe.db.get_value(
	"Currency Exchange",
	{"date": SANDBOX_DATE, "from_currency": SANDBOX_CURRENCY, "to_currency": "UAH"},
	["exchange_rate", "ua_source_rate", "ua_multiplicity", "ua_source"],
	as_dict=True,
)
chk(
	"курс зведено до однієї одиниці: 50 за 100 → 0,5 (FR-006)",
	action == "created" and saved and round(saved.exchange_rate, 6) == 0.5,
	str(saved),
)
chk(
	"кратність і курс джерела збережено як в as-is регістрі",
	bool(saved) and saved.ua_multiplicity == 100 and saved.ua_source_rate == 50.0 and saved.ua_source == "НБУ",
	str(saved),
)

action, _previous = writer.upsert_rate(SANDBOX_DATE, SANDBOX_CURRENCY, 50.0, multiplicity=100)
count = frappe.db.count("Currency Exchange", {"date": SANDBOX_DATE, "from_currency": SANDBOX_CURRENCY})
chk("повторний запис не створює дубля (FR-008)", action == "unchanged" and count == 1, f"{action}, записів {count}")

action, previous = writer.upsert_rate(SANDBOX_DATE, SANDBOX_CURRENCY, 60.0, multiplicity=100)
saved_rate = frappe.db.get_value(
	"Currency Exchange",
	{"date": SANDBOX_DATE, "from_currency": SANDBOX_CURRENCY, "to_currency": "UAH"},
	"exchange_rate",
)
chk(
	"інше значення джерела оновлює запис і віддає попереднє (FR-009)",
	action == "updated" and round(saved_rate, 6) == 0.6 and round(previous, 6) == 0.5,
	f"{action}: {previous} → {saved_rate}",
)

# 5. Серверний метод
chk("get_rate віддає збережений курс", round(api.get_rate(SANDBOX_CURRENCY, SANDBOX_DATE), 6) == 0.6)

try:
	api.get_rate(SANDBOX_CURRENCY, date(1999, 1, 1))
	chk("на дату без курсу — помилка, а не нуль (FR-005)", False, "помилки не було")
except frappe.ValidationError as error:
	chk(
		"на дату без курсу — помилка, а не нуль (FR-005)",
		"Офіційний курс НБУ на 01.01.1999 не завантажено" in str(error),
		str(error)[:120],
	)

# 6. Завантаження: ідемпотентність і журнал
summary = job.load_rates(days=2, write_log=True)
chk(
	"повторне завантаження не створює записів (FR-008)",
	summary["created"] == 0 and not summary["errors"],
	f"створено {summary['created']}, оновлено {summary['updated']}, помилки {summary['errors']}",
)

log = frappe.get_all(
	"UA Operation Log",
	filters={"kind": "Завантаження курсу"},
	fields=["name", "result", "checked_count", "message"],
	order_by="creation desc",
	limit=1,
)
chk(
	"кожен запуск лишає запис журналу (принцип IV)",
	bool(log) and log[0].checked_count >= 2 and log[0].result in ("Успішно", "Помилка"),
	str(log[0]) if log else "журнал порожній",
)

# 7. Незалежна звірка з першоджерелом
checked = mismatch = 0
for row in frappe.get_all(
	"Currency Exchange",
	filters={"to_currency": "UAH", "ua_source": "НБУ"},
	fields=["date", "from_currency", "exchange_rate"],
	order_by="date desc",
	limit=6,
):
	try:
		live = parse.parse(source.fetch(row.date), row.date)
	except Exception:
		continue
	expected = live.get(row.from_currency)
	if not expected:
		continue
	checked += 1
	if round(float(expected["rate"]), 6) != round(float(row.exchange_rate), 6):
		mismatch += 1
chk(
	"курс у базі збігається з офіційним на ту саму дату (SC-001)",
	checked >= 3 and mismatch == 0,
	f"звірено {checked} значень, розбіжностей {mismatch}",
)

# 8. Законодавчий параметр (US2)
PARAM = "TEST_MIN_WAGE"
frappe.db.delete("UA Legal Parameter", {"code": PARAM})


def make_param(valid_from, value, valid_to=None, source="Введено вручну", code=PARAM):
	return frappe.get_doc(
		{
			"doctype": "UA Legal Parameter",
			"code": code,
			"parameter_name": "Мінімальна заробітна плата (перевірка)",
			"value_type": "Сума",
			"value_number": value,
			"unit": "грн",
			"valid_from": valid_from,
			"valid_to": valid_to,
			"basis_type": "Закон",
			"basis_number": "4695-IX",
			"basis_date": "2025-12-03",
			"basis_url": "https://zakon.rada.gov.ua/laws/show/4695-20",
			"source": source,
			"verified_on": "2026-10-02",
		}
	).insert(ignore_permissions=True)


first = make_param("2025-01-01", 8000, valid_to="2025-12-31")
second = make_param("2026-01-01", 8647)
chk(
	"параметр зберігається з періодом і підставою",
	frappe.db.get_value("UA Legal Parameter", first.name, "value_number") == 8000,
	first.name,
)
chk("значення на дату всередині першого періоду", api.get_parameter(PARAM, date(2025, 6, 15)) == 8000)
chk("значення на дату всередині другого періоду", api.get_parameter(PARAM, date(2026, 6, 15)) == 8647)

try:
	api.get_parameter(PARAM, date(2024, 6, 15))
	chk("на дату без значення — помилка, а не нуль (FR-016)", False, "помилки не було")
except frappe.ValidationError as error:
	chk(
		"на дату без значення — помилка, а не нуль (FR-016)",
		"не визначено" in str(error),
		str(error)[:90],
	)

try:
	make_param("2026-06-01", 9000)
	chk("перетин періодів відхиляється (FR-017)", False, "запис створився")
except frappe.ValidationError as error:
	chk("перетин періодів відхиляється (FR-017)", "перетинається" in str(error), str(error)[:90])

try:
	frappe.delete_doc("UA Legal Parameter", first.name, ignore_permissions=True)
	chk("видалення заборонено (FR-018)", False, "запис видалився")
except frappe.ValidationError as error:
	chk("видалення заборонено (FR-018)", "не видаляється" in str(error), str(error)[:90])

try:
	make_param("2027-01-01", 9546, code="test_bad_code")
	chk("код лише латиницею великими літерами (принцип III)", False, "запис створився")
except frappe.ValidationError as error:
	chk("код лише латиницею великими літерами (принцип III)", "латиницею" in str(error), str(error)[:70])

from_package = make_param("2024-01-01", 7100, valid_to="2024-12-31", source="З пакета", code="TEST_FROM_PACKAGE")
from_package.value_number = 7777
try:
	from_package.save(ignore_permissions=True)
	chk("запис із пакета не правиться руками", False, "правка пройшла")
except frappe.ValidationError as error:
	chk("запис із пакета не правиться руками", "не редагується" in str(error), str(error)[:90])

# SC-011: поява нового значення не змінює розрахунок за минулий період.
# Так це відбувається в житті: пакет закриває чинний період датою і додає наступний.
before_change = api.get_parameter(PARAM, date(2025, 6, 15))
second.valid_to = "2026-12-31"
second.save(ignore_permissions=True)
make_param("2027-01-01", 9546, code=PARAM)
chk("нове значення діє з наступного періоду", api.get_parameter(PARAM, date(2027, 6, 15)) == 9546)
chk(
	"розрахунок за минулий період відтворюється після зміни значення (SC-011)",
	api.get_parameter(PARAM, date(2025, 6, 15)) == before_change == 8000,
)

# SC-005: значення не продубльоване формулою чи налаштуванням
duplicates = []
values = {
	frappe.utils.flt(v)
	for v in frappe.get_all("UA Legal Parameter", filters={"value_type": ["in", ["Сума", "Число", "Відсоток"]]}, pluck="value_number")
	if v
}
sources = []
if frappe.db.exists("DocType", "Salary Component"):
	sources += [(f"Salary Component {r.name}", r.formula) for r in frappe.get_all("Salary Component", fields=["name", "formula"]) if r.formula]
sources += [(f"Custom Field {r.name}", r.default) for r in frappe.get_all("Custom Field", fields=["name", "default"]) if r.default]
for where, text in sources:
	for value in values:
		if str(value).rstrip("0").rstrip(".") and str(value).rstrip("0").rstrip(".") in str(text):
			duplicates.append(f"{where}: {text}")
chk(
	"значення параметра не продубльоване формулою чи налаштуванням (SC-005)",
	not duplicates,
	"; ".join(duplicates[:3]) if duplicates else f"перевірено значень {len(values)} у {len(sources)} місцях",
)

# 9. Прибирання за собою
frappe.db.rollback()
removed = 0
for doctype, existing in BEFORE.items():
	for name in set(frappe.get_all(doctype, pluck="name")) - existing:
		# Параметр має заборону на видалення — прибираємо напряму, інакше пісочниця
		# лишається на стенді й наступний прогін падає на перетині періодів.
		frappe.db.delete(doctype, {"name": name})
		removed += 1
frappe.db.commit()
leftovers = sum(len(set(frappe.get_all(dt, pluck="name")) - existing) for dt, existing in BEFORE.items())
chk("перевірка прибрала за собою", leftovers == 0, f"видалено {removed}, лишилося зайвих {leftovers}")

# Підсумок
print()
for mark, name, note in RESULTS:
	print(f"  {mark} {name}" + (f"  — {note}" if note else ""))
passed = sum(1 for mark, _, _ in RESULTS if mark == "✔")
print(f"\nИТОГО: {passed} из {len(RESULTS)} проверок пройдено")
frappe.destroy()
sys.exit(0 if passed == len(RESULTS) else 1)
