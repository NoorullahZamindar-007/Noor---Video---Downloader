# Noor Video Downloader

A modern, permission-respecting desktop video downloader built with Python, CustomTkinter, and yt-dlp.

> Only download content you own or have permission to use.

Noor Video Downloader is designed for public media downloads from supported platforms. It does not use cookies, stolen sessions, credential scraping, private APIs, DRM bypasses, login bypasses, paywall bypasses, private-account access, or region-lock workarounds.

## What It Does

Noor Video Downloader gives you a clean desktop interface for fetching public media details, choosing a download quality, and saving the file with a safe filename.

Main features:

- Modern dark desktop UI
- Public URL input with paste and clear controls
- Platform detection
- Metadata preview before downloading
- Title, duration, uploader, thumbnail, and available formats
- Download folder selector
- Quality selector
- Progress bar, speed, ETA, and status log
- Cancel download button
- Copy error details button
- Open downloads folder button
- Safe filenames for Windows
- Duplicate-safe output names
- Local settings and download history
- Threaded downloads so the UI does not freeze

## Supported Platforms

The app uses `yt-dlp`, so support depends on what `yt-dlp` can legally and technically handle for public content.

Common supported platforms:

- YouTube public videos
- Instagram public reels/posts, when publicly available and supported by yt-dlp
- Facebook public videos, when publicly available and supported by yt-dlp
- TikTok public videos
- X/Twitter public videos
- Vimeo
- Many other public sites supported by yt-dlp

The app intentionally refuses or reports errors for:

- Private posts or private accounts
- Removed or unavailable content
- Login-required content
- Paywalled content
- DRM-protected media
- Region-restricted media
- Any content you do not own or do not have permission to download

## Tech Stack

This project uses:

- Python 3.10+
- CustomTkinter for the modern desktop interface
- yt-dlp for public media metadata and downloads
- Pillow for thumbnail image handling
- requests for loading thumbnails
- FFmpeg for best-quality video/audio merging and MP3 extraction
- Deno, optional but recommended, for newer YouTube JavaScript extraction support

## Project Structure

```text
Download-Instagram-reel-python/
  app.py              Desktop GUI, tabs, worker threads, user actions
  downloader.py       yt-dlp metadata/download logic and friendly errors
  validators.py       URL validation and platform detection
  config.py           App name, paths, window size, quality presets
  utils.py            Filenames, JSON settings, folders, formatting, cleanup
  requirements.txt    Python dependencies
  README.md           Project documentation
  LICENSE             License file
  5_insta_reel.py     Original prototype script
```

## Install

Open PowerShell in the project folder:

```powershell
cd "D:\Projcets\Done Projects\Download-Instagram-reel-python"
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

If PowerShell blocks venv activation, run:

```powershell
Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
```

Then activate again:

```powershell
.\.venv\Scripts\Activate.ps1
```

## Run

```powershell
python app.py
```

Basic flow:

1. Paste a public media URL.
2. Click `Fetch Info`.
3. Review the title, duration, uploader, thumbnail, and formats.
4. Choose the download folder.
5. Choose a quality.
6. Click `Download`.

## Quality Options

Available quality presets:

- Best video
- 1080p
- 720p
- 480p
- Audio only MP3

FFmpeg is required for:

- Best video/audio merging on many sites
- Audio-only MP3 conversion
- Some formats where video and audio are separate streams

Without FFmpeg, yt-dlp may download a lower-quality single-file format or show a warning.

## File Naming

The app creates safe filenames and includes the selected quality.

Examples:

```text
My Video Title [best].mp4
My Video Title [1080p].mp4
My Video Title [720p].mp4
My Video Title [480p].mp4
My Video Title [audio-mp3].mp3
```

If a file already exists, the app creates a new name:

```text
My Video Title [720p] (1).mp4
My Video Title [720p] (2).mp4
```

Partial files such as `.part`, `.ytdl`, `.tmp`, and `.temp` are cleaned for the selected output name after failed or cancelled downloads.

## Install FFmpeg

Recommended on Windows:

```powershell
winget install -e --id Gyan.FFmpeg --source winget
```

After installing, close and reopen PowerShell, then check:

```powershell
Get-Command ffmpeg
```

If it works, restart the app.

## Install Deno

YouTube may show this warning:

```text
No supported JavaScript runtime could be found.
```

Install Deno:

```powershell
winget install -e --id DenoLand.Deno --source winget
```

After installing, close and reopen PowerShell, then check:

```powershell
Get-Command deno
```

## Update yt-dlp

Sites change often, so keep yt-dlp updated:

```powershell
pip install -U yt-dlp
```

## Troubleshooting

### `yt-dlp is not installed`

Run:

```powershell
pip install -r requirements.txt
```

### `ffmpeg not found`

Install FFmpeg, reopen PowerShell, and run the app again.

```powershell
winget install -e --id Gyan.FFmpeg --source winget
```

### `No supported JavaScript runtime could be found`

Install Deno:

```powershell
winget install -e --id DenoLand.Deno --source winget
```

### `Audio conversion requires FFmpeg`

Audio-only MP3 needs FFmpeg. Install FFmpeg or choose a video quality instead.

### `Private, restricted, or login-required`

The app will not bypass restrictions. Use a public URL for content you own or have permission to download.

### `Unsupported URL`

The platform or URL format may not be supported by yt-dlp. Update yt-dlp:

```powershell
pip install -U yt-dlp
```

### PowerShell says `python.exe` has a logon-session error

Close PowerShell and open a fresh terminal. Then run:

```powershell
.\.venv\Scripts\Activate.ps1
python app.py
```

## Local Data

The app stores settings and history locally.

On Windows, the data folder is:

```text
%LOCALAPPDATA%\NoorVideoDownloader
```

Stored files:

- `settings.json`
- `history.json`

## Packaging with PyInstaller

Install PyInstaller:

```powershell
pip install pyinstaller
```

Build a desktop executable:

```powershell
pyinstaller --onefile --windowed --name "Noor Video Downloader" app.py
```

The output appears in:

```text
dist/
```

Note: FFmpeg and Deno are not bundled by default. For a public release, either document them as system requirements or bundle them deliberately.

## Manual Test Checklist

Use only a public URL that you own or have permission to download.

1. Run `python app.py`.
2. Paste a supported public URL.
3. Click `Fetch Info`.
4. Confirm metadata appears.
5. Download as `480p`.
6. Download the same URL as `720p`.
7. Download the same URL as `1080p`.
8. Download as `Audio only MP3` after FFmpeg is installed.
9. Confirm files are saved with separate quality labels.
10. Test `Cancel` on a large download.
11. Test `Copy Error Details` with an unsupported URL.

## Future Web Version

The code is already split so a web version can reuse the core logic.

Suggested web architecture:

- FastAPI backend
- React frontend
- Reuse `downloader.py` for metadata and downloads
- Reuse `validators.py` for URL validation
- Reuse `config.py` for quality presets
- Reuse `utils.py` for safe filenames and formatting
- Add background jobs for long downloads
- Add WebSocket or Server-Sent Events for progress updates
- Store job history in SQLite

Do not run downloads directly inside a request handler in the web version. Put long downloads in a background worker or job queue.

## Legal and Safety Notice

This tool is for downloading public content only when you own it, created it, or have permission to use it. You are responsible for following each platform's terms, copyright rules, and local laws.

The app does not attempt to bypass platform protections.

