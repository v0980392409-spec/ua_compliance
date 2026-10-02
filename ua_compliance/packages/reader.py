"""Читання пакета: zip з маніфестом, підписами й файлами даних.

Пакет несе **лише дані**. Усе, що не названо в маніфесті, ігнорується, а файли з
розширеннями, відмінними від дозволених, роблять пакет неприйнятним: логіка,
друковані форми й формати їдуть виключно релізом коду (FR-034).
"""

import hashlib
import io
import json
import zipfile

MANIFEST_NAME = "manifest.json"
ALLOWED_DATA_SUFFIXES = (".csv",)


class PackageError(Exception):
	"""Пакет не прийнято."""


def open_package(raw: bytes):
	"""Повертає (маніфест-словник, байти маніфесту, [тексти підписів], {ім'я: байти})."""
	try:
		archive = zipfile.ZipFile(io.BytesIO(raw))
	except zipfile.BadZipFile:
		raise PackageError("Пакет не прийнято: файл не є архівом") from None

	names = archive.namelist()
	if MANIFEST_NAME not in names:
		raise PackageError("Пакет не прийнято: у ньому немає маніфесту")

	manifest_bytes = archive.read(MANIFEST_NAME)
	try:
		manifest = json.loads(manifest_bytes)
	except ValueError:
		raise PackageError("Пакет не прийнято: маніфест не розбирається") from None

	signatures = [
		archive.read(name).decode("utf-8", "replace")
		for name in names
		if name.startswith(MANIFEST_NAME) and name.endswith(".minisig")
	]

	data = {}
	for name in names:
		if name == MANIFEST_NAME or name.endswith(".minisig"):
			continue
		if name.endswith("/"):
			continue
		if not name.endswith(ALLOWED_DATA_SUFFIXES):
			raise PackageError(f"Пакет не прийнято: файл {name} не є файлом даних")
		data[name] = archive.read(name)

	return manifest, manifest_bytes, signatures, data


def sha256(raw: bytes):
	return hashlib.sha256(raw).hexdigest()
