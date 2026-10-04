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

# ruff: noqa: E402 — харнес підключається до сайту, а вже потім імпортує модулі
# застосунку: інакше їх нема де взяти. Для цього файла правило вимкнене цілком.
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
	for dt in (
		"Currency Exchange",
		"UA Operation Log",
		"UA Legal Parameter",
		"UA Update Package",
		"UA Holiday Rule",
		"Holiday List",
		"UA Classifier Entry",
	)
	if frappe.db.exists("DocType", dt)
}

# 1. Застосунок і структура
apps = frappe.get_installed_apps()
chk("застосунок ua_compliance встановлено", "ua_compliance" in apps, str(apps))

from ua_compliance import api
from ua_compliance.rates import job, parse, source, writer

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
# Ідемпотентність перевіряється двома прогонами підряд, а не припущенням, що курс
# уже вантажили раніше: на чистому екземплярі перший прогін законно створює записи
# (спіймано на екземплярі кадрів 02.10.2026).
first_run = job.load_rates(days=2, write_log=True)
summary = job.load_rates(days=2, write_log=True)
chk(
	"повторне завантаження не створює записів (FR-008)",
	summary["created"] == 0 and not summary["errors"],
	f"перший прогін створив {first_run['created']}, повторний {summary['created']}, помилки {summary['errors']}",
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

# 9. Пакет оновлень (US3)
import sys as _sys

_sys.path.insert(0, frappe.get_app_path("ua_compliance", ".."))
from tests.fixtures.build_package import PARAMETERS_CSV, build_package, generate_key
from ua_compliance.packages import keys as keys_module
from ua_compliance.ua_compliance.doctype.ua_update_package.ua_update_package import receive

# Версії тестових пакетів — в окремому діапазоні, вищому за будь-яку справжню (РРРРММДД):
# інакше застосований на стенді справжній пакет робить тестові «не новішими» (спіймано
# 03.10.2026, коли застосували parameters-20261003). Взаємний порядок зберігається, а
# прибирання наприкінці видаляє тестові пакети, тож справжня лінія версій не засмічується.
TEST_VERSION_BASE = 900_000_000


def V(n):
	return TEST_VERSION_BASE + (n - 20261000)


key_a, private_a, id_a = generate_key()
key_b, private_b, id_b = generate_key()
key_c, private_c, id_c = generate_key()
SIGNERS = [(private_a, id_a), (private_b, id_b)]
_production_keys = list(keys_module.TRUSTED_KEYS)
keys_module.TRUSTED_KEYS[:] = [key_a, key_b, key_c]  # лише для перевірки: бойові ключі приїжджають релізом


def take(raw, version=V(20261002)):
	package = receive(raw, "parameters", version)
	ok = package.run_verification(raw)
	return package, ok


try:
	# 9.1 Повний шлях: прийняття → перевірка → передпоказ → затвердження → застосування
	good = build_package(PARAMETERS_CSV, keys=SIGNERS, version=V(20261002))
	package, ok = take(good)
	chk(
		"пакет із двома підписами проходить перевірку",
		ok and package.state == "До застосування" and package.signatures_ok == 2,
		f"{package.state}, підписів {package.signatures_ok}",
	)
	chk(
		"передпоказ показує, що саме зміниться (FR-031)",
		len(package.preview) >= 1 and package.preview[0].action == "Додається",
		"; ".join(f"{r.action} {r.code} з {r.valid_from}" for r in package.preview),
	)
	chk(
		"до затвердження нічого не застосовано (FR-030)",
		not frappe.db.exists("UA Legal Parameter", {"code": "TEST_PKG_MIN_WAGE"}),
	)

	summary = package.approve_and_apply(good)
	applied = frappe.db.get_value(
		"UA Legal Parameter",
		{"code": "TEST_PKG_MIN_WAGE"},
		["value_number", "source", "source_reference", "basis_number"],
		as_dict=True,
	)
	chk(
		"після затвердження параметр з'явився з посиланням на пакет",
		package.state == "Застосовано" and applied and applied.value_number == 9546 and applied.source == "З пакета",
		str(applied),
	)
	chk(
		"застосування лишило запис у журналі (FR-039)",
		bool(frappe.get_all("UA Operation Log", filters={"kind": "Застосування пакета", "package": package.name})),
	)

	package.state = "Відхилено"
	try:
		package.save(ignore_permissions=True)
		chk("застосований пакет не скасовується (FR-035)", False, "стан змінився")
	except frappe.ValidationError as error:
		chk("застосований пакет не скасовується (FR-035)", "не скасовується" in str(error), str(error)[:80])
	package.reload()

	# 9.2 Чотири зіпсованих пакети
	one_signature = build_package(PARAMETERS_CSV, keys=[SIGNERS[0]], version=V(20261003))
	package_one, ok_one = take(one_signature, version=V(20261003))
	chk(
		"один підпис замість двох — відмова (FR-024)",
		not ok_one and "підписів 1, потрібно 2" in (package_one.reject_reason or ""),
		package_one.reject_reason,
	)

	old_version = build_package(PARAMETERS_CSV, keys=SIGNERS, version=V(20261001))
	package_old, ok_old = take(old_version, version=V(20261001))
	chk(
		"версія не новіша за застосовану — відмова (FR-025)",
		not ok_old and "не новіша" in (package_old.reject_reason or ""),
		package_old.reject_reason,
	)

	expired = build_package(PARAMETERS_CSV, keys=SIGNERS, version=V(20261004), expires="2020-01-01")
	package_expired, ok_expired = take(expired, version=V(20261004))
	chk(
		"строк придатності минув — відмова (FR-026)",
		not ok_expired and "строк придатності" in (package_expired.reject_reason or ""),
		package_expired.reject_reason,
	)
	# T063 Блокування за строком знімає лише адміністратор, і це в журналі (FR-037)
	frappe.set_user("Guest")
	try:
		package_expired.unlock_expired(expired)
		chk("зняти блокування за строком може лише адміністратор", False, "зняв гість")
	except frappe.ValidationError as error:
		chk("зняти блокування за строком може лише адміністратор", "адміністратор" in str(error), str(error)[:80])
	finally:
		frappe.set_user("Administrator")
	package_expired.reload()
	unlocked = package_expired.unlock_expired(expired)
	stored_unlock = frappe.db.get_value(
		"UA Update Package", package_expired.name, ["state", "expiry_override", "expiry_override_by"], as_dict=True
	)
	chk(
		"адміністратор зняв блокування — пакет перевірено знову й готовий до затвердження (FR-037)",
		unlocked and stored_unlock.state == "До застосування" and stored_unlock.expiry_override == 1
		and stored_unlock.expiry_override_by == "Administrator"
		and frappe.db.exists("UA Operation Log", {"kind": "Рішення щодо пакета", "package": package_expired.name, "message": ["like", "Знято блокування%"]}),
		str(stored_unlock),
	)
	package_expired.reload()
	package_expired.approve_and_apply(expired)
	chk(
		"прострочений маніфест застосовано після зняття блокування — повторна перевірка теж його пропускає",
		frappe.db.get_value("UA Update Package", package_expired.name, "state") == "Застосовано",
	)
	# T065 Строк придатності останнього застосованого маніфесту минув — попередження й у розділі
	chk(
		"попередження «строк останнього пакета минув» видно через розділ і картку (FR-038)",
		any("Строк придатності останнього пакета минув 01.01.2020" in w for w in api.get_update_warnings()),
		"; ".join(api.get_update_warnings())[:150],
	)

	bad_hash = build_package(PARAMETERS_CSV, keys=SIGNERS, version=V(20261005), corrupt_hash=True)
	package_hash, ok_hash = take(bad_hash, version=V(20261005))
	chk(
		"хеш файла не збігається — відмова (FR-027)",
		not ok_hash and "не відповідає хешу" in (package_hash.reject_reason or ""),
		package_hash.reject_reason,
	)
	stored_hash = frappe.db.get_value("UA Update Package", package_hash.name, ["signatures_ok", "key_ids"], as_dict=True)
	chk(
		"відхилений за хешем пакет показує справжні підписи з номерами ключів",
		stored_hash.signatures_ok == 2 and (stored_hash.key_ids or "").count("ключ ") == 2,
		str(stored_hash),
	)

	# 9.3 Виконуваний вміст і стара версія застосунку
	executable = build_package(
		PARAMETERS_CSV, keys=SIGNERS, version=V(20261006), extra_file=("evil.py", b"import os")
	)
	package_exec, ok_exec = take(executable, version=V(20261006))
	chk(
		"файл, що не є даними, робить пакет неприйнятним (FR-034)",
		not ok_exec and "не є файлом даних" in (package_exec.reject_reason or ""),
		package_exec.reject_reason,
	)

	too_new = build_package(PARAMETERS_CSV, keys=SIGNERS, version=V(20261007), min_app_version="99.0.0")
	package_new, ok_new = take(too_new, version=V(20261007))
	chk(
		"пакет для новішої версії застосунку — відмова (FR-052)",
		not ok_new and "версія застосунку не нижче" in (package_new.reject_reason or ""),
		package_new.reject_reason,
	)

	# 9.4 Розходження з ручним записом
	make_param("2027-01-01", 9000, code="TEST_PKG_MIN_WAGE_MANUAL")
	manual_csv = PARAMETERS_CSV.replace("TEST_PKG_MIN_WAGE", "TEST_PKG_MIN_WAGE_MANUAL")
	conflicting = build_package(manual_csv, keys=SIGNERS, version=V(20261008))
	package_conflict, ok_conflict = take(conflicting, version=V(20261008))
	conflict_rows = [row for row in package_conflict.preview if row.conflict]
	chk(
		"прежнє значення в передпоказі — як у законі, без «.0»",
		[r.old_value for r in conflict_rows] == ["9000"],
		str([r.old_value for r in conflict_rows]),
	)
	chk(
		"розходження з ручним записом виділено в передпоказі (FR-032)",
		ok_conflict and bool(conflict_rows),
		"; ".join(f"{r.code} {r.old_value}→{r.new_value}" for r in conflict_rows),
	)
	try:
		package_conflict.approve_and_apply(conflicting)
		chk("пакет із розходженням не застосовується без рішення (FR-032)", False, "застосувався")
	except frappe.ValidationError as error:
		chk(
			"пакет із розходженням не застосовується без рішення (FR-032)",
			"розходження" in str(error),
			str(error)[:90],
		)
	# T062 Розходження чекає рішення людини: «Перевірено» → рішення → «До застосування»
	chk(
		"пакет із нерозв'язаним розходженням стоїть у «Перевірено» (FR-029)",
		frappe.db.get_value("UA Update Package", package_conflict.name, "state") == "Перевірено",
	)
	package_conflict.reload()
	state_after = package_conflict.decide({row.name: "Залишити ручне" for row in package_conflict.preview if row.conflict})
	package_conflict.reload()
	package_conflict.approve_and_apply(conflicting)
	kept = frappe.db.get_value(
		"UA Legal Parameter", {"code": "TEST_PKG_MIN_WAGE_MANUAL", "valid_from": "2027-01-01"}, ["value_number", "source"], as_dict=True
	)
	chk(
		"рішення «Залишити ручне»: пакет застосовано, ручний запис не зачеплено (US3/AC8)",
		state_after == "До застосування" and kept.value_number == 9000 and kept.source == "Введено вручну"
		and frappe.db.get_value("UA Update Package", package_conflict.name, "state") == "Застосовано"
		and frappe.db.exists("UA Operation Log", {"kind": "Рішення щодо пакета", "package": package_conflict.name}),
		str(kept),
	)
	# 9.4а Той самий зміст, що введений вручну: не розходження (найчастіший випадок —
	# пакет запізнився й привіз те, що вже ввели). У базі 9546.0, у пакеті 9546.
	make_param("2027-01-01", 9546, code="TEST_PKG_SAME_VALUE")
	same_value = build_package(
		PARAMETERS_CSV.replace("TEST_PKG_MIN_WAGE", "TEST_PKG_SAME_VALUE"), keys=SIGNERS, version=V(20261015)
	)
	package_same, ok_same = take(same_value, version=V(20261015))
	same_rows = [(r.action, r.conflict) for r in package_same.preview if r.code == "TEST_PKG_SAME_VALUE"]
	chk(
		"те саме значення, що введене вручну, не є розходженням (FR-032)",
		ok_same and same_rows == [("Змінюється", 0)],
		str(same_rows),
	)

	# 9.4б Стан і передпоказ пише лише сервер у діях пакета (спіймано на демо 03.10.2026)
	package_same.reload()
	package_same.state = "Застосовано"
	try:
		package_same.save(ignore_permissions=True)
		chk("стан пакета не виставляється руками", False, "збереглося")
	except frappe.ValidationError as error:
		chk("стан пакета не виставляється руками", "лише діями" in str(error), str(error)[:80])
	package_same.reload()
	package_same.preview[0].conflict = 1 - package_same.preview[0].conflict
	try:
		package_same.save(ignore_permissions=True)
		chk("передпоказ пакета не правиться руками", False, "збереглося")
	except frappe.ValidationError as error:
		chk("передпоказ пакета не правиться руками", "лише діями" in str(error), str(error)[:80])
	forged = frappe.get_doc(
		{"doctype": "UA Update Package", "channel": "Параметри", "version": "підробка", "state": "Застосовано"}
	).insert(ignore_permissions=True)
	chk(
		"новий пакет народжується лише отриманим",
		frappe.db.get_value("UA Update Package", forged.name, "state") == "Отримано",
		frappe.db.get_value("UA Update Package", forged.name, "state"),
	)

	# 9.5 Той самий пакет файлом (ізольований контур) і кнопки форми
	offline = build_package(
		PARAMETERS_CSV.replace("TEST_PKG_MIN_WAGE", "TEST_PKG_OFFLINE"), keys=SIGNERS, version=V(20261009)
	)
	package_offline = receive(offline, "parameters", V(20261009))
	attachment = frappe.get_doc(
		{
			"doctype": "File",
			"file_name": "ua-params-offline.zip",
			"attached_to_doctype": "UA Update Package",
			"attached_to_name": package_offline.name,
			"content": offline,
			"is_private": 1,
			"decode": False,
		}
	).insert(ignore_permissions=True)
	result_offline = api.verify_package(package_offline.name)
	chk(
		"пакет, прикріплений файлом, перевіряється тим самим шляхом (FR-036)",
		result_offline["ok"] and result_offline["state"] == "До застосування",
		f"{result_offline}, файл {attachment.file_name}",
	)

	approved_offline = api.approve_package(package_offline.name)
	chk(
		"кнопка «Затвердити» лише затверджує — «Затверджено», застосування у фоні (FR-029)",
		approved_offline["state"] == "Затверджено"
		and frappe.db.get_value("UA Update Package", package_offline.name, "state") == "Затверджено",
		str(approved_offline),
	)
	applied_offline = api.apply_package_job(package_offline.name)
	chk(
		"фонове завдання застосовує затверджений пакет (FR-030)",
		frappe.db.get_value("UA Update Package", package_offline.name, "state") == "Застосовано"
		and (applied_offline or {}).get("created", 0) >= 1,
		str(applied_offline),
	)

	# 9.5а Рішення «Прийняти з пакета» перезаписує ручний запис — свідомо, з журналом
	make_param("2027-01-01", 9000, code="TEST_PKG_ACCEPT")
	accepting = build_package(
		PARAMETERS_CSV.replace("TEST_PKG_MIN_WAGE", "TEST_PKG_ACCEPT"), keys=SIGNERS, version=V(20261012)
	)
	package_accept, _ok = take(accepting, version=V(20261012))
	package_accept.reload()
	package_accept.decide({row.name: "Прийняти з пакета" for row in package_accept.preview if row.conflict})
	package_accept.reload()
	package_accept.approve_and_apply(accepting)
	accepted = frappe.db.get_value(
		"UA Legal Parameter", {"code": "TEST_PKG_ACCEPT", "valid_from": "2027-01-01"}, ["value_number", "source"], as_dict=True
	)
	chk(
		"рішення «Прийняти з пакета»: ручний запис замінено значенням пакета (US3/AC8)",
		accepted.value_number == 9546 and accepted.source == "З пакета",
		str(accepted),
	)

	# 9.5б Невдале фонове застосування не губиться: пакет «Затверджено», причина в журналі
	failing = build_package(
		PARAMETERS_CSV.replace("TEST_PKG_MIN_WAGE", "TEST_PKG_FAIL"), keys=SIGNERS, version=V(20261013)
	)
	package_fail = receive(failing, "parameters", V(20261013))
	fail_file = frappe.get_doc(
		{
			"doctype": "File", "file_name": "fail.zip", "attached_to_doctype": "UA Update Package",
			"attached_to_name": package_fail.name, "content": failing, "is_private": 1, "decode": False,
		}
	).insert(ignore_permissions=True)
	api.verify_package(package_fail.name)
	api.approve_package(package_fail.name)
	frappe.delete_doc("File", fail_file.name, ignore_permissions=True)
	api.apply_package_job(package_fail.name)
	chk(
		"невдале фонове застосування: пакет лишається «Затверджено», причина в журналі (FR-033)",
		frappe.db.get_value("UA Update Package", package_fail.name, "state") == "Затверджено"
		and not frappe.db.exists("UA Legal Parameter", {"code": "TEST_PKG_FAIL"})
		and frappe.db.exists("UA Operation Log", {"kind": "Застосування пакета", "result": "Помилка", "package": package_fail.name}),
	)

	# 9.5в Пакет задає дату закінчення наявному запису (рядок пакета з valid_to).
	# Спіймано на репетиції: порівняння рядка з датою з бази падало TypeError.
	make_param("2025-01-01", 7500, code="TEST_PKG_PERIOD")
	period_csv = (
		PARAMETERS_CSV.replace("TEST_PKG_MIN_WAGE", "TEST_PKG_PERIOD")
		.replace(",9546,грн,2027-01-01,,", ",8000,грн,2025-01-01,2025-12-31,")
	)
	period_pkg = build_package(period_csv, keys=SIGNERS, version=V(20261014))
	package_period, _ok = take(period_pkg, version=V(20261014))
	package_period.reload()
	package_period.decide({row.name: "Прийняти з пакета" for row in package_period.preview if row.conflict})
	package_period.reload()
	try:
		package_period.approve_and_apply(period_pkg)
		period_row = frappe.db.get_value(
			"UA Legal Parameter", {"code": "TEST_PKG_PERIOD", "valid_from": "2025-01-01"}, ["value_number", "valid_to", "source"], as_dict=True
		)
		chk(
			"пакет із датою закінчення змінює наявний запис (рядок пакета з valid_to)",
			period_row.value_number == 8000 and str(period_row.valid_to) == "2025-12-31" and period_row.source == "З пакета",
			str(period_row),
		)
	except Exception as error:
		chk("пакет із датою закінчення змінює наявний запис (рядок пакета з valid_to)", False, f"{type(error).__name__}: {error}"[:120])

	# 9.6 Попередження про прострочений пакет (FR-038)
	stale = build_package(
		PARAMETERS_CSV.replace("TEST_PKG_MIN_WAGE", "TEST_PKG_STALE"), keys=SIGNERS, version=V(20261010)
	)
	package_stale = receive(stale, "parameters", V(20261010))
	package_stale.state = "До застосування"
	package_stale.expires_on = "2020-01-01"
	package_stale.save_by_action()  # підготовка перевірки, а не дія користувача
	from ua_compliance.packages.jobs import warn_about_updates

	warnings = warn_about_updates()
	# Читаємо збережений журнал, а не повернуте значення
	warning_rows = frappe.get_all(
		"UA Operation Log",
		filters={"kind": "Попередження", "result": "Увага", "message": ["like", "%Строк придатності%"]},
		pluck="message",
	)
	chk(
		"попередження про прострочений пакет — у журналі окремим видом (FR-038)",
		bool(warning_rows),
		"; ".join(warnings or [])[:120],
	)
	chk(
		"пакет без строку придатності не названо простроченим",
		not any("підробка" in w for w in (warnings or [])),
		"; ".join(w for w in (warnings or []) if "підробка" in w),
	)

	# 9.7 Забір з каналу роздачі (FR-039): канал підмінено, решта шляху — справжня
	from ua_compliance.packages import feed as feed_module
	from ua_compliance.packages.jobs import poll_packages

	feed_good = build_package(
		PARAMETERS_CSV.replace("TEST_PKG_MIN_WAGE", "TEST_PKG_FEED"), keys=SIGNERS, version=V(20261020)
	)
	feed_bad = build_package(
		PARAMETERS_CSV.replace("TEST_PKG_MIN_WAGE", "TEST_PKG_FEED_BAD"), keys=SIGNERS[:1], version=V(20261021)
	)
	feed_files = {"https://feed.test/20261021/bad.zip": feed_bad, "https://feed.test/20261020/good.zip": feed_good}
	feed_releases = [
		{"tag_name": f"parameters-{v}", "published_at": f"2026-10-{d}T08:00:00Z", "draft": False, "prerelease": False,
		 "assets": [{"name": n, "browser_download_url": f"https://feed.test/{v}/{n}", "size": 1}]}
		for v, d, n in (("20261021", "21", "bad.zip"), ("20261020", "20", "good.zip"))
	]
	_fetch, _download = feed_module.fetch_releases, feed_module.download
	# Налаштування могли жодного разу не зберігатися: тоді рядків у Singles немає й діють
	# умовчання. Один записаний рядок вимикає умовчання решти полів, тому ставимо обидва
	# поля явно, а повертаємо точно той набір рядків, що був.
	SETTINGS = "UA Compliance Settings"
	singles_query = "select field, value from tabSingles where doctype=%s order by field"
	_singles = frappe.db.sql(singles_query, SETTINGS)
	try:
		frappe.db.set_single_value(
			SETTINGS, {"packages_enabled": 1, "packages_feed_url": "https://feed.test/releases"}
		)
		feed_module.fetch_releases = lambda url: feed_releases
		feed_module.download = lambda asset: feed_files[asset["url"]]
		polled = poll_packages()
		stored = {
			row.source_url: row
			for row in frappe.get_all(
				"UA Update Package",
				filters={"source_url": ["like", "https://feed.test/%"]},
				fields=["name", "state", "source_url", "reject_reason", "applied_on"],
			)
		}
		good_row = stored.get("https://feed.test/20261020/good.zip")
		bad_row = stored.get("https://feed.test/20261021/bad.zip")
		chk(
			"забраний пакет перевірено й поставлено на рішення, а не застосовано (FR-039)",
			good_row is not None and good_row.state == "До застосування" and not good_row.applied_on
			and not frappe.db.exists("UA Legal Parameter", {"code": "TEST_PKG_FEED"}),
			f"{good_row}",
		)
		chk(
			"пакет з одним підписом із каналу відхилено з причиною",
			bad_row is not None and bad_row.state == "Відхилено" and "підписів 1" in (bad_row.reject_reason or ""),
			f"{bad_row}",
		)
		attached = frappe.get_all(
			"File", filters={"attached_to_doctype": "UA Update Package", "attached_to_name": good_row.name}, pluck="name"
		) if good_row else []
		chk(
			"забраний пакет лежить вкладенням — далі той самий шлях, що й файлом (FR-036)",
			len(attached) == 1 and api._package_bytes(frappe.get_doc("UA Update Package", good_row.name)) == feed_good,
			f"вкладень {len(attached)}",
		)
		repeat = poll_packages()
		chk(
			"повторний забір нічого не дублює",
			len(polled) == 2 and repeat == []
			and frappe.db.count("UA Update Package", {"source_url": ["like", "https://feed.test/%"]}) == 2,
			f"перший {len(polled)}, другий {len(repeat)}",
		)

		def broken(url):
			raise feed_module.FeedError("Канал роздачі відповів 503")

		feed_module.fetch_releases = broken
		log_before = frappe.db.count("UA Operation Log", {"message": "Канал роздачі відповів 503"})
		poll_packages()
		chk(
			"недоступний канал лишає запис у журналі, а не мовчить",
			frappe.db.count("UA Operation Log", {"message": "Канал роздачі відповів 503", "result": "Помилка"})
			== log_before + 1,
		)
	finally:
		feed_module.fetch_releases, feed_module.download = _fetch, _download
		frappe.db.delete("Singles", {"doctype": SETTINGS})
		for field, value in _singles:
			frappe.db.sql("insert into tabSingles (doctype, field, value) values (%s, %s, %s)", (SETTINGS, field, value))
		frappe.clear_document_cache(SETTINGS, SETTINGS)
	chk(
		"налаштування повернуто точно, як були",
		frappe.db.sql(singles_query, SETTINGS) == _singles,
		f"рядків {len(_singles)}",
	)

	# 9.8 Ручне заведення з форми: людина обирає лише канал
	manual = build_package(
		PARAMETERS_CSV.replace("TEST_PKG_MIN_WAGE", "TEST_PKG_MANUAL"), keys=SIGNERS, version=V(20261022)
	)
	results_manual = {}
	for title in ("Параметри", "Класифікатори"):
		doc = frappe.get_doc({"doctype": "UA Update Package", "channel": title, "version": str(V(20261022)), "state": "Отримано"})
		doc.insert(ignore_permissions=True)
		doc.run_verification(manual)
		results_manual[title] = frappe.db.get_value(
			"UA Update Package", doc.name, ["channel_code", "state", "reject_reason"], as_dict=True
		)
	chk(
		"пакет із форми отримує код каналу з обраного каналу і проходить перевірку",
		results_manual["Параметри"].channel_code == "parameters" and results_manual["Параметри"].state == "До застосування",
		str(results_manual["Параметри"]),
	)
	chk(
		"пакет параметрів, заведений на канал класифікаторів, відхилено",
		results_manual["Класифікатори"].state == "Відхилено"
		and "канал пакета parameters" in (results_manual["Класифікатори"].reject_reason or ""),
		str(results_manual["Класифікатори"]),
	)
finally:
	keys_module.TRUSTED_KEYS[:] = _production_keys

chk("бойові ключі не лишилися підміненими перевіркою", keys_module.TRUSTED_KEYS == _production_keys)

# 10. Календар і норма часу (US4)
from ua_compliance.calendar import build as calendar_build

MARTIAL_CODE = "TEST_MARTIAL_LAW"
frappe.db.delete("UA Legal Parameter", {"code": MARTIAL_CODE})
for name in frappe.get_all("UA Holiday Rule", filters={"holiday_name": ["like", "Перевірка %"]}, pluck="name"):
	frappe.db.delete("UA Holiday Rule", {"name": name})


def make_flag(valid_from, value, valid_to=None):
	doc = frappe.get_doc(
		{
			"doctype": "UA Legal Parameter",
			"code": MARTIAL_CODE,
			"parameter_name": "Воєнний стан (перевірка)",
			"value_type": "Ознака",
			"value_flag": value,
			"valid_from": valid_from,
			"valid_to": valid_to,
			"basis_type": "Закон",
			"basis_number": "2136-IX",
			"basis_date": "2022-03-15",
			"basis_url": "https://zakon.rada.gov.ua/laws/show/2136-20",
			"source": "Введено вручну",
			"verified_on": "2026-10-02",
		}
	)
	doc.insert(ignore_permissions=True)
	return doc


def make_rule(name, day, month, rule_type="Фіксована дата", valid_from="2020-01-01"):
	return frappe.get_doc(
		{
			"doctype": "UA Holiday Rule",
			"holiday_name": name,
			"rule_type": rule_type,
			"day": day,
			"month": month,
			"is_day_off": 1,
			"valid_from": valid_from,
			"basis_type": "Закон",
			"basis_number": "322-08",
			"basis_date": "1971-12-10",
			"basis_url": "https://zakon.rada.gov.ua/laws/show/322-08",
			"source": "Введено вручну",
		}
	).insert(ignore_permissions=True)


flag_war = make_flag("2022-03-15", 1, valid_to="2026-12-31")
flag_peace = make_flag("2027-01-01", 0)
rule_new_year = make_rule("Перевірка: Новий рік", 1, 1)
# Друге свято на ту саму дату: збіг буває (Великдень 01.05.2016 = День праці)
rule_same_day = make_rule("Перевірка: збіг дат", 1, 1)
rule_easter = make_rule("Перевірка: Великдень", None, None, rule_type="Великдень")

TITLE_2027 = "Перевірка календаря 2027"
war_title = "Перевірка календаря 2025"

# 2027 — воєнний стан уже закінчився: свята стають вихідними
built = calendar_build.build_holiday_list(2027, title=TITLE_2027, martial_law_code=MARTIAL_CODE)
chk(
	"після закінчення воєнного стану свята стають вихідними (FR-041)",
	built["martial_law"] is False and built["holidays"] >= 1,
	str(built),
)

new_year_rows = frappe.get_all(
	"Holiday", filters={"parent": TITLE_2027, "holiday_date": "2027-01-01"}, pluck="description"
)
chk(
	"свята, що збіглися в одну дату, — один рядок з обома назвами",
	len(new_year_rows) == 1
	and "Перевірка: Новий рік" in new_year_rows[0]
	and "Перевірка: збіг дат" in new_year_rows[0],
	"; ".join(new_year_rows),
)

again = calendar_build.build_holiday_list(2027, title=TITLE_2027, martial_law_code=MARTIAL_CODE)
rows_2027 = frappe.db.count("Holiday", {"parent": TITLE_2027})
chk(
	"повторна побудова дає той самий склад без дублів (FR-043)",
	again["total"] == built["total"] == rows_2027,
	f"{built['total']} = {again['total']} = {rows_2027}",
)

# 2025 — воєнний стан діє: свята не вихідні
built_war = calendar_build.build_holiday_list(2025, title=war_title, martial_law_code=MARTIAL_CODE)
chk(
	"у воєнний стан свята не є вихідними (FR-041)",
	built_war["martial_law"] is True and built_war["holidays"] == 0,
	str(built_war),
)

# Перебудова, що зачіпає минулі дати, потребує підтвердження
flag_war.valid_to = "2024-12-31"
flag_war.save(ignore_permissions=True)
make_flag("2025-01-01", 0, valid_to="2026-12-31")
try:
	calendar_build.build_holiday_list(2025, title=war_title, martial_law_code=MARTIAL_CODE)
	chk("перебудова за минулі дати потребує підтвердження (FR-046)", False, "пройшла без підтвердження")
except frappe.ValidationError as error:
	chk("перебудова за минулі дати потребує підтвердження (FR-046)", "минулих дат" in str(error), str(error)[:90])

confirmed = calendar_build.build_holiday_list(
	2025, title=war_title, confirm_past=True, martial_law_code=MARTIAL_CODE
)
chk(
	"з підтвердженням перебудова проходить і свята стають вихідними",
	confirmed["holidays"] >= 1,
	str(confirmed),
)

journal_past = frappe.get_all(
	"UA Operation Log",
	filters={"kind": "Перебудова календаря", "message": ["like", f"{war_title}%підтверджено зміну минулих дат%"]},
	pluck="message",
)
chk("підтверджена перебудова минулих дат записана в журнал (FR-046)", bool(journal_past), "; ".join(journal_past)[:120])

# Кнопка «Побудувати календар»: серверний метод на пісочному році 2099 (лише майбутні
# дати). Чинний робочий параметр воєнного стану не чіпаємо: якщо на екземплярі його
# немає, метод має відмовити, а не вигадати ознаку.
SANDBOX_YEAR = 2099
try:
	via_api = api.rebuild_calendar(SANDBOX_YEAR)
	chk(
		"кнопка будує календар року й пише журнал",
		frappe.db.exists("Holiday List", via_api["title"])
		and frappe.db.exists("UA Operation Log", {"kind": "Перебудова календаря", "message": ["like", f"{via_api['title']}%"]}),
		str(via_api),
	)
except frappe.ValidationError as error:
	chk(
		"кнопка будує календар року й пише журнал",
		"не визначено" in str(error),
		f"ознаки воєнного стану на екземплярі немає — відмова: {str(error)[:80]}",
	)
frappe.set_user("Guest")
try:
	api.rebuild_calendar(SANDBOX_YEAR)
	chk("будувати календар без ролі не можна", False, "побудувався")
except frappe.ValidationError as error:
	chk("будувати календар без ролі не можна", "лише роль" in str(error), str(error)[:80])
finally:
	frappe.set_user("Administrator")

# Норма часу рахується за календарем
norm = calendar_build.working_time(2027, title=TITLE_2027)
days_off = frappe.db.count("Holiday", {"parent": TITLE_2027})
chk(
	"норма часу рахується за календарем, а не зберігається (FR-044)",
	norm["working_days"] + days_off == 365 and norm["hours"] == norm["working_days"] * 8,
	f"робочих {norm['working_days']}, вихідних {days_off}, годин {norm['hours']}",
)

# 11. Звіт норми часу
from frappe.desk.query_report import run as run_report

report = run_report(
	"UA-Норма робочого часу",
	filters={"year": 2027, "holiday_list": TITLE_2027, "hours_per_day": 8},
	ignore_prepared_report=True,
)
# Платформа може віддати рядки звіту і словниками, і списками — беремо обидва випадки.
# У звіті ввімкнено підсумковий рядок, тому беремо лише дванадцять місяців.
month_rows = report["result"][:12]
report_days = sum(
	row["working_days"] if isinstance(row, dict) else row[1] for row in month_rows
)
chk(
	"звіт норми часу рахує за календарем",
	len(month_rows) == 12 and report_days == norm["working_days"],
	f"місяців {len(month_rows)}, робочих днів {report_days}",
)

# 12. Класифікатори (US5)
import time as _time

CLASSIFIER_CSV = """classifier,code,entry_name,parent_code,level,valid_from,valid_to
КАТОТТГ,UA00000000000000001,Тестова область,,1,2021-01-01,
КАТОТТГ,UA00000000000000002,Тестовий район,UA00000000000000001,2,2021-01-01,
КАТОТТГ,UA00000000000000003,Тестова громада,UA00000000000000002,3,2021-01-01,
"""

keys_module.TRUSTED_KEYS[:] = [key_a, key_b, key_c]
try:
	classifier_package = build_package(
		CLASSIFIER_CSV, channel="classifiers", keys=SIGNERS, version=V(20261101)
	)
	package_classifier = receive(classifier_package, "classifiers", V(20261101))
	ok_classifier = package_classifier.run_verification(classifier_package)
	chk(
		"пакет класифікатора проходить перевірку",
		ok_classifier and len(package_classifier.preview) == 3,
		f"{package_classifier.state}, рядків передпоказу {len(package_classifier.preview)}",
	)

	package_classifier.approve_and_apply(classifier_package)
	chk(
		"коди класифікатора застосовані пакетом",
		frappe.db.count("UA Classifier Entry", {"code": ["like", "UA000000000000000%"]}) == 3,
	)
	# Платформа ставить право на запис за умовчанням, тому права перевіряються
	# по ВСІХ доктайпах застосунку, а не лише там, де про це згадали (спіймано 02.10.2026).
	writable_for_all = []
	deletable = []
	for doctype_name in frappe.get_all("DocType", filters={"module": "UA Compliance", "istable": 0}, pluck="name"):
		for perm in frappe.get_all(
			"DocPerm",
			filters={"parent": doctype_name},
			fields=["role", "write", "create", "delete"],
		):
			if perm.role == "All" and (perm.write or perm.create):
				writable_for_all.append(f"{doctype_name}: {perm.role}")
			if perm.delete:
				deletable.append(f"{doctype_name}: {perm.role}")
	chk(
		"жоден доктайп застосунку не доступний на запис усім (FR-019, FR-048)",
		not writable_for_all,
		"; ".join(writable_for_all),
	)
	chk(
		"права на видалення немає ні в кого (принцип III)",
		not deletable,
		"; ".join(deletable),
	)

	# Закриття коду датою
	closing_csv = CLASSIFIER_CSV.replace(
		"КАТОТТГ,UA00000000000000003,Тестова громада,UA00000000000000002,3,2021-01-01,",
		"КАТОТТГ,UA00000000000000003,Тестова громада,UA00000000000000002,3,2021-01-01,2026-09-30",
	)
	closing_package = build_package(closing_csv, channel="classifiers", keys=SIGNERS, version=V(20261102))
	package_closing = receive(closing_package, "classifiers", V(20261102))
	package_closing.run_verification(closing_package)
	package_closing.approve_and_apply(closing_package)
	chk(
		"виведений код закривається датою, а не видаляється (FR-049)",
		frappe.db.get_value("UA Classifier Entry", "КАТОТТГ-UA00000000000000003", "valid_to") is not None
		and frappe.db.exists("UA Classifier Entry", "КАТОТТГ-UA00000000000000003"),
	)

	from ua_compliance.packages.apply import active_codes

	offered = [row.code for row in active_codes("КАТОТТГ", "2026-10-02", search="UA00000000000000")]
	chk(
		"закритий код до вибору не пропонується, чинні лишаються (FR-051)",
		"UA00000000000000003" not in offered and len(offered) == 2,
		str(offered),
	)

	# Обсяг: 32 000 кодів
	bulk_rows = "\n".join(
		f"КАТОТТГ,UA9{number:018d},Тестовий запис {number},,4,2021-01-01," for number in range(32000)
	)
	bulk_csv = "classifier,code,entry_name,parent_code,level,valid_from,valid_to\n" + bulk_rows + "\n"
	bulk_package = build_package(bulk_csv, channel="classifiers", keys=SIGNERS, version=V(20261103))
	package_bulk = receive(bulk_package, "classifiers", V(20261103))
	started_bulk = _time.time()
	package_bulk.run_verification(bulk_package)
	package_bulk.approve_and_apply(bulk_package)
	elapsed = _time.time() - started_bulk
	loaded = frappe.db.count("UA Classifier Entry", {"code": ["like", "UA9%"]})
	chk(
		"32 000 кодів завантажуються за менш ніж 2 хвилини (SC-008)",
		loaded == 32000 and elapsed < 120,
		f"{loaded} кодів за {elapsed:.0f} с",
	)
	frappe.db.delete("UA Classifier Entry", {"code": ["like", "UA9%"]})
finally:
	keys_module.TRUSTED_KEYS[:] = _production_keys

# 12а. Розділ «Законодавство»: ярлики з контракту екранів (pages-ui, екран 11), читаємо
# збережений воркспейс, а не файл, — migrate буває, що підміняє його
workspace = frappe.get_doc("Workspace", "Законодавство")
CONTRACT_SHORTCUTS = [
	"Законодавчі параметри", "Пакети оновлень", "Курси валют", "Свята",
	"Класифікатори", "Журнал операцій", "Норма робочого часу",
]
chk(
	"розділ «Законодавство» має ярлики з контракту екранів",
	[row.label for row in workspace.shortcuts] == CONTRACT_SHORTCUTS,
	", ".join(row.label for row in workspace.shortcuts),
)
dangling = [
	row.link_to
	for row in list(workspace.shortcuts) + [r for r in workspace.links if r.type == "Link"]
	if not frappe.db.exists("Report" if (row.get("type") == "Report" or row.get("link_type") == "Report") else "DocType", row.link_to)
]
chk("усі посилання розділу ведуть на наявні екрани", not dangling, ", ".join(dangling))

# Бокова панель розділу (контракт екранів, екран 11): без власного файла desk збирає її
# сам із доктайпів модуля — з технічними іменами й без половини екранів
sidebar = frappe.get_doc("Workspace Sidebar", "Законодавство") if frappe.db.exists("Workspace Sidebar", "Законодавство") else None
sidebar_links = [row for row in (sidebar.items if sidebar else []) if row.type == "Link"]
chk(
	"бокова панель розділу — з ярликами контракту, українськими підписами",
	sidebar is not None
	and all(label in [row.label for row in sidebar_links] for label in CONTRACT_SHORTCUTS)
	and not any(row.label.startswith("UA ") for row in sidebar_links),
	", ".join(row.label for row in sidebar_links),
)
sidebar_dangling = [
	row.link_to for row in sidebar_links if not frappe.db.exists(row.link_type, row.link_to)
]
chk("усі посилання бокової панелі ведуть на наявні екрани", not sidebar_dangling, ", ".join(sidebar_dangling))

# 12а-2. Список курсів за контрактом екранів (екран 1)
ce_meta = frappe.get_meta("Currency Exchange")
chk(
	"список курсів: за датою, новіші вгорі, з кратністю й джерелом",
	ce_meta.sort_field == "date"
	and ce_meta.sort_order == "DESC"
	and all(ce_meta.get_field(f).in_list_view for f in ("ua_multiplicity", "ua_source")),
	f"{ce_meta.sort_field} {ce_meta.sort_order}",
)

log_meta = frappe.get_meta("UA Operation Log")
chk(
	"журнал операцій: колонки й фільтри з контракту екранів (екран 7)",
	all(log_meta.get_field(f).in_list_view for f in ("kind", "started_at", "result", "checked_count", "created_count", "updated_count", "message"))
	and all(log_meta.get_field(f).in_standard_filter for f in ("kind", "result")),
)

# 12а-3. Кожен доктайп і звіт застосунку має український підпис (спіймано на демо:
# «UA Holiday Rule» і «UA-Норма робочого часу» в заголовках)
_lang = frappe.local.lang
frappe.local.lang = "uk"
frappe.local.lang_full_dict = None
_names = frappe.get_all("DocType", filters={"module": "UA Compliance"}, pluck="name") + frappe.get_all(
	"Report", filters={"module": "UA Compliance"}, pluck="name"
)
untranslated = [n for n in _names if frappe._(n) == n]
frappe.local.lang = _lang
frappe.local.lang_full_dict = None
chk("доктайпи й звіти застосунку мають український підпис", not untranslated, ", ".join(untranslated) or f"{len(_names)} назв")

icon = frappe.db.get_value("Desktop Icon", "Законодавство", ["link_type", "link_to", "icon"], as_dict=True)
chk(
	"плитка розділу веде на його бокову панель і має значок",
	bool(icon) and icon.link_type == "Workspace Sidebar" and icon.link_to == "Законодавство" and bool(icon.icon),
	str(icon),
)
chk(
	"у списку курсів немає колонки «У валюту» — вона завжди гривня",
	not frappe.get_meta("Currency Exchange").get_field("to_currency").in_list_view,
)

# Поріг давності 0 — «попереджати одразу», а не «за умовчанням 45»
from ua_compliance.packages.jobs import stale_threshold

chk(
	"поріг давності 0 діє як нуль, а не як 45",
	stale_threshold(frappe._dict(stale_warning_days=0)) == 0
	and stale_threshold(frappe._dict(stale_warning_days=45)) == 45,
)

# Мелочі з перевірки на екрані 04.10.2026: відмінювання днів і посилання без схеми
from ua_compliance.packages.jobs import uk_days

chk(
	"«1 день, 3 дні, 5 днів, 11 днів, 21 день, 22 дні» у попередженні",
	[uk_days(n) for n in (1, 3, 5, 11, 21, 22, 112)] == ["день", "дні", "днів", "днів", "день", "дні", "днів"],
)
try:
	frappe.get_doc(
		{
			"doctype": "UA Legal Parameter", "code": "TEST_URL_SCHEME", "parameter_name": "Перевірка посилання",
			"value_type": "Сума", "value_number": 1, "valid_from": "2001-01-01", "basis_type": "Закон",
			"basis_number": "1-IX", "basis_date": "2001-01-01", "basis_url": "zakon.rada.gov.ua/laws/show/1-20",
			"source": "Введено вручну", "verified_on": "2026-10-04",
		}
	).insert(ignore_permissions=True)
	chk("посилання на норму без https:// не приймається", False, "збереглося")
except frappe.ValidationError as error:
	chk("посилання на норму без https:// не приймається", "https://" in str(error), str(error)[:90])

# Найдовша офіційна назва КВЕД — 153 символи (47.43); стандартні 140 у Data її обрізали б
# з помилкою вставки (спіймано на репетиції першого пакета класифікаторів 04.10.2026)
_entry_len = frappe.db.sql(
	"select character_maximum_length from information_schema.columns where table_name='tabUA Classifier Entry' and column_name='entry_name' and table_schema=database()"
)
chk(
	"назва коду класифікатора вміщує 255 символів",
	bool(_entry_len) and int(_entry_len[0][0]) >= 255,
	str(_entry_len),
)

# T067 і T065: картка пакета вкладками, блок попереджень у розділі
package_meta = frappe.get_meta("UA Update Package")
chk(
	"картка пакета — вкладки «Загальне / Файли / Що зміниться» (контракт екранів, екран 5)",
	[f.label for f in package_meta.fields if f.fieldtype == "Tab Break"] == ["Загальне", "Файли", "Що зміниться"],
	str([f.label for f in package_meta.fields if f.fieldtype == "Tab Break"]),
)
section_blocks = [
	b["data"].get("custom_block_name")
	for b in frappe.parse_json(frappe.db.get_value("Workspace", "Законодавство", "content"))
	if b["type"] == "custom_block"
]
# Розділ малює блок лише з таблиці custom_blocks (frappe.desk.desktop), розкладки мало —
# саме так блок не показувався на екрані при зеленій перевірці розкладки (04.10.2026)
from frappe.desk.desktop import get_desktop_page

_page = get_desktop_page(frappe.as_json({"name": "Законодавство", "title": "Законодавство", "public": 1}))
chk(
	"у розділі є блок попереджень: у розкладці й у тому, що віддається на сторінку",
	section_blocks == ["Попередження законодавства"]
	and [b.custom_block_name for b in _page["custom_blocks"]["items"]] == ["Попередження законодавства"],
	str([b.custom_block_name for b in _page["custom_blocks"]["items"]]),
)

# 12б. Розклад курсу живе в налаштуваннях: такт звіряє час і не дублює запуск
from datetime import datetime as _dt
from datetime import timedelta as _td

from ua_compliance import journal as _journal
from ua_compliance.rates import job as rates_job

_settings_rows = frappe.db.sql("select field, value from tabSingles where doctype=%s order by field", "UA Compliance Settings")
_load_rates = rates_job.load_rates
_now = frappe.utils.now_datetime().replace(microsecond=0)
try:
	# Вікно відкривається зараз: завантаження курсу, які харнес зробив на початку
	# прогону, лишаються до вікна й не маскують такт.
	slot_time = _now.time()
	frappe.db.set_single_value(
		"UA Compliance Settings",
		{"rates_enabled": 1, "rates_morning_time": str(slot_time), "rates_evening_time": "23:59:00"},
	)
	settings_now = frappe.get_single("UA Compliance Settings")
	chk(
		"вікно запуску рахується від часу з налаштувань",
		rates_job.due_slot(settings_now, _now) == _dt.combine(_now.date(), slot_time)
		and rates_job.due_slot(settings_now, _now + _td(hours=2)) is None,
		str(rates_job.due_slot(settings_now, _now)),
	)
	# Завантаження підмінене: курс не чіпаємо, рахуємо лише, скільки разів такт його запустив
	rates_job.load_rates = lambda **kwargs: _journal.write("Завантаження курсу", "Успішно", "перевірка такту")
	before_ticks = frappe.db.count("UA Operation Log", {"message": "перевірка такту"})
	rates_job.scheduled_tick()
	rates_job.scheduled_tick()
	chk(
		"у вікні такт запускає завантаження один раз, а не двічі",
		frappe.db.count("UA Operation Log", {"message": "перевірка такту"}) == before_ticks + 1,
	)
finally:
	rates_job.load_rates = _load_rates
	frappe.db.delete("Singles", {"doctype": "UA Compliance Settings"})
	for field, value in _settings_rows:
		frappe.db.sql(
			"insert into tabSingles (doctype, field, value) values (%s, %s, %s)", ("UA Compliance Settings", field, value)
		)
	frappe.clear_document_cache("UA Compliance Settings", "UA Compliance Settings")
rate_jobs = frappe.get_all("Scheduled Job Type", filters={"method": ["like", "ua_compliance.rates.%"]}, pluck="method")
chk("у розкладі одне завдання курсу — такт", rate_jobs == ["ua_compliance.rates.job.scheduled_tick"], ", ".join(rate_jobs))

# T066 (після перевірки такту: записи серії в його вікні замаскували б запуск). Серія невдалих завантажень курсу — попередження, один раз на серію
from ua_compliance import journal as _journal_series
from ua_compliance.packages.jobs import rate_failure_warnings
from ua_compliance.rates import job as _rates_job_series

for _ in range(3):
	_journal_series.write("Завантаження курсу", "Помилка", "перевірка серії: джерело відповіло 403")
series = rate_failure_warnings()
_rates_job_series._warn_on_failure_series()
_rates_job_series._warn_on_failure_series()
chk(
	"3 невдачі курсу поспіль — попередження, у журналі один раз на серію",
	bool(series) and "3 разів поспіль" in series[0]
	and frappe.db.count("UA Operation Log", {"kind": "Попередження", "message": ["like", "Курс НБУ не завантажується%перевірка серії%"]}) == 1,
	"; ".join(series),
)

# 13. Прибирання за собою
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
