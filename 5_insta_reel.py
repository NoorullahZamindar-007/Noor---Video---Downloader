import tkinter as tk
from tkinter import scrolledtext
from urllib.parse import urlparse
import json
import requests
import re
import os

from validators import host_resolves_to_non_public, validate_url


# Instagram serves reel media from its own CDNs; a 2 GB cap keeps a
# misdirected download from filling the disk.
INSTAGRAM_MEDIA_HOSTS = (".cdninstagram.com", ".fbcdn.net")
MAX_REEL_BYTES = 2 * 1024 * 1024 * 1024


def _is_instagram_reel_url(url: str) -> bool:
    """Only Instagram reel links are fetchable here; anything else used to
    be fetched blindly and then fail with a confusing 'cannot find video
    URL' message (or fetch an arbitrary site the user pasted by mistake)."""
    try:
        parsed = urlparse(url.strip())
        host = (parsed.hostname or "").lower().removeprefix("www.").rstrip(".")
    except ValueError:
        return False
    # A non-http(s) scheme (e.g. ftp://instagram.com/reel/...) passed
    # the host/path checks and then failed inside requests with a
    # confusing "No connection adapters" error instead of the clean
    # "Enter a public Instagram reel URL" message.
    return parsed.scheme in {"http", "https"} and host in {"instagram.com", "instagr.am"} and "/reel/" in parsed.path


# ------------------ Functions ------------------
def download_instagram_reel(url, output_text):
    output_text.delete("1.0", tk.END)
    # A pasted URL with leading/trailing whitespace passed the
    # reel check (it strips internally) but was then fetched
    # unstripped, so requests failed on the whitespace instead of
    # fetching the reel. Strip once, up front.
    url = url.strip() if isinstance(url, str) else ""
    if not _is_instagram_reel_url(url):
        output_text.insert(tk.END, "❌ Enter a public Instagram reel URL (instagram.com/reel/...).\n")
        return
    try:
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
        # Stream the page with a size cap: the old response.text read
        # the whole body into memory, so a misdirected or bloated page
        # ballooned RAM before the regex ever ran. Reel pages are a
        # few MB at most, so 10 MB leaves ample headroom.
        max_page_bytes = 10 * 1024 * 1024
        chunks = []
        total = 0
        with requests.get(url, headers=headers, timeout=15, stream=True) as page:
            if page.status_code != 200:
                output_text.insert(tk.END, "❌ Failed to fetch URL. Make sure the link is public.\n")
                return
            for chunk in page.iter_content(chunk_size=65536):
                if not chunk:
                    continue
                total += len(chunk)
                if total > max_page_bytes:
                    output_text.insert(tk.END, "❌ The page is too large to read.\n")
                    return
                chunks.append(chunk)
        page_text = b"".join(chunks).decode("utf-8", errors="replace")
        video_url_match = re.search(r'"playable_url":"([^"]+)"', page_text)
        if not video_url_match:
            output_text.insert(tk.END, "❌ Cannot find video URL. Possibly private or removed.\n")
            return
        
        # The match is a JSON string literal, so decode every escape properly
        # (e.g. \u0026 and \/); a plain replace only handled one case and
        # left mangled URLs when the page escaped forward slashes.
        raw_url = video_url_match.group(1)
        try:
            video_url = json.loads(f'"{raw_url}"')
        except json.JSONDecodeError:
            video_url = raw_url.replace("\\u0026", "&")
        # The extracted URL comes straight from page JSON: validate it
        # like the main app validates thumbnails. A lookalike page
        # could point it at a private/LAN address or an arbitrary host,
        # and the body used to be written to disk unbounded.
        video_host = (urlparse(video_url).hostname or "").lower()
        if (
            not validate_url(video_url)[0]
            or not video_url.lower().startswith("https://")
            or host_resolves_to_non_public(video_host)
            or not video_host.endswith(INSTAGRAM_MEDIA_HOSTS)
        ):
            output_text.insert(tk.END, "❌ The video link in this page is not a valid Instagram media URL.\n")
            return
        # Extract the reel shortcode robustly: url.split("/")[-2] breaks when
        # the URL has no trailing slash (".../reel/ABC123" -> "reel.mp4") and
        # keeps query strings that are illegal in filenames.
        shortcode_match = re.search(r"/reel/([A-Za-z0-9_-]+)", url)
        if not shortcode_match:
            output_text.insert(tk.END, "❌ Could not parse a reel ID from the URL.\n")
            return
        base_name = re.sub(r"[^A-Za-z0-9_-]", "_", shortcode_match.group(1))
        # Never silently overwrite a previous download with the same name.
        file_name = base_name + ".mp4"
        counter = 1
        while os.path.exists(file_name):
            counter += 1
            file_name = f"{base_name} ({counter}).mp4"

        # Download video; a failure mid-stream used to leave a corrupt
        # partial .mp4 behind that looked like a finished download (and
        # pushed the next run to a "(2)" name), so remove it on failure.
        try:
            with requests.get(video_url, headers=headers, stream=True, timeout=15) as r:
                r.raise_for_status()
                # A 200 reply is not necessarily a video: an error page
                # served as HTML used to be written to disk as a .mp4.
                # Refuse a body whose Content-Type is present and not a
                # video type; a missing header is still accepted.
                content_type = (r.headers.get("Content-Type") or "").split(";")[0].strip().lower()
                if content_type and not content_type.startswith("video/"):
                    raise ValueError("The media link did not return a video file.")
                written = 0
                with open(file_name, "wb") as f:
                    for chunk in r.iter_content(chunk_size=8192):
                        if chunk:  # skip keep-alive chunks
                            written += len(chunk)
                            if written > MAX_REEL_BYTES:
                                raise ValueError("Video is larger than 2 GB; download aborted.")
                            f.write(chunk)
        except Exception:
            try:
                os.remove(file_name)
            except OSError:
                pass
            raise
        output_text.insert(tk.END, f"✅ Reel downloaded as {file_name}\n")
        
    except Exception as e:
        output_text.insert(tk.END, f"❌ Error: {e}\n")

# ------------------ GUI ------------------
def _run_gui() -> None:
    root = tk.Tk()
    root.title("📥 Instagram Reel Downloader")
    root.geometry("650x400")
    root.configure(bg="#1e1e2f")

    # Title
    tk.Label(root, text="Instagram Reel Downloader", font=("Helvetica", 18, "bold"),
             fg="#ff79c6", bg="#1e1e2f").pack(pady=10)

    # URL Entry
    tk.Label(root, text="Paste Public Reel URL:", font=("Arial", 12, "bold"),
             fg="#f8f8f2", bg="#1e1e2f").pack(pady=5)
    url_entry = tk.Entry(root, font=("Arial", 12), width=60, fg="black")
    url_entry.pack(pady=5)

    # Output Area (created before the button so the callback can use it)
    output_text = scrolledtext.ScrolledText(root, width=75, height=12,
                                            font=("Arial", 12), bg="#282a36", fg="#f8f8f2",
                                            insertbackground="white")
    output_text.pack(pady=10)

    # Download Button
    tk.Button(root, text="⬇️ Download Reel", command=lambda: download_instagram_reel(url_entry.get(), output_text),
              font=("Arial", 12, "bold"), bg="#50fa7b", fg="black").pack(pady=10)

    # Run App
    root.mainloop()


if __name__ == "__main__":
    # Guarded so the download helper can be imported (e.g. by tests or
    # tooling) without popping open a Tk window.
    _run_gui()
