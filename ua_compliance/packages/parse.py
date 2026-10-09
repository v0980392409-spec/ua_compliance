"""Розбір файлів даних пакета за схемою каналу."""

import csv
import io
from datetime import date

from ua_compliance.calendar.rules import RULE_TYPES, slot_key
from ua_compliance.packages.reader import PackageError

CHANNEL_BY_CODE = {"parameters": "Параметри", "calendar": "Календар", "classifiers": "Класифікатори"}

PARAMETER_COLUMNS = (
	"code",
	"parameter_name",
	"value_type",
	"value",
	"unit",
	"valid_from",
	"valid_to",
	"basis_type",
	"basis_number",
	"basis_date",
	"basis_clause",
	"basis_url",
	"verified_on",
)
REQUIRED_PARAMETER_COLUMNS = (
	"code",
	"parameter_name",
	"value_type",
	"value",
	"valid_from",
	"basis_type",
	"basis_number",
	"basis_date",
	"basis_url",
	"verified_on",
)


def parse_parameters(file_name, raw):
	"""Повертає список рядків каналу «Параметри». Помилка називає файл і рядок."""
	try:
		text = raw.decode("utf-8")
	except UnicodeDecodeError:
		raise PackageError(f"Пакет не прийнято: {file_name} не у кодуванні UTF-8") from None

	reader = csv.DictReader(io.StringIO(text))
	missing = set(REQUIRED_PARAMETER_COLUMNS) - set(reader.fieldnames or [])
	if missing:
		raise PackageError(
			f"Пакет не прийнято: {file_name}, бракує колонок: {', '.join(sorted(missing))}"
		)

	rows = []
	for number, row in enumerate(reader, start=2):
		for column in REQUIRED_PARAMETER_COLUMNS:
			if not (row.get(column) or "").strip():
				raise PackageError(f"Пакет не прийнято: {file_name}, рядок {number}: не заповнено {column}")
		rows.append({key: (row.get(key) or "").strip() for key in PARAMETER_COLUMNS})

	if not rows:
		raise PackageError(f"Пакет не прийнято: {file_name} не містить жодного рядка")
	return rows


CLASSIFIER_COLUMNS = ("classifier", "code", "entry_name", "parent_code", "level", "valid_from", "valid_to")
REQUIRED_CLASSIFIER_COLUMNS = ("classifier", "code", "entry_name", "valid_from")


def parse_classifiers(file_name, raw):
	"""Повертає список рядків каналу «Класифікатори»."""
	try:
		text = raw.decode("utf-8")
	except UnicodeDecodeError:
		raise PackageError(f"Пакет не прийнято: {file_name} не у кодуванні UTF-8") from None

	reader = csv.DictReader(io.StringIO(text))
	missing = set(REQUIRED_CLASSIFIER_COLUMNS) - set(reader.fieldnames or [])
	if missing:
		raise PackageError(f"Пакет не прийнято: {file_name}, бракує колонок: {', '.join(sorted(missing))}")

	rows = []
	for number, row in enumerate(reader, start=2):
		for column in REQUIRED_CLASSIFIER_COLUMNS:
			if not (row.get(column) or "").strip():
				raise PackageError(f"Пакет не прийнято: {file_name}, рядок {number}: не заповнено {column}")
		rows.append({key: (row.get(key) or "").strip() for key in CLASSIFIER_COLUMNS})

	if not rows:
		raise PackageError(f"Пакет не прийнято: {file_name} не містить жодного рядка")
	return rows


HOLIDAY_COLUMNS = (
	"holiday_name",
	"rule_type",
	"day",
	"month",
	"offset_days",
	"is_day_off",
	"valid_from",
	"valid_to",
	"basis_type",
	"basis_number",
	"basis_date",
	"basis_url",
)
REQUIRED_HOLIDAY_COLUMNS = (
	"holiday_name",
	"rule_type",
	"is_day_off",
	"valid_from",
	"basis_type",
	"basis_number",
	"basis_date",
	"basis_url",
)


def parse_holidays(file_name, raw):
	"""Повертає рядки каналу «Календар» — правила свят.

	Кожен рядок дістає «code» — місце свята в році (24.08, Великдень): за ним пакет
	зіставляє правило з наявним, і його ж людина бачить у передпоказі. Дати й числа
	перевіряються тут, а не на застосуванні: битий рядок має відхилити пакет до
	затвердження, а не зірвати застосування після нього.
	"""
	try:
		text = raw.decode("utf-8")
	except UnicodeDecodeError:
		raise PackageError(f"Пакет не прийнято: {file_name} не у кодуванні UTF-8") from None

	reader = csv.DictReader(io.StringIO(text))
	missing = set(REQUIRED_HOLIDAY_COLUMNS) - set(reader.fieldnames or [])
	if missing:
		raise PackageError(f"Пакет не прийнято: {file_name}, бракує колонок: {', '.join(sorted(missing))}")

	rows = []
	seen = set()
	for number, row in enumerate(reader, start=2):
		where = f"Пакет не прийнято: {file_name}, рядок {number}"
		values = {key: (row.get(key) or "").strip() for key in HOLIDAY_COLUMNS}
		for column in REQUIRED_HOLIDAY_COLUMNS:
			if not values[column]:
				raise PackageError(f"{where}: не заповнено {column}")
		if values["rule_type"] not in RULE_TYPES:
			raise PackageError(f"{where}: невідомий вид правила «{values['rule_type']}»")
		if values["is_day_off"] not in ("0", "1"):
			raise PackageError(f"{where}: is_day_off — 0 або 1")
		try:
			if values["rule_type"] == "Фіксована дата":
				date(2000, int(values["month"]), int(values["day"]))  # 2000 — високосний: 29.02 допустиме
			else:
				int(values["offset_days"] or 0)
			for column in ("valid_from", "valid_to", "basis_date"):
				if values[column]:
					date.fromisoformat(values[column])
		except ValueError:
			raise PackageError(f"{where}: дата або число не розпізнано") from None
		if values["valid_to"] and values["valid_to"] < values["valid_from"]:
			raise PackageError(f"{where}: дата закінчення дії раніша за дату початку")
		values["code"] = slot_key(values["rule_type"], values["day"], values["month"], values["offset_days"])
		if (values["code"], values["valid_from"]) in seen:
			raise PackageError(f"{where}: свято {values['code']} з {values['valid_from']} уже є в пакеті")
		seen.add((values["code"], values["valid_from"]))
		rows.append(values)

	if not rows:
		raise PackageError(f"Пакет не прийнято: {file_name} не містить жодного рядка")
	return rows
