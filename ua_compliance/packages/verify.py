"""Перевірка пакета: шість кроків у строгому порядку, зупинка на першій невдачі.

Порядок і тексти відмов — з контракту пакета (contracts/package-manifest.md).
Кожна відмова лишає запис у журналі: мовчазних відмов не буває.
"""

import frappe
from frappe.utils import getdate, today

import ua_compliance
from ua_compliance.packages import keys as keys_module
from ua_compliance.packages import parse as package_parse
from ua_compliance.packages.reader import PackageError, open_package, sha256
from ua_compliance.packages.signature import SignatureError, verify_detached

MANIFEST_TYPE = "ua-compliance-package"


def verify(raw: bytes, last_applied_version=None):
	"""Повертає словник з маніфестом, підписами й розібраними даними.

	Кидає PackageError з текстом відмови, якщо хоч одна перевірка не пройдена.
	"""
	manifest, manifest_bytes, signatures, data_files = open_package(raw)

	if manifest.get("type") != MANIFEST_TYPE:
		raise PackageError("Пакет не прийнято: маніфест не того виду")

	# 1. Підписи
	trusted = keys_module.trusted_keys()
	if not trusted:
		raise PackageError("Пакет не прийнято: ключі підпису ще не випущені")

	key_ids = set()
	for signature_text in signatures:
		try:
			key_ids.add(verify_detached(manifest_bytes, signature_text, trusted))
		except SignatureError:
			continue
	if len(key_ids) < keys_module.THRESHOLD:
		raise PackageError(
			f"Пакет не прийнято: підписів {len(key_ids)}, потрібно {keys_module.THRESHOLD}"
		)

	# 2. Версія
	version = manifest.get("version")
	if version is None:
		raise PackageError("Пакет не прийнято: у маніфесті немає версії")
	if last_applied_version is not None and int(version) <= int(last_applied_version):
		raise PackageError(
			f"Пакет не прийнято: версія {version} не новіша за застосовану {last_applied_version}"
		)

	# 3. Строк придатності
	expires = manifest.get("expires")
	if not expires:
		raise PackageError("Пакет не прийнято: у маніфесті немає строку придатності")
	if getdate(expires) < getdate(today()):
		raise PackageError(
			f"Пакет не прийнято: строк придатності маніфесту минув {getdate(expires).strftime('%d.%m.%Y')}"
		)

	# 4. Версія застосунку (FR-052)
	required = manifest.get("min_app_version")
	if required and _version_tuple(ua_compliance.__version__) < _version_tuple(required):
		raise PackageError(f"Пакет не прийнято: потрібна версія застосунку не нижче {required}")

	# 5. Розмір і хеш кожного файла
	declared = manifest.get("files") or []
	if not declared:
		raise PackageError("Пакет не прийнято: маніфест не перелічує жодного файла")
	for entry in declared:
		name = entry.get("name")
		raw_file = data_files.get(name)
		if raw_file is None:
			raise PackageError(f"Пакет не прийнято: файла {name} немає в архіві")
		if int(entry.get("size") or -1) != len(raw_file) or entry.get("sha256") != sha256(raw_file):
			raise PackageError(f"Пакет не прийнято: файл {name} не відповідає хешу в маніфесті")

	# 6. Розбір вмісту
	channel_code = manifest.get("channel")
	if channel_code not in package_parse.CHANNEL_BY_CODE:
		raise PackageError(f"Пакет не прийнято: невідомий канал {channel_code}")
	if channel_code == "calendar":
		raise PackageError(f"Пакет не прийнято: канал {channel_code} ще не підтримується")

	parser = (
		package_parse.parse_parameters if channel_code == "parameters" else package_parse.parse_classifiers
	)

	rows = []
	for entry in declared:
		rows += parser(entry["name"], data_files[entry["name"]])

	return {
		"manifest": manifest,
		"manifest_hash": sha256(manifest_bytes),
		"key_ids": sorted(key_ids),
		"rows": rows,
		"files": [
			{
				"file_name": entry["name"],
				"size": entry.get("size"),
				"sha256": entry.get("sha256"),
				"rows_count": len(parser(entry["name"], data_files[entry["name"]])),
				"check_result": "Збіглося",
			}
			for entry in declared
		],
	}


def last_applied_version(channel_code):
	"""Найбільша застосована версія каналу — захист від відкоту (FR-025)."""
	channel = package_parse.CHANNEL_BY_CODE[channel_code]
	versions = frappe.get_all(
		"UA Update Package",
		filters={"channel": channel, "state": "Застосовано"},
		pluck="version",
	)
	numeric = [int(v) for v in versions if str(v).isdigit()]
	return max(numeric) if numeric else None


def _version_tuple(value):
	return tuple(int(part) for part in str(value).split(".") if part.isdigit())
