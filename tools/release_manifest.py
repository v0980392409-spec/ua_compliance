"""Релізний маніфест: зібрати для підпису й перевірити підписи.

Маніфест прив'язує тег до коміту й версії застосунку. Підписують його двоє з трьох
ключів, закріплених у `ua_compliance/packages/keys.py`, — тими самими, що й пакети
даних. Секретні ключі в CI не потрапляють: підпис ставиться офлайн, а CI лише
перевіряє, перш ніж опублікувати реліз.

    python tools/release_manifest.py build v0.1.0 > release-manifest.json
    python tools/release_manifest.py verify v0.1.0 <каталог з маніфестом і .minisig>

Друга команда — і для клієнта перед оновленням: запускати в копії репозиторію,
з якої ставитиметься застосунок, — коміт тега звіряється з маніфестом.
"""

import json
import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from ua_compliance.packages import keys as keys_module  # noqa: E402
from ua_compliance.packages.signature import SignatureError, verify_detached  # noqa: E402

MANIFEST_NAME = "release-manifest.json"
MANIFEST_TYPE = "ua-compliance-release"


def app_version():
	text = (ROOT / "ua_compliance" / "__init__.py").read_text()
	return text.split("__version__", 1)[1].split('"')[1]


def tag_commit(tag):
	try:
		return subprocess.check_output(
			["git", "rev-list", "-n", "1", tag], cwd=ROOT, text=True, stderr=subprocess.DEVNULL
		).strip()
	except subprocess.CalledProcessError:
		raise SystemExit(f"Тега {tag} у цій копії репозиторію немає (git fetch --tags?)") from None


def build(tag):
	version = app_version()
	if tag != f"v{version}":
		raise SystemExit(f"Тег {tag} не відповідає версії застосунку {version}")
	manifest = {
		"type": MANIFEST_TYPE,
		"tag": tag,
		"commit": tag_commit(tag),
		"version": version,
	}
	return json.dumps(manifest, ensure_ascii=False, indent=1) + "\n"


def verify(tag, directory):
	directory = pathlib.Path(directory)
	manifest_bytes = (directory / MANIFEST_NAME).read_bytes()
	manifest = json.loads(manifest_bytes)
	if manifest.get("type") != MANIFEST_TYPE:
		raise SystemExit("Маніфест не того виду")
	if manifest.get("tag") != tag:
		raise SystemExit(f"Маніфест виписано на тег {manifest.get('tag')}, а не на {tag}")
	if manifest.get("commit") != tag_commit(tag):
		raise SystemExit("Коміт тега не збігається з підписаним у маніфесті")

	trusted = keys_module.trusted_keys()
	if not trusted:
		raise SystemExit("Ключі підпису ще не закріплені в коді")
	key_ids = set()
	for path in sorted(directory.glob(f"{MANIFEST_NAME}*.minisig")):
		try:
			key_ids.add(verify_detached(manifest_bytes, path.read_text(), trusted))
		except SignatureError:
			continue
	if len(key_ids) < keys_module.THRESHOLD:
		raise SystemExit(f"Підписів {len(key_ids)}, потрібно {keys_module.THRESHOLD}")
	return f"Реліз {tag} підписано {len(key_ids)} ключами, коміт {manifest['commit'][:12]}"


if __name__ == "__main__":
	if len(sys.argv) == 3 and sys.argv[1] == "build":
		sys.stdout.write(build(sys.argv[2]))
	elif len(sys.argv) == 4 and sys.argv[1] == "verify":
		print(verify(sys.argv[2], sys.argv[3]))
	else:
		raise SystemExit(__doc__)
