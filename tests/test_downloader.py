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


def test_final_path_ignores_temp_sidecar(tmp_path):
    # _final_path used its own inline ".part"/".ytdl" substring check, so
    # a leftover .temp file (which the shared partial check treats as
    # partial) was returned as the finished download.
    (tmp_path / "Test Video [best].mp4.temp").write_text("temp")

    with pytest.raises(RuntimeError, match="could not be found"):
        VideoDownloader._final_path({}, tmp_path, "Test Video [best]", "best")


def test_final_path_prefers_finished_file_over_temp_sidecar(tmp_path):
    (tmp_path / "Test Video [best].mp4.temp").write_text("temp")
    finished = tmp_path / "Test Video [best].mp4"
    finished.write_text("finished")

    assert (
        VideoDownloader._final_path({}, tmp_path, "Test Video [best]", "best")
        == finished
    )


def test_final_path_finds_finished_file_with_part_in_title(tmp_path):
    # A finished file whose title contains ".part" ("S01E01.part1")
    # used to be flagged as a partial by the substring check in
    # is_partial_file, so _final_path reported a successful download
    # as missing even though the file was right there.
    finished = tmp_path / "S01E01.part1 [best].mp4"
    finished.write_text("finished")

    assert (
        VideoDownloader._final_path({}, tmp_path, "S01E01.part1 [best]", "best")
        == finished
    )


def test_final_path_ignores_malformed_requested_downloads(tmp_path):
    # A malformed requested_downloads entry (a string instead of a dict,
    # a non-string filepath) used to crash _final_path with
    # AttributeError/TypeError even though the download had succeeded.
    finished = tmp_path / "Test Video [best].mp4"
    finished.write_text("finished")

    assert VideoDownloader._final_path(
        {
            "requested_downloads": [
                "junk",
                None,
                {"filepath": 42},
                {"filepath": str(finished)},
            ],
            "filepath": 123,
        },
        tmp_path,
        "Test Video [best]",
        "best",
    ) == finished


def test_simple_formats_ignores_malformed_format_entries():
    # yt-dlp metadata is not guaranteed clean: a non-dict entry in the
    # formats list used to crash _simple_formats on .get, so the whole
    # info fetch failed instead of showing the usable qualities.
    labels = VideoDownloader._simple_formats(
        {
            "formats": [
                {"height": 720, "ext": "mp4", "vcodec": "avc1", "acodec": "mp4a"},
                "junk",
                None,
                42,
                {"height": 480, "ext": "webm", "vcodec": "vp9", "acodec": "opus"},
            ]
        }
    )

    assert labels == ["720p mp4", "480p webm"]


def test_simple_formats_returns_empty_for_non_list_formats():
    # A non-list "formats" value (a dict, a string) used to crash the
    # same loop; an empty quality list is the right fallback.
    assert VideoDownloader._simple_formats({"formats": "not-a-list"}) == []
    assert VideoDownloader._simple_formats({"formats": {"height": 720}}) == []
    assert VideoDownloader._simple_formats({}) == []


class _FakeYoutubeDLHookProgress:
    """yt-dlp stand-in that fires the progress hook with downloaded
    bytes past the reported total, then produces the finished file."""

    def __init__(self, options, output_dir, seen):
        self.options = options
        self.output_dir = output_dir
        self.seen = seen

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def extract_info(self, url, download=False):
        if not download:
            return {"title": "Test Video"}
        for hook in self.options.get("progress_hooks") or []:
            hook(
                {
                    "status": "downloading",
                    "downloaded_bytes": 1500,
                    "total_bytes": 1000,
                    "speed": 10,
                    "eta": 5,
                }
            )
            hook(
                {
                    "status": "finished",
                    "filename": str(self.output_dir / "Test Video [best].mp4"),
                }
            )
        finished = self.output_dir / "Test Video [best].mp4"
        finished.write_text("finished")
        return {"filepath": str(finished)}


def test_download_progress_percent_never_exceeds_one(monkeypatch, tmp_path):
    # total_bytes_estimate is rough: downloaded can pass it near the end
    # of a file, so the raw ratio used to exceed 1 and the bar showed
    # over 100%. The hook must clamp at the source.
    seen: list[dict] = []

    def _fake(options):
        return _FakeYoutubeDLHookProgress(options, tmp_path, seen)

    monkeypatch.setattr(
        VideoDownloader,
        "_yt_dlp",
        staticmethod(
            lambda: SimpleNamespace(
                YoutubeDL=_fake, utils=SimpleNamespace(DownloadError=_FakeDownloadError)
            )
        ),
    )
    monkeypatch.setattr(
        downloader_module, "resolve_host_status", lambda host: "public"
    )

    result = VideoDownloader().download(
        "https://www.youtube.com/watch?v=abc",
        tmp_path,
        "Best video",
        progress=lambda status: seen.append(status),
    )

    assert result == tmp_path / "Test Video [best].mp4"
    downloading = [s for s in seen if s["text"].startswith("Downloading")]
    assert downloading and downloading[0]["percent"] == 1.0
