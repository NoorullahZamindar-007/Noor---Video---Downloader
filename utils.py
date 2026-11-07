from __future__ import annotations

import json
import os
import re
import subprocess
from datetime import datetime
from pathlib import Path 
from shutil import which
from typing import Any


_PARTIAL_SUFFIXES = (".part", ".ytdl", ".temp", ".tmp")


def sanitize_filename(title: str, fallback: str = "download") -> str:
    # yt-dlp metadata is not guaranteed clean: a missing title is
    # guarded by callers with `or "download"`, but a non-string title
    # (a number, for example) is truthy, so it slipped through and
    # crashed re.sub with TypeError. Coerce it instead; None has no
    # text at all, so it falls back.
    if title is None:
        return fallback
    if not isinstance(title, str):
        title = str(title)
    cleaned = re.sub(r'[<>:"/\\|?*\x00-\x1f]+', "_", title).strip(" ._")
    return (cleaned or fallback)[:160] 


safe_filename = sanitize_filename


def get_quality_label(selected_quality: str) -> str:
    labels = {
        "Best video": "best",
        "1080p": "1080p",
        "720p": "720p",
        "480p": "480p",
        "Audio only MP3": "audio-mp3",
    }
    return labels.get(selected_quality, sanitize_filename(selected_quality).lower() or "video")


def get_unique_output_template(download_folder: str | Path, title: str, quality_label: str) -> tuple[str, str]:
    folder = ensure_folder(download_folder)
    base = f"{sanitize_filename(title)} [{quality_label}]"
    candidate = base
    counter = 1
    while _has_final_file(folder, candidate):
        candidate = f"{base} ({counter})"
        counter += 1
    return str(folder / f"{candidate}.%(ext)s"), candidate


def cleanup_partial_files(download_folder: str | Path, base_filename: str) -> None:
    folder = Path(download_folder).expanduser()
    if not folder.exists():
        return
    safe_base = Path(base_filename).name
    for path in folder.iterdir():
        if path.is_file() and path.name.startswith(safe_base) and _is_partial(path):
            try:
                path.unlink()
            except OSError:
                pass


def check_ffmpeg_installed() -> bool:
    return bool(find_tool("ffmpeg"))


def _has_final_file(folder: Path, base_filename: str) -> bool:
    prefix = f"{base_filename}."
    for path in folder.iterdir():
        if path.is_file() and path.name.startswith(prefix) and not _is_partial(path):
            return True
    return False


def _is_partial(path: Path) -> bool:
    name = path.name.lower()
    return path.suffix.lower() in _PARTIAL_SUFFIXES or ".part" in name or ".ytdl" in name


def ensure_folder(path: str | Path) -> Path:
    folder = Path(path).expanduser()
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def read_json(path: Path, fallback: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return fallback

def coerce_dict(value: Any) -> dict:
    """Return *value* when it is a dict, else an empty dict.

    Settings and history files are hand-editable JSON: a wrong shape
    (a list where a dict belongs, or vice versa) used to crash the app
    at startup on .get/.insert instead of falling back to defaults.
    read_json only guards unreadable or malformed JSON, not valid JSON
    of the wrong shape.
    """
    return value if isinstance(value, dict) else {}


def coerce_list(value: Any) -> list:
    """Return *value* when it is a list, else an empty list (see coerce_dict)."""
    return value if isinstance(value, list) else []


def write_json(path: Path, data: Any) -> None:
    """Write JSON atomically so a crash cannot leave a half-written file.

    Settings and history are read with a silent fallback on corrupt JSON;
    without an atomic write, a crash mid-save would silently reset the
    user's settings and download history. The temp file + os.replace
    dance keeps the old file intact until the new one is fully written.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(data, indent=2, ensure_ascii=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        tmp.write_text(payload, encoding="utf-8")
        os.replace(tmp, path)
    finally:
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass


def now_stamp() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def format_duration(seconds: int | float | None) -> str:
    # yt-dlp metadata is not guaranteed clean: a negative, NaN, infinite,
    # or non-numeric duration used to render nonsense ("-2:30") or crash
    # with ValueError/TypeError instead of showing "Unknown".
    try:
        total = int(seconds) if seconds is not None else 0
    except (TypeError, ValueError, OverflowError):
        return "Unknown"
    if total <= 0:
        return "Unknown"
    minutes, sec = divmod(total, 60)
    hours, minutes = divmod(minutes, 60)
    return f"{hours}:{minutes:02d}:{sec:02d}" if hours else f"{minutes}:{sec:02d}"


def format_bytes(value: int | float | None) -> str:
    # Same guard as format_duration: a negative, NaN, infinite, or
    # non-numeric size used to render as "-90.0 B" or "nan B".
    try:
        size = float(value) if value is not None else 0.0
    except (TypeError, ValueError):
        return "-"
    if size <= 0 or size != size or size == float("inf"):
        return "-"
    for unit in ("B", "KB", "MB", "GB", "TB", "PB"):
        if size < 1024 or unit == "PB":
            return f"{size:.1f} {unit}"
        size /= 1024
    return "-"


def format_eta(seconds: int | float | None) -> str:
    # An ETA is a countdown, never a duration label: reuse the duration
    # guard but report an unusable value as "-" rather than "Unknown".
    if format_duration(seconds) == "Unknown":
        return "-"
    return format_duration(seconds)


def find_tool(name: str) -> str | None:
    found = which(name)
    if found:
        return found

    exe = f"{name}.exe"
    roots = [
        Path(os.getenv("LOCALAPPDATA") or "") / "Microsoft" / "WinGet" / "Links",
        Path(os.getenv("LOCALAPPDATA") or "") / "Microsoft" / "WinGet" / "Packages",
    ]
    for root in roots:
        if not root.exists():
            continue
        direct = root / exe
        if direct.exists():
            return str(direct)
        # ponytail: winget package scan only; add a user setting if portable tool paths matter later.
        for match in root.glob(f"**/{exe}"):
            return str(match)
    return None


def open_folder(path: str | Path) -> None:
    folder = ensure_folder(path)
    try:
        if os.name == "nt":
            os.startfile(folder)  # type: ignore[attr-defined]
        else:
            subprocess.Popen(["open" if os.uname().sysname == "Darwin" else "xdg-open", str(folder)])
    except OSError:
        # A minimal install may have no xdg-open (or no associated viewer);
        # that used to raise FileNotFoundError out of the button callback.
        # There is nothing useful to show without a viewer, so stay silent
        # rather than surfacing a traceback for a folder that does exist.
        pass


if __name__ == "__main__":
    assert sanitize_filename('bad<>:"/\\|?*name') == "bad_name"
    assert sanitize_filename(None) == "download"
    assert sanitize_filename(12345) == "12345"
    assert format_duration(-90) == "Unknown"
    assert format_duration(float("nan")) == "Unknown"
    assert format_duration(float("inf")) == "Unknown"
    assert format_duration("not-a-number") == "Unknown"
    assert format_duration(90) == "1:30"
    assert format_bytes(-5) == "-"
    assert format_bytes(float("nan")) == "-"
    assert format_bytes(2048) == "2.0 KB"
    assert format_eta(-10) == "-"
    assert format_eta(90) == "1:30"
    assert get_quality_label("Audio only MP3") == "audio-mp3"
    assert coerce_dict({"a": 1}) == {"a": 1}
    assert coerce_dict(["not", "a", "dict"]) == {}
    assert coerce_dict(None) == {}
    assert coerce_list([1, 2]) == [1, 2]
    assert coerce_list({"a": 1}) == []
    assert coerce_list(None) == []
    # atomic write_json: round-trips data and leaves no temp files behind
    import tempfile
    with tempfile.TemporaryDirectory() as tmpdir:
        target = Path(tmpdir) / "sub" / "settings.json"
        write_json(target, {"a": 1})
        assert read_json(target, {}) == {"a": 1}
        write_json(target, {"b": [1, 2]})
        assert read_json(target, {}) == {"b": [1, 2]}
        leftovers = [f.name for f in target.parent.iterdir() if f.name.startswith(".settings.json.")]
        assert not leftovers, leftovers



