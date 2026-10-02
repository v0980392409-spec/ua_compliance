"""Розбір файлів даних пакета за схемою каналу."""

import csv
import io

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
