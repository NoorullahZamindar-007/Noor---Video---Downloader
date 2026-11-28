"""Tests for utils.py — filename sanitising, formatting, atomic JSON
writes and partial-file cleanup.

These were previously only covered by `__main__` assert blocks that run
only when the file is executed directly, never in CI or via pytest.
"""

import pytest

from utils import (
    _has_final_file,
    cleanup_partial_files,
    coerce_dict,
    coerce_list,
    ensure_folder,
    find_tool,
    format_bytes,
    format_duration,
    format_eta,
    get_quality_label,
    get_unique_output_template,
    is_partial_file,
    read_json,
    sanitize_filename,
    write_json,
)


def test_sanitize_filename():
    assert sanitize_filename('bad<>:"/\\|?*name') == "bad_name"
    assert sanitize_filename(None) == "download"
    assert sanitize_filename(12345) == "12345"
    assert sanitize_filename("") == "download"
    assert sanitize_filename("a" * 200) == "a" * 160


def test_format_duration():
    assert format_duration(-90) == "Unknown"
    assert format_duration(float("nan")) == "Unknown"
    assert format_duration(float("inf")) == "Unknown"
    assert format_duration("not-a-number") == "Unknown"
    assert format_duration(90) == "1:30"
    assert format_duration(0) == "Unknown"
    assert format_duration(None) == "Unknown"


def test_format_bytes():
    assert format_bytes(-5) == "-"
    assert format_bytes(float("nan")) == "-"
    assert format_bytes(2048) == "2.0 KB"
    assert format_bytes(500) == "500.0 B"
    # An infinite or missing size is not a size: without these guards
    # it used to render as "inf B" (or crash on None) instead of "-".
    assert format_bytes(float("inf")) == "-"
    assert format_bytes(float("-inf")) == "-"
    assert format_bytes(None) == "-"


def test_format_eta():
    assert format_eta(-10) == "-"
    assert format_eta(90) == "1:30"


def test_get_quality_label():
    assert get_quality_label("Audio only MP3") == "audio-mp3"
    assert get_quality_label("1080p") == "1080p"
    assert get_quality_label("Best video") == "best"
    # An unknown quality is not one of the presets: it is sanitised
    # and lowercased instead of crashing, and an empty/garbage label
    # falls back to "download" rather than producing an empty label.
    assert get_quality_label("Custom 4K") == "custom 4k"
    assert get_quality_label("") == "download"
    assert get_quality_label("???") == "download"


def test_coerce_dict_and_list():
    assert coerce_dict({"a": 1}) == {"a": 1}
    assert coerce_dict(["not", "a", "dict"]) == {}
    assert coerce_dict(None) == {}
    assert coerce_list([1, 2]) == [1, 2]
    assert coerce_list({"a": 1}) == []
    assert coerce_list(None) == []


def test_write_json_round_trips_and_leaves_no_temp_files(tmp_path):
    target = tmp_path / "sub" / "settings.json"
    write_json(target, {"a": 1})
    assert read_json(target, {}) == {"a": 1}
    write_json(target, {"b": [1, 2]})
    assert read_json(target, {}) == {"b": [1, 2]}
    leftovers = [
        f.name for f in target.parent.iterdir() if f.name.startswith(".settings.json.")
    ]
    assert not leftovers


def test_read_json_falls_back_on_non_utf8_bytes(tmp_path):
    # A settings/history file with invalid UTF-8 bytes used to raise
    # UnicodeDecodeError out of read_json — and the app reads its
    # settings at startup, so garbage bytes crashed the whole app
    # instead of falling back to defaults like corrupt JSON does.
    target = tmp_path / "settings.json"
    target.write_bytes(b"\xff\xfe not utf-8 \x80\x81")
    assert read_json(target, {"fallback": True}) == {"fallback": True}


def test_write_json_tolerates_unwritable_location(tmp_path):
    # When the settings/history folder cannot be created (here its
    # parent path is a file), write_json used to raise out of the UI
    # action that triggered the save, so e.g. clicking Download did
    # nothing but print a traceback. Persistence is best-effort: the
    # save is skipped and the action goes ahead.
    blocker = tmp_path / "blocker"
    blocker.write_text("not a folder")
    write_json(blocker / "settings.json", {"a": 1})
    assert read_json(blocker / "settings.json", {}) == {}


@pytest.mark.parametrize(
    "name, expected",
    [
        ("video.mp4.part", True),
        ("video.mp4.ytdl", True),
        ("video.mp4.temp", True),
        ("video.mp4.tmp", True),
        ("video.mp4.part-Frag0", True),
        ("video.mp4.part-Frag12", True),
        ("video.mp4", False),
        ("video.mp3", False),
        # A finished file whose title contains ".part" is not a partial:
        # the old ".part" substring check flagged these, so _final_path
        # reported a successful download as missing.
        ("S01E01.part1 [best].mp4", False),
        ("My Video.part2 [720p].mp4", False),
        ("video.ytdl.mp4", False),
    ],
)
def test_is_partial_file(name, expected):
    from pathlib import Path

    assert is_partial_file(Path(name)) == expected


def test_cleanup_partial_files_removes_partials_only(tmp_path):
    base = "My Video [best]"
    (tmp_path / f"{base}.mp4.part").write_text("partial")
    (tmp_path / f"{base}.mp4.ytdl").write_text("partial")
    (tmp_path / f"{base}.mp4").write_text("finished")
    (tmp_path / "Other Video [best].mp4.part").write_text("unrelated")

    cleanup_partial_files(tmp_path, base)

    assert not (tmp_path / f"{base}.mp4.part").exists()
    assert not (tmp_path / f"{base}.mp4.ytdl").exists()
    assert (tmp_path / f"{base}.mp4").exists()
    assert (tmp_path / "Other Video [best].mp4.part").exists()


def test_cleanup_partial_files_tolerates_missing_folder(tmp_path):
    # Cleanup runs inside error handlers: it must never raise.
    cleanup_partial_files(tmp_path / "no-such-folder", "Video [best]")


def test_get_unique_output_template_avoids_existing_files(tmp_path):
    (tmp_path / "My Video [best].mp4").write_text("existing")
    template, base = get_unique_output_template(tmp_path, "My Video", "best")

    assert base == "My Video [best] (1)"
    assert template.endswith("My Video [best] (1).%(ext)s")


def test_has_final_file_tolerates_unreadable_folder(tmp_path):
    # iterdir() raises OSError when the path is a file, not a folder
    # (or the folder lost its permissions): _has_final_file must treat
    # it as "no finished file" and let the download fail later with
    # the real error, instead of escaping as a raw OSError. The same
    # guard already exists in cleanup_partial_files and _final_path.
    not_a_folder = tmp_path / "not-a-folder"
    not_a_folder.write_text("x")
    assert _has_final_file(not_a_folder, "video") is False
    # And a folder holding a finished file still reports True.
    (tmp_path / "video [best].mp4").write_text("finished")
    assert _has_final_file(tmp_path, "video [best]") is True


def test_find_tool_skips_winget_scan_off_windows(monkeypatch):
    import os
    import pathlib

    import utils

    # The WinGet Links/Packages scan is Windows-only: with LOCALAPPDATA
    # unset, Path("") used to resolve to the working directory and the
    # recursive glob walked the whole tree looking for "<name>.exe".
    monkeypatch.setattr(os, "name", "posix")
    monkeypatch.delenv("LOCALAPPDATA", raising=False)
    monkeypatch.setattr(utils, "which", lambda name: None)

    def _forbidden_glob(self, pattern):
        raise AssertionError("WinGet glob must not run off Windows")

    monkeypatch.setattr(pathlib.Path, "glob", _forbidden_glob)
    assert find_tool("definitely-not-a-tool-xyz") is None


def test_find_tool_finds_winget_link_on_windows(monkeypatch, tmp_path):
    import os

    import utils

    # Patch os inside utils only: patching the real os.name to "nt" would
    # also flip pathlib.Path to WindowsPath, which cannot instantiate on
    # a POSIX test runner. The stub delegates everything except the name.
    class _FakeOs:
        def __init__(self, name):
            self.name = name

        def __getattr__(self, attr):
            return getattr(os, attr)

    monkeypatch.setattr(utils, "os", _FakeOs("nt"))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.setattr(utils, "which", lambda name: None)
    links = tmp_path / "Microsoft" / "WinGet" / "Links"
    links.mkdir(parents=True)
    target = links / "ffmpeg.exe"
    target.write_text("fake")
    assert find_tool("ffmpeg") == str(target)


def test_find_tool_returns_none_on_windows_without_localappdata(monkeypatch):
    import os
    import pathlib

    import utils

    class _FakeOs:
        def __init__(self, name):
            self.name = name

        def __getattr__(self, attr):
            return getattr(os, attr)

    monkeypatch.setattr(utils, "os", _FakeOs("nt"))
    monkeypatch.delenv("LOCALAPPDATA", raising=False)
    monkeypatch.setattr(utils, "which", lambda name: None)

    def _forbidden_glob(self, pattern):
        raise AssertionError("glob must not run without LOCALAPPDATA")

    monkeypatch.setattr(pathlib.Path, "glob", _forbidden_glob)
    assert find_tool("ffmpeg") is None


def test_ensure_folder_creates_nested_folders(tmp_path):
    target = tmp_path / "a" / "b"
    assert ensure_folder(target) == target
    assert target.is_dir()
    # Idempotent: an existing folder is fine.
    assert ensure_folder(target) == target


def test_ensure_folder_reports_clear_error_when_path_is_a_file(tmp_path):
    # The download folder setting can point at an existing file: mkdir
    # then raises a bare "[Errno 17] File exists" OSError, which the UI
    # showed verbatim. The error must name the folder that could not be
    # created instead.
    target = tmp_path / "not-a-folder"
    target.write_text("x", encoding="utf-8")
    with pytest.raises(OSError, match="Could not create folder"):
        ensure_folder(target)
