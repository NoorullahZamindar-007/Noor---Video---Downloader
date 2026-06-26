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


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=True), encoding="utf-8")


def now_stamp() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def format_duration(seconds: int | float | None) -> str:
    if not seconds:
        return "Unknown"
    minutes, sec = divmod(int(seconds), 60)
    hours, minutes = divmod(minutes, 60)
    return f"{hours}:{minutes:02d}:{sec:02d}" if hours else f"{minutes}:{sec:02d}"


def format_bytes(value: int | float | None) -> str:
    if not value:
        return "-"
    size = float(value)
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{size:.1f} {unit}"
        size /= 1024
    return "-"


def format_eta(seconds: int | float | None) -> str:
    if seconds is None:
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
    if os.name == "nt":
        os.startfile(folder)  # type: ignore[attr-defined]
    else:
        subprocess.Popen(["open" if os.uname().sysname == "Darwin" else "xdg-open", str(folder)])


if __name__ == "__main__":
    assert sanitize_filename('bad<>:"/\\|?*name') == "bad_name"
    assert get_quality_label("Audio only MP3") == "audio-mp3"



