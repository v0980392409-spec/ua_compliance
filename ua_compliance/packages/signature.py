"""Перевірка підпису minisign (Ed25519) силами бібліотеки `cryptography`.

Бібліотека входить у залежності платформи, тому застосунок не додає жодної нової.

Формат файла підпису minisign:
    рядок 1  untrusted comment: ...
    рядок 2  base64( алгоритм[2] + ідентифікатор ключа[8] + підпис[64] )
    рядок 3  trusted comment: ...
    рядок 4  base64( глобальний підпис[64] ) — над (підпис + довірений коментар)

Алгоритм «Ed» підписує сам файл, «ED» — його хеш BLAKE2b-512 (так minisign робить
за умовчанням).
"""

import base64
import hashlib

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey


class SignatureError(Exception):
	"""Підпис не розібрано або він не підходить."""


def _decode_public_key(encoded):
	raw = base64.b64decode(encoded)
	if len(raw) != 42:
		raise SignatureError("Невірна довжина відкритого ключа")
	return raw[:2], raw[2:10], raw[10:]


def _decode_signature(text):
	lines = [line.strip() for line in text.strip().splitlines() if line.strip()]
	if len(lines) < 2:
		raise SignatureError("Файл підпису порожній або неповний")
	raw = base64.b64decode(lines[1])
	if len(raw) != 74:
		raise SignatureError("Невірна довжина підпису")
	algorithm, key_id, signature = raw[:2], raw[2:10], raw[10:]
	trusted_comment = ""
	global_signature = b""
	for line in lines[2:]:
		if line.startswith("trusted comment:"):
			trusted_comment = line.split(":", 1)[1].strip()
		else:
			try:
				global_signature = base64.b64decode(line)
			except Exception:
				continue
	return algorithm, key_id, signature, trusted_comment, global_signature


def verify_detached(payload: bytes, signature_text: str, public_keys):
	"""Повертає ідентифікатор ключа, яким підписано, або кидає SignatureError."""
	algorithm, key_id, signature, trusted_comment, global_signature = _decode_signature(signature_text)
	if algorithm == b"ED":
		signed = hashlib.blake2b(payload, digest_size=64).digest()
	elif algorithm == b"Ed":
		signed = payload
	else:
		raise SignatureError(f"Невідомий алгоритм підпису: {algorithm!r}")

	for encoded in public_keys:
		# Зіставляємо лише за ідентифікатором ключа: у minisign у файлі відкритого
		# ключа стоїть «Ed», а підпис попередньо хешованого вмісту позначено «ED».
		_key_algorithm, candidate_id, raw_key = _decode_public_key(encoded)
		if candidate_id != key_id:
			continue
		public_key = Ed25519PublicKey.from_public_bytes(raw_key)
		try:
			public_key.verify(signature, signed)
		except InvalidSignature:
			raise SignatureError("Підпис не відповідає вмісту") from None
		if global_signature:
			# Довірений коментар захищений окремим підписом: інакше його можна
			# було б підмінити, не чіпаючи самого підпису файла.
			try:
				public_key.verify(global_signature, signature + trusted_comment.encode())
			except InvalidSignature:
				raise SignatureError("Довірений коментар підписано невірно") from None
		return base64.b64encode(key_id).decode()

	raise SignatureError("Підпис зроблено ключем, якого немає серед довірених")
