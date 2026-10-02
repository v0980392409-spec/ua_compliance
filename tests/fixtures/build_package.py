"""Збирач тестового пакета: ключі, підписи у форматі minisign, zip.

Потрібен перевіркам і харнесу. Бойові пакети збирає видавець своїм інструментом;
тут та сама форма, щоб перевіряти саме той шлях розбору, яким піде справжній пакет.
"""

import base64
import hashlib
import io
import json
import os
import zipfile

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey


def generate_key():
	"""Повертає (відкритий ключ у форматі minisign, приватний ключ, ідентифікатор)."""
	private_key = Ed25519PrivateKey.generate()
	public_raw = private_key.public_key().public_bytes_raw()
	key_id = os.urandom(8)
	encoded = base64.b64encode(b"Ed" + key_id + public_raw).decode()
	return encoded, private_key, key_id


def sign(payload: bytes, private_key, key_id: bytes, trusted_comment="тестовий пакет"):
	"""Підпис у форматі minisign з попереднім хешуванням (алгоритм «ED»)."""
	digest = hashlib.blake2b(payload, digest_size=64).digest()
	signature = private_key.sign(digest)
	global_signature = private_key.sign(signature + trusted_comment.encode())
	return "\n".join(
		[
			"untrusted comment: signature from test key",
			base64.b64encode(b"ED" + key_id + signature).decode(),
			f"trusted comment: {trusted_comment}",
			base64.b64encode(global_signature).decode(),
			"",
		]
	)


def build_package(csv_text, channel="parameters", version=20261002, expires="2030-12-31",
                  min_app_version="0.0.1", keys=None, notes="тестовий пакет",
                  corrupt_hash=False, extra_file=None):
	"""Збирає zip пакета. keys — список (приватний ключ, ідентифікатор)."""
	data_name = f"data/{channel}.csv"
	raw = csv_text.encode("utf-8")
	manifest = {
		"type": "ua-compliance-package",
		"channel": channel,
		"version": version,
		"created": "2026-10-02",
		"expires": expires,
		"min_app_version": min_app_version,
		"files": [
			{
				"name": data_name,
				"size": len(raw),
				"sha256": hashlib.sha256(raw if not corrupt_hash else raw + b"x").hexdigest(),
			}
		],
		"notes": notes,
	}
	manifest_bytes = json.dumps(manifest, ensure_ascii=False, indent=2).encode("utf-8")

	buffer = io.BytesIO()
	with zipfile.ZipFile(buffer, "w") as archive:
		archive.writestr("manifest.json", manifest_bytes)
		for number, (private_key, key_id) in enumerate(keys or [], start=1):
			archive.writestr(f"manifest.json.{number}.minisig", sign(manifest_bytes, private_key, key_id))
		archive.writestr(data_name, raw)
		if extra_file:
			archive.writestr(extra_file[0], extra_file[1])
	return buffer.getvalue()


PARAMETERS_CSV = """code,parameter_name,value_type,value,unit,valid_from,valid_to,basis_type,basis_number,basis_date,basis_clause,basis_url,verified_on
TEST_PKG_MIN_WAGE,Мінімальна заробітна плата (пакет),Сума,9546,грн,2027-01-01,,Закон,0000-IX,2026-12-01,ст. 8,https://zakon.rada.gov.ua/laws/show/0000-20,2026-10-02
"""
