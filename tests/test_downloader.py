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
        downloader_module, "host_resolves_to_non_public", lambda host: False
    )

    with pytest.raises(RuntimeError, match="could not be found"):
        VideoDownloader().download(
            "https://www.youtube.com/watch?v=abc",
            tmp_path,
            "Best video",
            progress=lambda status: None,
        )

    assert not (tmp_path / "Test Video [best].mp4.part").exists()
