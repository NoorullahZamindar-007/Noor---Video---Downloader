"""Tests for validators.py — the SSRF guards and URL/platform checks.

These were previously only covered by `__main__` assert blocks that run
only when the file is executed directly, never in CI or via pytest, so a
regression in e.g. _is_non_public_host would have shipped silently.
"""

import socket

import pytest

from validators import (
    detect_platform,
    host_resolves_to_non_public,
    resolve_host_status,
    validate_url,
)


@pytest.mark.parametrize(
    "url",
    [
        "https://youtu.be/abc",
        "https://www.youtube.com/watch?v=abc",
        "https://www.instagram.com/reel/abc/",
    ],
)
def test_validate_url_accepts_public_media_urls(url):
    assert validate_url(url) == (True, "")


@pytest.mark.parametrize(
    "url",
    [
        None,
        "",
        "   ",
        "not a url",
        "http://:8080/x",
        "https://user:secret@youtube.com/watch?v=abc",
        "http://127.0.0.1/video",
        "http://localhost./video",
        "http://0.0.0.0./video",
        "http://[::1]/video",
        "http://192.168.1.10/video",
        "http://[::1/video",
        "https://[256.256.256.256]/x",
        "ftp://youtube.com/watch?v=abc",
    ],
)
def test_validate_url_rejects_bad_or_private_urls(url):
    valid, message = validate_url(url)
    assert not valid
    assert message


@pytest.mark.parametrize(
    "url, expected",
    [
        ("https://www.instagram.com/reel/abc/", "Instagram"),
        ("https://www.youtube.com./watch?v=abc", "YouTube"),
        ("https://youtu.be./abc", "YouTube"),
        ("https://vimeo.com/123", "Vimeo"),
        ("https://example.com/video", "Other yt-dlp supported site"),
        ("http://[::1/video", "-"),
        (None, "-"),
        ("", "-"),
    ],
)
def test_detect_platform(url, expected):
    assert detect_platform(url) == expected


def test_host_resolves_to_non_public_when_dns_points_private(monkeypatch):
    # A public-looking hostname whose DNS points at 127.0.0.1 (DNS
    # rebinding) must be rejected even though the literal host is fine.
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda host, port: [(socket.AF_INET, 0, 0, "", ("127.0.0.1", 0))],
    )
    assert host_resolves_to_non_public("example.com") is True


def test_host_resolves_to_non_public_when_dns_points_public(monkeypatch):
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda host, port: [(socket.AF_INET, 0, 0, "", ("93.184.216.34", 0))],
    )
    assert host_resolves_to_non_public("example.com") is False


def test_host_resolves_to_non_public_when_dns_fails(monkeypatch):
    def _boom(host, port):
        raise socket.gaierror("Name or service not known")

    monkeypatch.setattr(socket, "getaddrinfo", _boom)
    assert host_resolves_to_non_public("nonexistent.invalid") is True


def test_resolve_host_status_public_when_dns_points_public(monkeypatch):
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda host, port: [(socket.AF_INET, 0, 0, "", ("93.184.216.34", 0))],
    )
    assert resolve_host_status("example.com") == "public"


def test_resolve_host_status_non_public_when_dns_points_private(monkeypatch):
    # A public-looking hostname whose DNS points at 127.0.0.1 must be
    # reported as non-public, not as unresolvable.
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda host, port: [(socket.AF_INET, 0, 0, "", ("127.0.0.1", 0))],
    )
    assert resolve_host_status("example.com") == "non-public"


def test_resolve_host_status_unresolvable_when_dns_fails(monkeypatch):
    # A host that fails to resolve is a third case, not a private one:
    # it used to be lumped in with private hosts and misreported as
    # "Local or private URLs are not supported".
    def _boom(host, port):
        raise socket.gaierror("Name or service not known")

    monkeypatch.setattr(socket, "getaddrinfo", _boom)
    assert resolve_host_status("nonexistent.invalid") == "unresolvable"
