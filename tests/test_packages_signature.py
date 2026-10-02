"""Перевірка підпису пакета: без бази й без платформи."""

import base64

import pytest

from tests.fixtures.build_package import generate_key, sign
from ua_compliance.packages.signature import SignatureError, verify_detached

PAYLOAD = b'{"type":"ua-compliance-package","version":1}'


def test_valid_signature_returns_key_id():
	public_key, private_key, key_id = generate_key()
	signature = sign(PAYLOAD, private_key, key_id)
	assert verify_detached(PAYLOAD, signature, [public_key]) == base64.b64encode(key_id).decode()


def test_tampered_payload_is_rejected():
	public_key, private_key, key_id = generate_key()
	signature = sign(PAYLOAD, private_key, key_id)
	with pytest.raises(SignatureError):
		verify_detached(PAYLOAD + b" ", signature, [public_key])


def test_foreign_key_is_rejected():
	_public_key, private_key, key_id = generate_key()
	other_public, _other_private, _other_id = generate_key()
	signature = sign(PAYLOAD, private_key, key_id)
	with pytest.raises(SignatureError) as error:
		verify_detached(PAYLOAD, signature, [other_public])
	assert "немає серед довірених" in str(error.value)


def test_tampered_trusted_comment_is_rejected():
	public_key, private_key, key_id = generate_key()
	signature = sign(PAYLOAD, private_key, key_id, trusted_comment="версія 1")
	spoiled = signature.replace("trusted comment: версія 1", "trusted comment: версія 99")
	with pytest.raises(SignatureError) as error:
		verify_detached(PAYLOAD, spoiled, [public_key])
	assert "коментар" in str(error.value)


def test_broken_signature_file_is_rejected():
	public_key, _private_key, _key_id = generate_key()
	with pytest.raises(SignatureError):
		verify_detached(PAYLOAD, "untrusted comment: лише коментар\n", [public_key])
