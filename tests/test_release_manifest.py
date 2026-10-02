"""Юніт-тести перевірки релізного маніфесту: два підписи з трьох і прив'язка до коміту."""

import json

import pytest

from tests.fixtures.build_package import generate_key, sign
from tools import release_manifest

COMMIT = "a" * 40


@pytest.fixture
def signers(monkeypatch):
	keys = [generate_key() for _ in range(3)]
	monkeypatch.setattr(release_manifest.keys_module, "TRUSTED_KEYS", [k[0] for k in keys])
	monkeypatch.setattr(release_manifest, "tag_commit", lambda tag: COMMIT)
	return keys


def write(directory, signers, commit=COMMIT, tag="v0.1.0"):
	payload = json.dumps({"type": release_manifest.MANIFEST_TYPE, "tag": tag, "commit": commit, "version": "0.1.0"})
	(directory / "release-manifest.json").write_text(payload)
	for number, (_public, private, key_id) in enumerate(signers, start=1):
		(directory / f"release-manifest.json.{number}.minisig").write_text(sign(payload.encode(), private, key_id))


def test_two_signatures_pass(tmp_path, signers):
	write(tmp_path, signers[:2])
	assert "підписано 2" in release_manifest.verify("v0.1.0", tmp_path)


def test_one_signature_is_not_enough(tmp_path, signers):
	write(tmp_path, signers[:1])
	with pytest.raises(SystemExit, match="Підписів 1, потрібно 2"):
		release_manifest.verify("v0.1.0", tmp_path)


def test_manifest_for_other_commit_is_refused(tmp_path, signers):
	write(tmp_path, signers[:2], commit="b" * 40)
	with pytest.raises(SystemExit, match="Коміт тега"):
		release_manifest.verify("v0.1.0", tmp_path)


def test_foreign_key_does_not_count(tmp_path, signers):
	write(tmp_path, [signers[0], generate_key()])
	with pytest.raises(SystemExit, match="Підписів 1"):
		release_manifest.verify("v0.1.0", tmp_path)
