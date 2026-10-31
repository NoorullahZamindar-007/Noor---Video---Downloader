import tkinter as tk
from tkinter import scrolledtext
from urllib.parse import urlparse
import json
import requests
import re
import os


def _is_instagram_reel_url(url: str) -> bool:
    """Only Instagram reel links are fetchable here; anything else used to
    be fetched blindly and then fail with a confusing 'cannot find video
    URL' message (or fetch an arbitrary site the user pasted by mistake)."""
    try:
        host = (urlparse(url.strip()).hostname or "").lower().removeprefix("www.").rstrip(".")
    except ValueError:
        return False
    return host in {"instagram.com", "instagr.am"} and "/reel/" in urlparse(url.strip()).path


# ------------------ Functions ------------------
def download_instagram_reel(url, output_text):
    output_text.delete("1.0", tk.END)
    if not _is_instagram_reel_url(url):
        output_text.insert(tk.END, "❌ Enter a public Instagram reel URL (instagram.com/reel/...).\n")
        return
    try:
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
        response = requests.get(url, headers=headers, timeout=15)
        if response.status_code != 200:
            output_text.insert(tk.END, "❌ Failed to fetch URL. Make sure the link is public.\n")
            return
        
        video_url_match = re.search(r'"playable_url":"([^"]+)"', response.text)
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

        # Download video
        with requests.get(video_url, headers=headers, stream=True, timeout=15) as r:
            r.raise_for_status()
            with open(file_name, "wb") as f:
                for chunk in r.iter_content(chunk_size=8192):
                    if chunk:  # skip keep-alive chunks
                        f.write(chunk)
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
