from __future__ import annotations

import queue
import threading
import traceback
from io import BytesIO
from pathlib import Path
from tkinter import filedialog, messagebox

import customtkinter as ctk

from config import APP_NAME, DEFAULT_DOWNLOAD_DIR, HISTORY_FILE, NOTICE, QUALITY_OPTIONS, SETTINGS_FILE, WINDOW_SIZE
from downloader import DependencyError, DownloadCancelled, VideoDownloader, has_ffmpeg, has_ytdlp
from utils import format_bytes, format_duration, format_eta, now_stamp, open_folder, read_json, write_json
from validators import detect_platform, validate_url


class NoorVideoDownloaderApp(ctk.CTk):
    def __init__(self) -> None:
        super().__init__()
        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("blue")

        self.title(APP_NAME)
        self.geometry(WINDOW_SIZE)
        self.minsize(920, 680)

        self.downloader = VideoDownloader()
        self.events: queue.Queue[tuple[str, object]] = queue.Queue()
        self.settings = read_json(SETTINGS_FILE, {})
        self.history: list[dict] = read_json(HISTORY_FILE, [])
        self.current_info: dict | None = None
        self.last_error_details = ""
        self.worker_running = False
        self.thumbnail_image = None

        self.url_var = ctk.StringVar()
        self.platform_var = ctk.StringVar(value="Platform: -")
        self.folder_var = ctk.StringVar(value=self.settings.get("download_folder", str(DEFAULT_DOWNLOAD_DIR)))
        self.quality_var = ctk.StringVar(value=self.settings.get("quality", QUALITY_OPTIONS[0]))
        self.progress_var = ctk.DoubleVar(value=0)
        self.speed_var = ctk.StringVar(value="Speed: -")
        self.eta_var = ctk.StringVar(value="ETA: -")
        self.status_var = ctk.StringVar(value="Ready")

        self._build_ui()
        self._check_dependencies()
        self.after(100, self._drain_events)

    def _build_ui(self) -> None:
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(6, weight=1)

        header = ctk.CTkFrame(self, fg_color="transparent")
        header.grid(row=0, column=0, padx=24, pady=(18, 6), sticky="ew")
        header.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(header, text=APP_NAME, font=ctk.CTkFont(size=28, weight="bold")).grid(row=0, column=0, sticky="w")
        ctk.CTkLabel(header, text=NOTICE, text_color="#f6c177", font=ctk.CTkFont(size=14)).grid(row=1, column=0, pady=(4, 0), sticky="w")
        ctk.CTkButton(header, text="About", width=90, command=self._show_about).grid(row=0, column=1, rowspan=2, sticky="e")

        url_frame = ctk.CTkFrame(self, corner_radius=8)
        url_frame.grid(row=1, column=0, padx=24, pady=10, sticky="ew")
        url_frame.grid_columnconfigure(0, weight=1)
        self.url_entry = ctk.CTkEntry(url_frame, textvariable=self.url_var, placeholder_text="Paste a public video/media URL", height=40)
        self.url_entry.grid(row=0, column=0, padx=(14, 8), pady=14, sticky="ew")
        self.url_entry.bind("<KeyRelease>", lambda _event: self._update_platform())
        ctk.CTkButton(url_frame, text="Paste", width=82, command=self._paste_url).grid(row=0, column=1, padx=6)
        ctk.CTkButton(url_frame, text="Clear", width=82, command=self._clear_url).grid(row=0, column=2, padx=6)
        ctk.CTkButton(url_frame, text="Fetch Info", width=110, command=self._fetch_info).grid(row=0, column=3, padx=(6, 14))

        options = ctk.CTkFrame(self, corner_radius=8)
        options.grid(row=2, column=0, padx=24, pady=(0, 10), sticky="ew")
        options.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(options, textvariable=self.platform_var).grid(row=0, column=0, padx=14, pady=12, sticky="w")
        ctk.CTkEntry(options, textvariable=self.folder_var).grid(row=0, column=1, padx=8, sticky="ew")
        ctk.CTkButton(options, text="Folder", width=86, command=self._choose_folder).grid(row=0, column=2, padx=6)
        ctk.CTkOptionMenu(options, values=QUALITY_OPTIONS, variable=self.quality_var, command=lambda _v: self._save_settings()).grid(row=0, column=3, padx=(6, 14))

        info = ctk.CTkFrame(self, corner_radius=8)
        info.grid(row=3, column=0, padx=24, pady=(0, 10), sticky="ew")
        info.grid_columnconfigure(1, weight=1)
        self.thumbnail = ctk.CTkLabel(info, text="No thumbnail", width=220, height=124, fg_color="#111827", corner_radius=6)
        self.thumbnail.grid(row=0, column=0, rowspan=4, padx=14, pady=14)
        self.title_label = ctk.CTkLabel(info, text="Title: -", anchor="w", wraplength=720)
        self.title_label.grid(row=0, column=1, padx=(0, 14), pady=(14, 2), sticky="ew")
        self.uploader_label = ctk.CTkLabel(info, text="Uploader: -", anchor="w")
        self.uploader_label.grid(row=1, column=1, padx=(0, 14), pady=2, sticky="ew")
        self.duration_label = ctk.CTkLabel(info, text="Duration: -", anchor="w")
        self.duration_label.grid(row=2, column=1, padx=(0, 14), pady=2, sticky="ew")
        self.formats_label = ctk.CTkLabel(info, text="Available qualities: fetch info to preview", anchor="w", wraplength=720)
        self.formats_label.grid(row=3, column=1, padx=(0, 14), pady=(2, 14), sticky="ew")

        actions = ctk.CTkFrame(self, corner_radius=8)
        actions.grid(row=4, column=0, padx=24, pady=(0, 10), sticky="ew")
        actions.grid_columnconfigure(0, weight=1)
        self.progress = ctk.CTkProgressBar(actions, variable=self.progress_var)
        self.progress.grid(row=0, column=0, columnspan=5, padx=14, pady=(14, 8), sticky="ew")
        ctk.CTkLabel(actions, textvariable=self.status_var).grid(row=1, column=0, padx=14, pady=(0, 12), sticky="w")
        ctk.CTkLabel(actions, textvariable=self.speed_var).grid(row=1, column=1, padx=8, pady=(0, 12), sticky="w")
        ctk.CTkLabel(actions, textvariable=self.eta_var).grid(row=1, column=2, padx=8, pady=(0, 12), sticky="w")
        self.download_button = ctk.CTkButton(actions, text="Download", command=self._download)
        self.download_button.grid(row=1, column=3, padx=6, pady=(0, 12))
        ctk.CTkButton(actions, text="Cancel", fg_color="#9f1239", hover_color="#be123c", command=self.downloader.cancel).grid(row=1, column=4, padx=(6, 14), pady=(0, 12))

        tabs = ctk.CTkTabview(self)
        tabs.grid(row=6, column=0, padx=24, pady=(0, 18), sticky="nsew")
        tabs.add("Status Log")
        tabs.add("History")
        tabs.tab("Status Log").grid_columnconfigure(0, weight=1)
        tabs.tab("Status Log").grid_rowconfigure(0, weight=1)
        tabs.tab("History").grid_columnconfigure(0, weight=1)
        tabs.tab("History").grid_rowconfigure(0, weight=1)

        self.log = ctk.CTkTextbox(tabs.tab("Status Log"), wrap="word")
        self.log.grid(row=0, column=0, columnspan=3, padx=8, pady=8, sticky="nsew")
        ctk.CTkButton(tabs.tab("Status Log"), text="Open Downloads Folder", command=lambda: open_folder(self.folder_var.get())).grid(row=1, column=0, padx=8, pady=(0, 8), sticky="w")
        self.copy_error_button = ctk.CTkButton(tabs.tab("Status Log"), text="Copy Error Details", state="disabled", command=self._copy_error_details)
        self.copy_error_button.grid(row=1, column=1, padx=8, pady=(0, 8), sticky="w")

        self.history_box = ctk.CTkTextbox(tabs.tab("History"), wrap="word")
        self.history_box.grid(row=0, column=0, padx=8, pady=8, sticky="nsew")
        ctk.CTkButton(tabs.tab("History"), text="Refresh History", command=self._render_history).grid(row=1, column=0, padx=8, pady=(0, 8), sticky="w")
        self._render_history()

    def _check_dependencies(self) -> None:
        if not has_ytdlp():
            self._log("yt-dlp is not installed. Run: pip install -r requirements.txt")
            self.status_var.set("Missing yt-dlp")
        elif not has_ffmpeg():
            self._log("Audio conversion requires FFmpeg. Please install FFmpeg and add it to PATH.")
        else:
            self._log("Dependencies ready.")

    def _paste_url(self) -> None:
        try:
            self.url_var.set(self.clipboard_get().strip())
            self._update_platform()
        except Exception:
            self._log("Clipboard is empty or unavailable.")

    def _clear_url(self) -> None:
        self.url_var.set("")
        self.current_info = None
        self.platform_var.set("Platform: -")
        self.title_label.configure(text="Title: -")
        self.uploader_label.configure(text="Uploader: -")
        self.duration_label.configure(text="Duration: -")
        self.formats_label.configure(text="Available qualities: fetch info to preview")
        self.thumbnail.configure(text="No thumbnail", image=None)

    def _choose_folder(self) -> None:
        folder = filedialog.askdirectory(initialdir=self.folder_var.get() or str(DEFAULT_DOWNLOAD_DIR))
        if folder:
            self.folder_var.set(folder)
            self._save_settings()

    def _update_platform(self) -> None:
        url = self.url_var.get().strip()
        ok, _message = validate_url(url)
        self.platform_var.set(f"Platform: {detect_platform(url) if ok else '-'}")

    def _fetch_info(self) -> None:
        url = self.url_var.get().strip()
        ok, message = validate_url(url)
        if not ok:
            self._show_error(message)
            return
        self._run_worker("Fetching public metadata", lambda: self.downloader.get_info(url), "info")

    def _download(self) -> None:
        url = self.url_var.get().strip()
        ok, message = validate_url(url)
        if not ok:
            self._show_error(message)
            return
        if not self.settings.get("permission_notice_seen"):
            if not messagebox.askokcancel(APP_NAME, f"{NOTICE}\n\nContinue only if this is your content or you have permission."):
                return
            self.settings["permission_notice_seen"] = True
            self._save_settings()
        self._save_settings()
        quality = self.quality_var.get()
        if quality == "Audio only MP3" and not has_ffmpeg():
            self._show_error("Audio conversion requires FFmpeg. Please install FFmpeg and add it to PATH.")
            return
        folder = self.folder_var.get()
        self.progress_var.set(0)
        self.speed_var.set("Speed: -")
        self.eta_var.set("ETA: -")
        self._run_worker("Starting download", lambda: self.downloader.download(url, folder, quality, self._progress), "done")

    def _run_worker(self, start_message: str, work, done_kind: str) -> None:
        if self.worker_running:
            self._log("Another task is already running.")
            return
        self.worker_running = True
        self.download_button.configure(state="disabled")
        self.status_var.set(start_message)
        self._log(start_message + "...")

        def wrapped() -> None:
            try:
                self.events.put((done_kind, work()))
            except DownloadCancelled as exc:
                self.events.put(("cancelled", str(exc)))
            except Exception as exc:
                details = traceback.format_exc()
                print(details)
                self.events.put(("error", (str(exc), details)))

        threading.Thread(target=wrapped, daemon=True).start()

    def _progress(self, data: dict) -> None:
        self.events.put(("progress", data))

    def _drain_events(self) -> None:
        while not self.events.empty():
            kind, payload = self.events.get()
            if kind == "info":
                self._show_info(payload)  # type: ignore[arg-type]
                self._finish_worker("Metadata ready")
            elif kind == "progress":
                self._show_progress(payload)  # type: ignore[arg-type]
            elif kind == "done":
                self.progress_var.set(1)
                self._finish_worker(f"Saved: {payload}")
                self._add_history(str(payload))
            elif kind == "cancelled":
                self._finish_worker("Download cancelled")
            elif kind == "error":
                message, details = payload  # type: ignore[misc]
                self._show_error(message, details)
                self.worker_running = False
                self.download_button.configure(state="normal")
        self.after(100, self._drain_events)

    def _finish_worker(self, message: str) -> None:
        self.worker_running = False
        self.download_button.configure(state="normal")
        self.status_var.set(message)
        self._log(message)

    def _show_info(self, info: dict) -> None:
        self.current_info = info
        self.title_label.configure(text=f"Title: {info['title']}")
        self.uploader_label.configure(text=f"Uploader: {info.get('uploader') or 'Unknown'}")
        self.duration_label.configure(text=f"Duration: {format_duration(info.get('duration'))}")
        self.platform_var.set(f"Platform: {info.get('platform') or detect_platform(self.url_var.get())}")
        formats = ", ".join(info.get("formats") or []) or "No separate quality list available"
        self.formats_label.configure(text=f"Available qualities: {formats}")
        self._load_thumbnail(info.get("thumbnail"))

    def _load_thumbnail(self, url: str | None) -> None:
        if not url:
            self.thumbnail.configure(text="No thumbnail", image=None)
            return
        try:
            import requests
            from PIL import Image

            response = requests.get(url, timeout=8)
            response.raise_for_status()
            image = Image.open(BytesIO(response.content))
            self.thumbnail_image = ctk.CTkImage(image, size=(220, 124))
            self.thumbnail.configure(text="", image=self.thumbnail_image)
        except Exception:
            self.thumbnail.configure(text="Thumbnail unavailable", image=None)

    def _show_progress(self, data: dict) -> None:
        percent = data.get("percent")
        if percent is not None:
            self.progress_var.set(max(0, min(1, float(percent))))
        self.speed_var.set(f"Speed: {format_bytes(data.get('speed'))}/s")
        self.eta_var.set(f"ETA: {format_eta(data.get('eta'))}")
        self.status_var.set(data.get("text") or "Downloading")

    def _show_error(self, message: str, details: str | None = None) -> None:
        self.last_error_details = details or message
        self.copy_error_button.configure(state="normal")
        friendly = message or "Something went wrong."
        self._log(f"Error: {friendly}")
        if details:
            self._log("Full error details:")
            self.log.insert("end", details + "\n")
            self.log.see("end")
        self.status_var.set("Error")

    def _copy_error_details(self) -> None:
        self.clipboard_clear()
        self.clipboard_append(self.last_error_details)
        self._log("Error details copied to clipboard.")

    def _add_history(self, filepath: str) -> None:
        item = {
            "time": now_stamp(),
            "title": (self.current_info or {}).get("title") or Path(filepath).name,
            "platform": detect_platform(self.url_var.get()),
            "quality": self.quality_var.get(),
            "url": self.url_var.get().strip(),
            "final_file": filepath,
            "file": filepath,
        }
        self.history.insert(0, item)
        self.history = self.history[:100]
        write_json(HISTORY_FILE, self.history)
        self._render_history()

    def _render_history(self) -> None:
        self.history_box.delete("1.0", "end")
        if not self.history:
            self.history_box.insert("end", "No downloads yet.\n")
            return
        for item in self.history:
            self.history_box.insert(
                "end",
                f"{item.get('time')} | {item.get('platform')} | {item.get('quality')}\n"
                f"{item.get('title')}\n{item.get('file')}\n{item.get('url')}\n\n",
            )

    def _save_settings(self) -> None:
        self.settings["download_folder"] = self.folder_var.get()
        self.settings["quality"] = self.quality_var.get()
        write_json(SETTINGS_FILE, self.settings)

    def _show_about(self) -> None:
        messagebox.showinfo(
            APP_NAME,
            f"{APP_NAME}\n\n{NOTICE}\n\nSupports public media links handled by yt-dlp. Private, login-restricted, paywalled, DRM-protected, removed, or region-restricted content is not bypassed.",
        )

    def _log(self, message: str) -> None:
        self.log.insert("end", f"[{now_stamp()}] {message}\n")
        self.log.see("end")


if __name__ == "__main__":
    NoorVideoDownloaderApp().mainloop()



