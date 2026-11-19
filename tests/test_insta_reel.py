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
