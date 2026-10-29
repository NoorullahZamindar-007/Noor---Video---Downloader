from __future__ import annotations

from ipaddress import ip_address
from urllib.parse import urlparse


SUPPORTED_HOSTS = {
    "youtube.com": "YouTube",
    "youtu.be": "YouTube",
    "instagram.com": "Instagram",
    "facebook.com": "Facebook",
    "fb.watch": "Facebook",
    "tiktok.com": "TikTok",
    "x.com": "X/Twitter",
    "twitter.com": "X/Twitter",
    "vimeo.com": "Vimeo",
}


def _is_non_public_host(host: str) -> bool:
    """Reject local or non-routable hosts; this tool fetches public media only."""
    # DNS treats a trailing dot as the same name, so "localhost." and
    # "0.0.0.0." must be rejected too: without stripping it, those
    # hosts sailed past this check and reached yt-dlp as local URLs.
    host = host.lower().removeprefix("www.").rstrip(".")
    if host in {"localhost", "0.0.0.0"}:
        return True
    try:
        ip = ip_address(host)
    except ValueError:
        return False
    return (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
    )


def host_resolves_to_non_public(host: str) -> bool:
    """True if the host resolves to any non-public address, or cannot be resolved.

    validate_url() only inspects the literal host string, so a
    public-looking hostname whose DNS points at 127.0.0.1 (or any private
    range — attacker-controlled DNS / DNS rebinding) would sail through
    it and reach yt-dlp. Call this from the download/info paths only —
    NOT from validate_url(), which runs on every keystroke in the URL box.
    """
    import socket

    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror:
        return True
    for _family, _type, _proto, _canon, sockaddr in infos:
        if _is_non_public_host(sockaddr[0]):
            return True
    return False


def validate_url(url: str) -> tuple[bool, str]:
    # Callers pass form input straight through; a None/empty value used to
    # crash here with AttributeError instead of a clean validation error.
    if not isinstance(url, str) or not url.strip():
        return False, "Enter a valid public http(s) media URL."
    parsed = urlparse(url.strip())
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return False, "Enter a valid public http(s) media URL."
    if parsed.username or parsed.password:
        # Never hand embedded credentials to yt-dlp; they would be sent to
        # the media host (and possibly logged) as part of the request.
        return False, "URLs must not contain a username or password."
    if _is_non_public_host(parsed.hostname or ""):
        return False, "Local or private URLs are not supported."
    return True, ""


def detect_platform(url: str) -> str:
    # DNS treats a trailing dot as the same name, so strip it like
    # _is_non_public_host does: without this, "youtube.com." showed as
    # "Other yt-dlp supported site" even though the URL validates fine.
    host = (urlparse(url.strip()).hostname or "").lower().removeprefix("www.").rstrip(".")
    for domain, platform in SUPPORTED_HOSTS.items():
        if host == domain or host.endswith(f".{domain}"):
            return platform
    return "Other yt-dlp supported site" if host else "-"


if __name__ == "__main__":
    assert validate_url("https://youtu.be/abc")[0]
    assert not validate_url("https://user:secret@youtube.com/watch?v=abc")[0]
    assert not validate_url("not a url")[0]
    assert not validate_url("http://127.0.0.1/video")[0]
    assert not validate_url("http://localhost./video")[0]
    assert not validate_url("http://0.0.0.0./video")[0]
    assert not validate_url("http://[::1]/video")[0]
    assert not validate_url("http://192.168.1.10/video")[0]
    assert detect_platform("https://www.instagram.com/reel/abc/") == "Instagram"
    assert detect_platform("https://www.youtube.com./watch?v=abc") == "YouTube"
    assert detect_platform("https://youtu.be./abc") == "YouTube"
