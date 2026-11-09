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
from urllib.parse import urlparse

from validators import detect_platform, host_resolves_to_non_public, validate_url


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
        # Literal-host check passed, but the hostname may still resolve
        # to a private address (see host_resolves_to_non_public).
        if host_resolves_to_non_public(urlparse(url.strip()).hostname or ""):
            raise ValueError("Local or private URLs are not supported.")

        ytdlp = self._yt_dlp()
        try:
            with ytdlp.YoutubeDL({**self._base_options(), "skip_download": True}) as ydl:
                info = ydl.extract_info(url, download=False)
        except ytdlp.utils.DownloadError as exc:
            raise RuntimeError(self._friendly_error(str(exc), include_raw=True)) from exc

        # Cancel is otherwise only checked in the download progress
        # hook, so pressing Cancel during a slow metadata fetch did
        # nothing until the fetch finished (up to ~20 s, longer with
        # yt-dlp retries). The worker already surfaces this as
        # "Download cancelled".
        if self._cancel.is_set():
            raise DownloadCancelled("Download cancelled.")

        # yt-dlp can return None for a URL whose extractor yields no
        # result; using it unguarded raised a raw AttributeError instead
        # of a clear message.
        if not isinstance(info, dict):
            raise RuntimeError("Could not read video information for this URL.")

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
        # An unknown quality string used to fall through to
        # QUALITY_FORMATS.get(quality, "Best video") below and silently
        # download the best format instead of the one asked for; fail
        # fast here instead, before any metadata fetch or reset.
        if quality not in QUALITY_FORMATS:
            raise ValueError(
                f"Unknown quality option: {quality!r}. "
                f"Choose one of: {', '.join(QUALITY_FORMATS)}."
            )

        # Literal-host check passed, but the hostname may still resolve
        # to a private address (see host_resolves_to_non_public).
        if host_resolves_to_non_public(urlparse(url.strip()).hostname or ""):
            raise ValueError("Local or private URLs are not supported.")

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

        # Same as get_info: Cancel is otherwise only checked in the
        # download progress hook, so pressing Cancel during a slow
        # metadata fetch did nothing until the download itself
        # started. No partial file exists yet at this point, so
        # there is nothing to clean up.
        if self._cancel.is_set():
            raise DownloadCancelled("Download cancelled.")

        if not isinstance(info, dict):
            raise RuntimeError("Could not read video information for this URL.")

        quality_label = get_quality_label(quality)
        output_template, base_filename = get_unique_output_template(output_dir, info.get("title") or "download", quality_label)
        # Do NOT clean up partials here: get_unique_output_template only
        # avoids finished files, so a .part left by a crashed run reuses
        # this base name, and deleting it would defeat continuedl resume.
        # Failed/cancelled downloads are still cleaned up below.

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
                # The only direct [] access on a hook payload: a finished
                # status without a filename used to raise KeyError here.
                filename = status.get("filename")
                if filename:
                    self._last_file = Path(filename)
                progress({"percent": 1.0, "speed": None, "eta": None, "text": "Finalizing"})
 
        options = self._base_options()
        options.update(
            {
                "format": QUALITY_FORMATS.get(quality, QUALITY_FORMATS["Best video"]),
                "outtmpl": output_template,
                "progress_hooks": [hook],
                "windowsfilenames": True, 
                "skip_download": False,
                "nooverwrites": False,
                "continuedl": True,
                "postprocessors": [],
            }
        )
        ffmpeg = find_tool("ffmpeg")
        if ffmpeg:
            ffmpeg_path = Path(ffmpeg)
            options["ffmpeg_location"] = str(ffmpeg_path)
            # yt-dlp spawns ffmpeg by name; prepend its dir only once so
            # repeated downloads do not grow PATH without bound.
            ffmpeg_dir = str(ffmpeg_path.parent)
            path_entries = os.environ.get("PATH", "").split(os.pathsep)
            if ffmpeg_dir not in path_entries:
                os.environ["PATH"] = ffmpeg_dir + os.pathsep + os.environ.get("PATH", "")
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

        # Same None-result guard as the metadata fetch above: _final_path
        # calls .get on this, so a None result escaped as a raw
        # AttributeError after a "successful" download.
        if not isinstance(downloaded_info, dict):
            raise RuntimeError("Download finished but no video information was returned.")

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
            # yt-dlp does not guarantee "ext" on every format; a missing
            # extension previously produced labels like "720p None".
            ext = item.get("ext") or ""
            acodec = item.get("acodec")
            vcodec = item.get("vcodec")
            label = f"{height}p {ext}".strip() if height else ext
            if vcodec == "none" and acodec != "none":
                label = f"audio {ext}".strip() or "audio"
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
        try:
            entries = list(output_dir.iterdir())
        except OSError:
            # The folder may have been deleted mid-download; fall through
            # to the "output file could not be found" error below instead
            # of escaping as a raw FileNotFoundError.
            entries = []
        matches = [
            path
            for path in entries
            if path.is_file() and path.name.startswith(prefix) and ".part" not in path.name.lower() and ".ytdl" not in path.name.lower()
        ]
        if matches:
            # Alphabetical order used to win here, so a sidecar file
            # (thumbnail .jpg, .info.json) sorting after the media could
            # be reported as the download. Prefer a real media file, and
            # among those the most recently written one (the file this
            # download actually produced, not a leftover from an earlier
            # run that shares the base name).
            media_exts = {
                ".mp4", ".mkv", ".webm", ".mov", ".avi",
                ".mp3", ".m4a", ".opus", ".wav", ".flac",
            }

            def sort_key(path):
                try:
                    mtime = path.stat().st_mtime
                except OSError:
                    mtime = 0.0
                return (path.suffix.lower() in media_exts, mtime)

            return max(matches, key=sort_key)
        # yt-dlp reported success but left no file we can point at (e.g.
        # a postprocessor renamed the output unexpectedly). Returning
        # the bare base path here used to make the app report "Saved:"
        # and log a history entry for a file that does not exist, so
        # fail loudly instead of claiming a success the user cannot open.
        fallback = output_dir / base_filename
        if fallback.exists():
            return fallback
        raise RuntimeError(
            "Download finished but the output file could not be found in "
            f"{output_dir}. The download may have produced an unexpected filename."
        )

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



