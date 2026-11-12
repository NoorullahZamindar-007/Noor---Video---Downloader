"""Tests for utils.py — filename sanitising, formatting, atomic JSON
writes and partial-file cleanup.

These were previously only covered by `__main__` assert blocks that run
only when the file is executed directly, never in CI or via pytest.
"""

from utils import (
    cleanup_partial_files,
    coerce_dict,
    coerce_list,
    format_bytes,
    format_duration,
    format_eta,
    get_quality_label,
    get_unique_output_template,
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


def test_format_eta():
    assert format_eta(-10) == "-"
    assert format_eta(90) == "1:30"


def test_get_quality_label():
    assert get_quality_label("Audio only MP3") == "audio-mp3"
    assert get_quality_label("1080p") == "1080p"
    assert get_quality_label("Best video") == "best"


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
