from __future__ import annotations

import importlib.util
import os
import re 
import threading 
from pathlib import Path
from typing import Callable

from config import QUALITY_FORMATS
from utils import (
    check_ffmpeg_installed,
    cleanup_partial_files,
    ensure_folder,
    find_tool,
    get_quality_label,
    get_unique_output_template,
)
from validators import detect_platform, validate_url


class DownloadCancelled(Exception):
    pass


class DependencyError(RuntimeError):
    pass


ProgressCallback = Callable[[dict], None]


def has_ytdlp() -> bool:
    return importlib.util.find_spec("yt_dlp") is not None


def has_ffmpeg() -> bool:
    return check_ffmpeg_installed()


class VideoDownloader:
    def __init__(self) -> None:
        self._cancel = threading.Event()
        self._last_file: Path | None = None

    def cancel(self) -> None:
        self._cancel.set()

    def reset(self) -> None:
        self._cancel.clear()
        self._last_file = None

    def get_info(self, url: str) -> dict:
        ok, message = validate_url(url)
        if not ok:
            raise ValueError(message)

        ytdlp = self._yt_dlp()
        try:
            with ytdlp.YoutubeDL({**self._base_options(), "skip_download": True}) as ydl:
                info = ydl.extract_info(url, download=False)
        except ytdlp.utils.DownloadError as exc:
            raise RuntimeError(self._friendly_error(str(exc), include_raw=True)) from exc

        return {
            "title": info.get("title") or "Untitled",
            "duration": info.get("duration"),
            "uploader": info.get("uploader") or info.get("channel") or "Unknown", 
            "thumbnail": info.get("thumbnail"),
            "platform": detect_platform(url),
            "formats": self._simple_formats(info),
            "webpage_url": info.get("webpage_url") or url,
        }

    def download(self, url: str, folder: str | Path, quality: str, progress: ProgressCallback) -> Path:
        ok, message = validate_url(url)
        if not ok:
            raise ValueError(message)

        ytdlp = self._yt_dlp()
        self.reset()
        output_dir = ensure_folder(folder)

        if quality == "Audio only MP3" and not has_ffmpeg():
            raise DependencyError("Audio conversion requires FFmpeg. Please install FFmpeg and add it to PATH.")

        try:
            with ytdlp.YoutubeDL({**self._base_options(), "skip_download": True}) as ydl: 
                info = ydl.extract_info(url, download=False)
        except ytdlp.utils.DownloadError as exc:
            raise RuntimeError(self._friendly_error(str(exc), include_raw=True)) from exc

        quality_label = get_quality_label(quality)
        output_template, base_filename = get_unique_output_template(output_dir, info.get("title") or "download", quality_label)
        cleanup_partial_files(output_dir, base_filename)

        def hook(status: dict) -> None:
            if self._cancel.is_set():
                raise DownloadCancelled("Download cancelled.")
            if status.get("status") == "downloading":
                total = status.get("total_bytes") or status.get("total_bytes_estimate")
                downloaded = status.get("downloaded_bytes") or 0
                progress(
                    {
                        "percent": downloaded / total if total else None,
                        "speed": status.get("speed"),
                        "eta": status.get("eta"),
                        "text": f"Downloading {quality_label}",
                    }
                )
            elif status.get("status") == "finished":
                self._last_file = Path(status["filename"])
                progress({"percent": 1.0, "speed": None, "eta": None, "text": "Finalizing"})
 
        options = self._base_options()
        options.update(
            {
                "format": QUALITY_FORMATS.get(quality, QUALITY_FORMATS["Best video"]),
                "outtmpl": output_template,
                "progress_hooks": [hook],
                "windowsfilenames": True, 
                "skip_download": False,
                "overwrites": False,
                "nooverwrites": False,
                "continuedl": True,
                "postprocessors": [],
            }
        )
        ffmpeg = find_tool("ffmpeg")
        if ffmpeg:
            ffmpeg_path = Path(ffmpeg)
            options["ffmpeg_location"] = str(ffmpeg_path)
            os.environ["PATH"] = str(ffmpeg_path.parent) + os.pathsep + os.environ.get("PATH", "")
        if quality == "Audio only MP3":
            options["postprocessors"] = [
                {
                    "key": "FFmpegExtractAudio",
                    "preferredcodec": "mp3",
                    "preferredquality": "192",
                }
            ]

        try:
            with ytdlp.YoutubeDL(options) as ydl:
                downloaded_info = ydl.extract_info(url, download=True)
        except DownloadCancelled:
            cleanup_partial_files(output_dir, base_filename)
            raise
        except ytdlp.utils.DownloadError as exc:
            cleanup_partial_files(output_dir, base_filename)
            raise RuntimeError(self._friendly_error(str(exc), include_raw=True)) from exc
        except Exception:
            cleanup_partial_files(output_dir, base_filename)
            raise

        return self._final_path(downloaded_info, output_dir, base_filename, quality_label)

    @staticmethod
    def _yt_dlp():
        if not has_ytdlp():
            raise DependencyError("yt-dlp is not installed. Run: pip install -r requirements.txt")
        import yt_dlp

        return yt_dlp

    @staticmethod
    def _base_options() -> dict:
        return {
            "quiet": True,
            "no_warnings": True,
            "no_color": True,
            "noplaylist": True,
            "ignoreconfig": True,
            "socket_timeout": 20,
        }

    @staticmethod
    def _simple_formats(info: dict) -> list[str]:
        labels: list[str] = []
        seen: set[str] = set()
        for item in info.get("formats") or []:
            height = item.get("height")
            ext = item.get("ext")
            acodec = item.get("acodec")
            vcodec = item.get("vcodec")
            label = f"{height}p {ext}" if height else ext
            if vcodec == "none" and acodec != "none":
                label = f"audio {ext}"
            if label and label not in seen: 
                seen.add(label)
                labels.append(label)
        return labels[:24]

    @staticmethod
    def _final_path(info: dict, output_dir: Path, base_filename: str, quality_label: str) -> Path:
        for item in info.get("requested_downloads") or []:
            path = item.get("filepath")
            if path:
                candidate = Path(path)
                if candidate.exists():
                    return candidate
        path = info.get("filepath")
        if path and Path(path).exists():
            return Path(path)
        if quality_label == "audio-mp3":
            mp3 = output_dir / f"{base_filename}.mp3"
            if mp3.exists():
                return mp3
        prefix = f"{base_filename}."
        matches = sorted(
            path
            for path in output_dir.iterdir()
            if path.is_file() and path.name.startswith(prefix) and ".part" not in path.name.lower() and ".ytdl" not in path.name.lower()
        )
        return matches[-1] if matches else output_dir / base_filename

    @staticmethod
    def _friendly_error(error: str, include_raw: bool = False) -> str: 
        error = re.sub(r"\x1b\[[0-9;]*m", "", error).strip()
        text = error.lower()
        if any(word in text for word in ("private", "login", "sign in", "cookies", "members-only", "forbidden")):
            friendly = "This link appears private, login-restricted, or protected. Noor Video Downloader will not bypass restrictions."
        elif any(word in text for word in ("removed", "deleted", "404", "not found")):
            friendly = "This content appears removed or unavailable."
        elif any(word in text for word in ("geo", "region", "country")):
            friendly = "This content appears region-restricted. Region locks are not bypassed."
        elif "unsupported url" in text:
            friendly = "This URL is unsupported by yt-dlp."
        else:
            friendly = "Could not download this public media. Check the URL, permissions, and platform support."
        return f"{friendly}\n\nyt-dlp error:\n{error}" if include_raw else friendly



