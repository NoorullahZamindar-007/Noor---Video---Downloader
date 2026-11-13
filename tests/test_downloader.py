"""Tests for downloader.py — the download flow with a stubbed yt-dlp."""

from types import SimpleNamespace

import pytest

import downloader as downloader_module
from downloader import VideoDownloader


class _FakeDownloadError(Exception):
    pass


class _FakeYoutubeDL:
    """Minimal yt-dlp stand-in: metadata fetch succeeds, the download
    "finishes" but produces no findable file — only a .part leftover."""

    def __init__(self, options, output_dir):
        self.output_dir = output_dir

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def extract_info(self, url, download=False):
        if not download:
            return {"title": "Test Video"}
        part = self.output_dir / "Test Video [best].mp4.part"
        part.write_text("partial download")
        return {}


def _fake_ytdlp(output_dir):
    return SimpleNamespace(
        YoutubeDL=lambda options: _FakeYoutubeDL(options, output_dir),
        utils=SimpleNamespace(DownloadError=_FakeDownloadError),
    )


def test_failed_final_path_resolution_cleans_up_partials(monkeypatch, tmp_path):
    # A download that "finished" but produced no findable file used to
    # leave its .part files behind: the None-check and _final_path call
    # sat outside the try that cleans up on failure.
    monkeypatch.setattr(
        VideoDownloader, "_yt_dlp", staticmethod(lambda: _fake_ytdlp(tmp_path))
    )
    monkeypatch.setattr(
        downloader_module, "resolve_host_status", lambda host: "public"
    )

    with pytest.raises(RuntimeError, match="could not be found"):
        VideoDownloader().download(
            "https://www.youtube.com/watch?v=abc",
            tmp_path,
            "Best video",
            progress=lambda status: None,
        )

    assert not (tmp_path / "Test Video [best].mp4.part").exists()


def test_unresolvable_host_reports_dns_failure_not_private(monkeypatch):
    # A host that fails to resolve used to be reported as "Local or
    # private URLs are not supported", which blamed the wrong thing.
    monkeypatch.setattr(
        downloader_module, "resolve_host_status", lambda host: "unresolvable"
    )

    with pytest.raises(ValueError, match="Could not resolve the host name"):
        VideoDownloader().get_info("https://nonexistent.invalid/watch?v=abc")


def test_non_public_host_still_reports_private(monkeypatch):
    monkeypatch.setattr(
        downloader_module, "resolve_host_status", lambda host: "non-public"
    )

    with pytest.raises(ValueError, match="Local or private URLs are not supported"):
        VideoDownloader().get_info("https://example.com/watch?v=abc")


def test_download_with_unresolvable_host_reports_dns_failure(monkeypatch, tmp_path):
    monkeypatch.setattr(
        downloader_module, "resolve_host_status", lambda host: "unresolvable"
    )

    with pytest.raises(ValueError, match="Could not resolve the host name"):
        VideoDownloader().download(
            "https://nonexistent.invalid/watch?v=abc",
            tmp_path,
            "Best video",
            progress=lambda status: None,
        )


class _FakeYoutubeDLMetadataError:
    """yt-dlp stand-in whose metadata fetch raises a raw (non-DownloadError)
    exception, e.g. a socket timeout or an extractor bug."""

    def __init__(self, options):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def extract_info(self, url, download=False):
        raise RuntimeError("boom")


def _fake_ytdlp_metadata_error():
    return SimpleNamespace(
        YoutubeDL=lambda options: _FakeYoutubeDLMetadataError(options),
        utils=SimpleNamespace(DownloadError=_FakeDownloadError),
    )


def test_get_info_wraps_unexpected_metadata_error(monkeypatch):
    # yt-dlp wraps most failures in DownloadError, but a raw exception
    # used to escape with no context — the UI showed e.g. bare "timed out".
    monkeypatch.setattr(
        VideoDownloader, "_yt_dlp", staticmethod(lambda: _fake_ytdlp_metadata_error())
    )
    monkeypatch.setattr(
        downloader_module, "resolve_host_status", lambda host: "public"
    )

    with pytest.raises(RuntimeError, match="Could not read video information"):
        VideoDownloader().get_info("https://www.youtube.com/watch?v=abc")


def test_download_wraps_unexpected_metadata_error(monkeypatch, tmp_path):
    monkeypatch.setattr(
        VideoDownloader, "_yt_dlp", staticmethod(lambda: _fake_ytdlp_metadata_error())
    )
    monkeypatch.setattr(
        downloader_module, "resolve_host_status", lambda host: "public"
    )

    with pytest.raises(RuntimeError, match="Could not read video information"):
        VideoDownloader().download(
            "https://www.youtube.com/watch?v=abc",
            tmp_path,
            "Best video",
            progress=lambda status: None,
        )
