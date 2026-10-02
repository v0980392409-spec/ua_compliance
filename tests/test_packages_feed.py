"""Юніт-тести каналу роздачі: що забирати з переліку релізів і як не захлинутися.

Без мережі й без платформи: відповідь сервера підміняється.
"""

import pytest

from ua_compliance.packages import feed


def release(tag, published, assets, draft=False, prerelease=False):
	return {
		"tag_name": tag,
		"published_at": published,
		"draft": draft,
		"prerelease": prerelease,
		"assets": [
			{"name": name, "browser_download_url": f"https://example.test/{tag}/{name}", "size": 10}
			for name in assets
		],
	}


RELEASES = [
	# GitHub віддає новіші першими.
	release("parameters-20261102", "2026-11-02T08:00:00Z", ["ua-params-20261102.zip"]),
	release("parameters-20261101", "2026-11-01T08:00:00Z", ["ua-params-20261101.zip", "README.md"]),
	release("parameters-20261103", "2026-11-03T08:00:00Z", ["draft.zip"], draft=True),
	release("parameters-20261104", "2026-11-04T08:00:00Z", ["pre.zip"], prerelease=True),
]


def test_old_first_and_only_zip():
	"""Старший пакет іде першим: інакше перевірка відкине його як не новіший."""
	picked = feed.pick_new_assets(RELEASES, set())
	assert [item["name"] for item in picked] == ["ua-params-20261101.zip", "ua-params-20261102.zip"]


def test_drafts_and_prereleases_are_not_packages():
	names = {item["name"] for item in feed.pick_new_assets(RELEASES, set())}
	assert "draft.zip" not in names and "pre.zip" not in names


def test_known_sources_are_not_taken_twice():
	known = {"https://example.test/parameters-20261101/ua-params-20261101.zip"}
	picked = feed.pick_new_assets(RELEASES, known)
	assert [item["name"] for item in picked] == ["ua-params-20261102.zip"]


class FakeResponse:
	def __init__(self, status, body=None, chunks=()):
		self.status_code = status
		self._body = body
		self._chunks = chunks

	def json(self):
		if isinstance(self._body, Exception):
			raise self._body
		return self._body

	def iter_content(self, chunk_size):
		yield from self._chunks


@pytest.mark.parametrize(
	"response, reason",
	[
		(FakeResponse(404, {"message": "Not Found"}), "відповів 404"),
		# Сервер відповідає 200 з тілом помилки — перевіряємо форму, а не код.
		(FakeResponse(200, {"message": "API rate limit exceeded"}), "не перелік релізів"),
		(FakeResponse(200, ValueError("bad")), "не JSON"),
	],
)
def test_feed_refuses_wrong_answer(monkeypatch, response, reason):
	monkeypatch.setattr(feed.requests, "get", lambda *a, **k: response)
	with pytest.raises(feed.FeedError, match=reason):
		feed.fetch_releases("https://example.test/releases")


def test_oversized_package_is_not_downloaded(monkeypatch):
	monkeypatch.setattr(feed, "MAX_PACKAGE_BYTES", 5)
	monkeypatch.setattr(feed.requests, "get", lambda *a, **k: FakeResponse(200, chunks=[b"abc", b"def"]))
	with pytest.raises(feed.FeedError, match="завеликий"):
		feed.download({"name": "big.zip", "url": "https://example.test/big.zip", "size": 0})
