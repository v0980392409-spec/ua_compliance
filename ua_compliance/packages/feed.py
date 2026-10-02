"""Канал роздачі: релізи окремого репозиторію даних на GitHub.

Кожен пакет — це реліз з одним zip-вкладенням. Сервер роздачі вважається
**недовіреним**: звідси береться лише архів, а довіра виникає тільки після
перевірки підписів на боці екземпляра (verify.py). Тому тут немає ні токенів,
ні власних перевірок — тільки забрати й не захлинутися.
"""

import requests

TIMEOUT = 30
# Класифікатор на 32 000 кодів важить ~2 МБ; запас на порядок, але не безмежний.
MAX_PACKAGE_BYTES = 50 * 1024 * 1024
PACKAGE_SUFFIX = ".zip"


class FeedError(Exception):
	"""Канал роздачі не відповів так, як очікувалося."""


def fetch_releases(url):
	try:
		response = requests.get(
			url,
			params={"per_page": 20},
			headers={"Accept": "application/vnd.github+json"},
			timeout=TIMEOUT,
		)
	except requests.RequestException as error:
		raise FeedError(f"Канал роздачі недоступний: {error}") from None
	if response.status_code != 200:
		raise FeedError(f"Канал роздачі відповів {response.status_code}")
	try:
		releases = response.json()
	except ValueError:
		raise FeedError("Канал роздачі повернув не JSON") from None
	# Сервер може відповісти 200 з тілом помилки — перевіряємо форму, а не код.
	if not isinstance(releases, list):
		raise FeedError("Канал роздачі повернув не перелік релізів")
	return releases


def pick_new_assets(releases, known_sources):
	"""Нові пакети з переліку релізів, від старших до новіших.

	Чернетки й попередні релізи пропускаються: пакет у каналі з'являється лише
	опублікованим релізом. Порядок важливий — перевірка відкидає версію, не новішу
	за застосовану, тому старший пакет має прийти першим.
	"""
	found = []
	for release in releases:
		if not isinstance(release, dict) or release.get("draft") or release.get("prerelease"):
			continue
		for asset in release.get("assets") or []:
			name = asset.get("name") or ""
			url = asset.get("browser_download_url")
			if not url or not name.endswith(PACKAGE_SUFFIX) or url in known_sources:
				continue
			found.append(
				{
					"tag": release.get("tag_name") or "",
					"published": release.get("published_at") or "",
					"name": name,
					"url": url,
					"size": asset.get("size") or 0,
				}
			)
	found.sort(key=lambda item: (item["published"], item["tag"], item["name"]))
	return found


def download(asset):
	if asset.get("size", 0) > MAX_PACKAGE_BYTES:
		raise FeedError(f"Пакет {asset['name']} завеликий: {asset['size']} байт")
	try:
		response = requests.get(asset["url"], timeout=TIMEOUT, stream=True)
	except requests.RequestException as error:
		raise FeedError(f"Пакет {asset['name']} не завантажено: {error}") from None
	if response.status_code != 200:
		raise FeedError(f"Пакет {asset['name']} не завантажено: відповідь {response.status_code}")
	chunks, total = [], 0
	for chunk in response.iter_content(chunk_size=65536):
		total += len(chunk)
		if total > MAX_PACKAGE_BYTES:
			raise FeedError(f"Пакет {asset['name']} завеликий: понад {MAX_PACKAGE_BYTES} байт")
		chunks.append(chunk)
	return b"".join(chunks)
