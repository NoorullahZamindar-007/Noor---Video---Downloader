from __future__ import annotations

import os
from pathlib import Path


APP_NAME = "Noor Video Downloader"
NOTICE = "Only download content you own or have permission to use."
DEFAULT_DOWNLOAD_DIR = Path.home() / "Downloads" / "Noor Video Downloader" 

DATA_DIR = Path(os.getenv("LOCALAPPDATA") or (Path.home() / ".config")) / "NoorVideoDownloader"
SETTINGS_FILE = DATA_DIR / "settings.json"
HISTORY_FILE = DATA_DIR / "history.json"

QUALITY_OPTIONS = ["Best video", "1080p", "720p", "480p", "Audio only MP3"]
QUALITY_FORMATS = {
    "Best video": "bestvideo+bestaudio/best",
    "1080p": "bestvideo[height<=1080]+bestaudio/best[height<=1080]/best",
    "720p": "bestvideo[height<=720]+bestaudio/best[height<=720]/best",
    "480p": "bestvideo[height<=480]+bestaudio/best[height<=480]/best",
    "Audio only MP3": "bestaudio/best", 
}

WINDOW_SIZE = "1040x760"
