"""Tests for 5_insta_reel.py — the standalone Instagram reel downloader.

The reel URL check had no test coverage at all, so a valid link shape
could be rejected (or an invalid one accepted) without anyone noticing.

The module name starts with a digit, so it cannot be imported with a
plain import statement; importlib handles it. Importing the module does
not open a window: the GUI only runs under `__main__`.
"""

import importlib

import pytest

reel = importlib.import_module("5_insta_reel")
_is_instagram_reel_url = reel._is_instagram_reel_url


@pytest.mark.parametrize(
    "url",
    [
        "https://www.instagram.com/reel/ABC123/",
        "https://instagram.com/reel/ABC123",
        "https://instagr.am/reel/ABC123/",
        # Mobile-web links use a subdomain; only the bare host and www
        # were accepted, so a reel shared from a phone browser failed
        # with "Enter a public Instagram reel URL".
        "https://m.instagram.com/reel/ABC123/",
        "http://www.instagram.com/reel/ABC123/",
    ],
)
def test_accepts_instagram_reel_urls(url):
    assert _is_instagram_reel_url(url) is True


@pytest.mark.parametrize(
    "url",
    [
        "",
        "not a url",
        # Not a reel: a post, a profile, or another site entirely.
        "https://instagram.com/p/ABC123/",
        "https://instagram.com/someuser/",
        "https://example.com/reel/ABC123/",
        # A lookalike host is not Instagram.
        "https://notinstagram.com/reel/ABC123/",
        "https://instagram.com.evil.example/reel/ABC123/",
        # A non-http(s) scheme has no requests adapter for it.
        "ftp://instagram.com/reel/ABC123/",
        # Malformed URL that urlparse rejects.
        "http://[::1/reel/ABC123/",
    ],
)
def test_rejects_non_reel_urls(url):
    assert _is_instagram_reel_url(url) is False


def test_extract_playable_url_decodes_escapes():
    # Instagram's page JSON escapes forward slashes and & as \/ and
    # \u0026; both must come back as plain characters in the media URL.
    page = r'{"playable_url":"https:\/\/scontent.cdninstagram.com\/v\/abc.mp4?x=1\u0026y=2"}'
    assert (
        reel._extract_playable_url(page)
        == "https://scontent.cdninstagram.com/v/abc.mp4?x=1&y=2"
    )


def test_extract_playable_url_keeps_escaped_quote_in_url():
    # An escaped quote inside the JSON string used to end the old [^"]+
    # match early, truncating the URL so it failed the media-host check.
    page = r'{"playable_url":"https://scontent.cdninstagram.com/v/a.mp4?x=1\"y=2"}'
    assert (
        reel._extract_playable_url(page)
        == 'https://scontent.cdninstagram.com/v/a.mp4?x=1"y=2'
    )


def test_extract_playable_url_returns_none_without_match():
    assert reel._extract_playable_url('{"no_video_here":true}') is None
    assert reel._extract_playable_url("") is None


def test_extract_playable_url_allows_whitespace_around_colon():
    # JSON allows whitespace around the colon; a re-spaced page embed
    # used to return None ("Cannot find video URL") even though the
    # URL was right there in the page.
    page = '{"playable_url" : "https://scontent.cdninstagram.com/v/a.mp4"}'
    assert (
        reel._extract_playable_url(page)
        == "https://scontent.cdninstagram.com/v/a.mp4"
    )


class _FakeOutput:
    """Stand-in for the Tk text widget: records what the downloader shows."""

    def __init__(self):
        self.text = ""

    def delete(self, *args):
        self.text = ""

    def insert(self, index, text):
        self.text += text


class _FakeResponse:
    def __init__(self, body, status_code=200, content_type="text/html", url=""):
        self._body = body
        self.status_code = status_code
        self.headers = {"Content-Type": content_type}
        # requests sets .url to the final URL after following redirects;
        # the download code checks it, so the fake must carry it too.
        self.url = url

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def raise_for_status(self):
        pass

    def iter_content(self, chunk_size=65536):
        yield self._body


def _no_fetch(*args, **kwargs):
    raise AssertionError("requests.get must not be called")


def test_reel_page_not_fetched_when_host_resolves_private(monkeypatch):
    # The page fetch used to run with no host check at all: a poisoned
    # or rebinding resolver pointing instagram.com at a LAN address
    # would have the app GET an internal address. Refuse before any
    # request goes out.
    monkeypatch.setattr(reel, "resolve_host_status", lambda host: "non-public")
    monkeypatch.setattr(reel.requests, "get", _no_fetch)
    output = _FakeOutput()

    reel.download_instagram_reel("https://www.instagram.com/reel/ABC123/", output)

    assert "private address" in output.text


def test_reel_page_not_fetched_when_host_unresolvable(monkeypatch):
    # Same refusal, but reported as a DNS/connection problem rather
    # than a private host: the usual cause is simply no internet.
    monkeypatch.setattr(reel, "resolve_host_status", lambda host: "unresolvable")
    monkeypatch.setattr(reel.requests, "get", _no_fetch)
    output = _FakeOutput()

    reel.download_instagram_reel("https://www.instagram.com/reel/ABC123/", output)

    assert "Could not resolve" in output.text


def test_reel_download_happy_path_with_mocked_network(monkeypatch, tmp_path):
    # The full download, with the page fetch, the media fetch and the
    # host checks all mocked: proves the new host check does not block
    # a normal public reel.
    monkeypatch.setattr(reel, "resolve_host_status", lambda host: "public")
    monkeypatch.setattr(reel, "host_resolves_to_non_public", lambda host: False)
    monkeypatch.setattr(reel, "DEFAULT_DOWNLOAD_DIR", tmp_path)
    page = (
        '{"playable_url":"https://scontent.cdninstagram.com/v/a.mp4"}'
    ).encode("utf-8")

    def fake_get(url, **kwargs):
        if "cdninstagram.com" in url:
            return _FakeResponse(b"fake video bytes", content_type="video/mp4", url=url)
        return _FakeResponse(page, url=url)

    monkeypatch.setattr(reel.requests, "get", fake_get)
    output = _FakeOutput()

    reel.download_instagram_reel("https://www.instagram.com/reel/ABC123/", output)

    assert "Reel downloaded to" in output.text
    assert (tmp_path / "ABC123.mp4").read_bytes() == b"fake video bytes"


def test_reel_page_redirect_off_instagram_is_refused(monkeypatch, tmp_path):
    # requests follows redirects silently: the host check on the pasted
    # URL does not cover where it ends up, so a redirect to another
    # host must be refused before the page body is read — and the media
    # must never be fetched.
    monkeypatch.setattr(reel, "resolve_host_status", lambda host: "public")
    monkeypatch.setattr(reel, "DEFAULT_DOWNLOAD_DIR", tmp_path)
    page = (
        '{"playable_url":"https://scontent.cdninstagram.com/v/a.mp4"}'
    ).encode("utf-8")
    fetched = []

    def fake_get(url, **kwargs):
        fetched.append(url)
        return _FakeResponse(page, url="https://evil.example/reel/ABC123/")

    monkeypatch.setattr(reel.requests, "get", fake_get)
    output = _FakeOutput()

    reel.download_instagram_reel("https://www.instagram.com/reel/ABC123/", output)

    assert "redirected" in output.text
    assert fetched == ["https://www.instagram.com/reel/ABC123/"]
    assert list(tmp_path.iterdir()) == []


def test_reel_page_redirect_within_instagram_is_allowed(monkeypatch, tmp_path):
    # Instagram itself redirects (instagram.com -> www/m.), so a
    # redirect that stays on an Instagram host must still download.
    monkeypatch.setattr(reel, "resolve_host_status", lambda host: "public")
    monkeypatch.setattr(reel, "host_resolves_to_non_public", lambda host: False)
    monkeypatch.setattr(reel, "DEFAULT_DOWNLOAD_DIR", tmp_path)
    page = (
        '{"playable_url":"https://scontent.cdninstagram.com/v/a.mp4"}'
    ).encode("utf-8")

    def fake_get(url, **kwargs):
        if "cdninstagram.com" in url:
            return _FakeResponse(b"fake video bytes", content_type="video/mp4", url=url)
        return _FakeResponse(page, url="https://m.instagram.com/reel/ABC123/")

    monkeypatch.setattr(reel.requests, "get", fake_get)
    output = _FakeOutput()

    reel.download_instagram_reel("https://www.instagram.com/reel/ABC123/", output)

    assert "Reel downloaded to" in output.text
    assert (tmp_path / "ABC123.mp4").read_bytes() == b"fake video bytes"


def test_reel_media_redirect_off_cdn_is_refused(monkeypatch, tmp_path):
    # A 302 from the CDN to an arbitrary host used to be followed and
    # written to disk (up to 2 GB). Refuse it and leave no partial file.
    monkeypatch.setattr(reel, "resolve_host_status", lambda host: "public")
    monkeypatch.setattr(reel, "host_resolves_to_non_public", lambda host: False)
    monkeypatch.setattr(reel, "DEFAULT_DOWNLOAD_DIR", tmp_path)
    page = (
        '{"playable_url":"https://scontent.cdninstagram.com/v/a.mp4"}'
    ).encode("utf-8")

    def fake_get(url, **kwargs):
        if "cdninstagram.com" in url:
            return _FakeResponse(
                b"not a video", content_type="video/mp4", url="https://evil.example/v/a.mp4"
            )
        return _FakeResponse(page, url=url)

    monkeypatch.setattr(reel.requests, "get", fake_get)
    output = _FakeOutput()

    reel.download_instagram_reel("https://www.instagram.com/reel/ABC123/", output)

    assert "redirected" in output.text
    assert list(tmp_path.iterdir()) == []
