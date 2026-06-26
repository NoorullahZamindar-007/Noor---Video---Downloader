from __future__ import annotations

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


def validate_url(url: str) -> tuple[bool, str]:
    parsed = urlparse(url.strip())
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return False, "Enter a valid public http(s) media URL."
    if parsed.hostname in {"localhost", "127.0.0.1", "0.0.0.0"}:
        return False, "Local or private URLs are not supported."
    return True, ""


def detect_platform(url: str) -> str:
    host = (urlparse(url.strip()).hostname or "").lower().removeprefix("www.")
    for domain, platform in SUPPORTED_HOSTS.items():
        if host == domain or host.endswith(f".{domain}"):
            return platform
    return "Other yt-dlp supported site" if host else "-"


if __name__ == "__main__":
    assert validate_url("https://youtu.be/abc")[0]
    assert not validate_url("not a url")[0]
    assert detect_platform("https://www.instagram.com/reel/abc/") == "Instagram"
