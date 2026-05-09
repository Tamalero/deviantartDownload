import os
import sys
import time
import random
import re
import argparse
import configparser
from pathlib import Path
from datetime import datetime

import requests
from tqdm import tqdm
from cryptography.fernet import Fernet, InvalidToken

VERSION     = "1.2.0"
GITHUB_REPO = "Tamalero/deviantartDownload"
_GITHUB_API = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"

# --- XDG paths ---
_cfg_home = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
CONFIG_DIR  = _cfg_home / "deviantartdownload"
CONFIG_FILE = CONFIG_DIR / "config.ini"
KEY_FILE    = CONFIG_DIR / "secret.key"
DEFAULT_DOWNLOAD_DIR = str(Path.home() / "Pictures" / "DeviantArtDownload")

# --- DeviantArt OAuth2 endpoints ---
_DA_BASE       = "https://www.deviantart.com"
TOKEN_URL      = f"{_DA_BASE}/oauth2/token"
API_BASE       = f"{_DA_BASE}/api/v1/oauth2"
GALLERY_URL    = f"{API_BASE}/gallery/all"
FAVOURITES_URL = f"{API_BASE}/collections/all"
DOWNLOAD_URL   = f"{API_BASE}/deviation/download"
AUTH_URL       = f"{_DA_BASE}/oauth2/authorize"
REDIRECT_PORT  = 8765   # add http://localhost:8765 to your DA app's redirect URI whitelist


# ── Config helpers ─────────────────────────────────────────────────────────────

def load_config():
    cfg = configparser.ConfigParser()
    if CONFIG_FILE.exists():
        cfg.read(CONFIG_FILE)
    return cfg


def save_config(client_id: str, client_secret: str):
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    cfg = load_config()
    if not cfg.has_section("credentials"):
        cfg.add_section("credentials")
    cfg.set("credentials", "client_id", client_id)
    cfg.set("credentials", "client_secret", encrypt_password(client_secret))
    with open(CONFIG_FILE, "w") as f:
        cfg.write(f)


def save_ui_state(state: dict):
    cfg = load_config()
    if not cfg.has_section("last_run"):
        cfg.add_section("last_run")
    for k, v in state.items():
        cfg.set("last_run", k, str(v))
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    with open(CONFIG_FILE, "w") as f:
        cfg.write(f)


# ── Encryption ─────────────────────────────────────────────────────────────────

def _get_or_create_key() -> bytes:
    if KEY_FILE.exists():
        return KEY_FILE.read_bytes()
    key = Fernet.generate_key()
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    KEY_FILE.write_bytes(key)
    KEY_FILE.chmod(0o600)
    return key


def encrypt_password(password: str) -> str:
    return Fernet(_get_or_create_key()).encrypt(password.encode()).decode()


def decrypt_password(token: str) -> str | None:
    """Decrypt a Fernet token.
    Returns None if the token looks like Fernet but can't be decrypted (key lost).
    Returns the token unchanged for legacy plain-text values (migration path)."""
    try:
        return Fernet(_get_or_create_key()).decrypt(token.encode()).decode()
    except (InvalidToken, Exception):
        if token.startswith("gAAAAA"):
            return None
        return token


def get_client_secret(cfg) -> str | None:
    raw = cfg.get("credentials", "client_secret", fallback=None)
    if raw is None:
        return None
    return decrypt_password(raw)


# ── Authentication ─────────────────────────────────────────────────────────────

def get_access_token(client_id: str, client_secret: str) -> str:
    """Exchange client credentials for an OAuth2 access token."""
    resp = requests.post(
        TOKEN_URL,
        data={
            "client_id":     client_id,
            "client_secret": client_secret,
            "grant_type":    "client_credentials",
        },
        timeout=15,
    )
    resp.raise_for_status()
    data = resp.json()
    if "error" in data:
        raise RuntimeError(f"OAuth2 error: {data.get('error_description', data['error'])}")
    return data["access_token"]


def get_access_token_auth_code(
    client_id: str, client_secret: str,
    port: int = REDIRECT_PORT, log_fn=print,
) -> dict:
    """OAuth2 Authorization Code flow — opens browser, catches redirect, returns full token dict.

    Requires http://localhost:{port} in your DA app's redirect URI whitelist (default: 8765).
    The authenticated DA account must have mature content viewing enabled and be age-verified.
    """
    import base64
    import hashlib
    import os as _os
    import urllib.parse
    import webbrowser
    from http.server import BaseHTTPRequestHandler, HTTPServer

    redirect_uri   = f"http://localhost:{port}/callback"
    state          = _os.urandom(8).hex()
    code_verifier  = base64.urlsafe_b64encode(_os.urandom(32)).rstrip(b"=").decode()
    code_challenge = base64.urlsafe_b64encode(
        hashlib.sha256(code_verifier.encode()).digest()
    ).rstrip(b"=").decode()

    auth_params = urllib.parse.urlencode({
        "response_type":         "code",
        "client_id":             client_id,
        "redirect_uri":          redirect_uri,
        "scope":                 "browse",
        "state":                 state,
        "code_challenge":        code_challenge,
        "code_challenge_method": "S256",
    })
    auth_url = f"{AUTH_URL}?{auth_params}"
    result: dict[str, str | None] = {"code": None, "error": None}

    class _Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            qs = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            if "code" in qs:
                result["code"] = qs["code"][0]
                body   = b"<html><body><h2>Authorized!</h2><p>You can close this tab.</p></body></html>"
                status = 200
            else:
                result["error"] = qs.get("error", ["unknown"])[0]
                body   = b"<html><body><h2>Authorization failed.</h2><p>You can close this tab.</p></body></html>"
                status = 400
            self.send_response(status)
            self.send_header("Content-Type", "text/html")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, fmt, *args):
            pass

    server         = HTTPServer(("localhost", port), _Handler)
    server.timeout = 120

    log_fn("Opening DeviantArt authorization page in your browser…")
    log_fn(f"(If it doesn't open automatically, visit: {auth_url})")
    webbrowser.open(auth_url)
    log_fn("Waiting for authorization (120 s timeout)…")

    server.handle_request()
    server.server_close()

    if result["error"]:
        raise RuntimeError(f"Authorization denied: {result['error']}")
    if not result["code"]:
        raise RuntimeError("Authorization timed out — no code received within 120 s.")

    resp = requests.post(TOKEN_URL, data={
        "grant_type":    "authorization_code",
        "client_id":     client_id,
        "client_secret": client_secret,
        "code":          result["code"],
        "redirect_uri":  redirect_uri,
        "code_verifier": code_verifier,
    }, timeout=15)
    resp.raise_for_status()
    data = resp.json()
    if "error" in data:
        raise RuntimeError(f"Token exchange failed: {data.get('error_description', data['error'])}")
    return data


def refresh_access_token(client_id: str, client_secret: str, refresh_token: str) -> dict:
    """Exchange a refresh token for a new access token."""
    resp = requests.post(TOKEN_URL, data={
        "grant_type":    "refresh_token",
        "client_id":     client_id,
        "client_secret": client_secret,
        "refresh_token": refresh_token,
    }, timeout=15)
    resp.raise_for_status()
    data = resp.json()
    if "error" in data:
        raise RuntimeError(f"Token refresh failed: {data.get('error_description', data['error'])}")
    return data


def save_token(token_data: dict):
    """Persist access_token, refresh_token, and expiry to config (Fernet-encrypted)."""
    cfg = load_config()
    if not cfg.has_section("credentials"):
        cfg.add_section("credentials")
    cfg.set("credentials", "access_token", encrypt_password(token_data["access_token"]))
    if "refresh_token" in token_data:
        cfg.set("credentials", "refresh_token", encrypt_password(token_data["refresh_token"]))
    expires_at = int(time.time()) + int(token_data.get("expires_in", 3600)) - 60
    cfg.set("credentials", "token_expires_at", str(expires_at))
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    with open(CONFIG_FILE, "w") as f:
        cfg.write(f)


def load_token(cfg) -> tuple[str | None, str | None, int]:
    """Return (access_token, refresh_token, expires_at) from a loaded config."""
    access_raw  = cfg.get("credentials", "access_token",      fallback=None)
    refresh_raw = cfg.get("credentials", "refresh_token",     fallback=None)
    expires_at  = int(cfg.get("credentials", "token_expires_at", fallback="0") or "0")
    return (
        decrypt_password(access_raw)  if access_raw  else None,
        decrypt_password(refresh_raw) if refresh_raw else None,
        expires_at,
    )


def get_or_refresh_token(client_id: str, client_secret: str, log_fn=print) -> str:
    """Return a valid access token for CLI use — refreshes or re-authorizes via browser as needed."""
    cfg = load_config()
    access_token, refresh_token, expires_at = load_token(cfg)

    if access_token and time.time() < expires_at:
        return access_token

    if refresh_token:
        log_fn("Access token expired — refreshing…")
        try:
            data = refresh_access_token(client_id, client_secret, refresh_token)
            save_token(data)
            log_fn("Token refreshed.")
            return data["access_token"]
        except Exception as e:
            log_fn(f"Token refresh failed ({e}) — re-authorizing…")

    data = get_access_token_auth_code(client_id, client_secret, log_fn=log_fn)
    save_token(data)
    log_fn("Authorized.")
    return data["access_token"]


# ── Helpers ────────────────────────────────────────────────────────────────────

def sanitize_filename(text: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_-]", "_", text)


def format_timestamp(unix_ts) -> str:
    try:
        dt = datetime.utcfromtimestamp(int(unix_ts))
        return dt.strftime("%Y%m%d_%H%M%S")
    except Exception:
        return "unknown_date"


def _deviation_media_type(dev: dict) -> str:
    """Infer media type from deviation fields — DA API does not include an explicit 'type' field."""
    if dev.get("videos"):
        return "film"
    if dev.get("content") or dev.get("is_downloadable"):
        return "image"
    return ""


def _version_tuple(v: str) -> tuple[int, ...]:
    try:
        return tuple(int(x) for x in v.split("."))
    except Exception:
        return (0,)


def check_for_update() -> tuple[str | None, str | None]:
    """Check GitHub releases for a newer version.
    Returns (tag_without_v, release_url) or (None, None) on failure or no releases yet."""
    try:
        resp = requests.get(
            _GITHUB_API,
            headers={"Accept": "application/vnd.github+json"},
            timeout=5,
        )
        if resp.status_code != 200:
            return None, None
        data = resp.json()
        tag = data.get("tag_name", "").lstrip("v")
        url = data.get("html_url", "")
        if tag and url:
            return tag, url
    except Exception:
        pass
    return None, None


def _image_ext_from_url(url: str) -> str:
    path = url.split("?")[0]
    if "." in path:
        ext = path.rsplit(".", 1)[-1].lower()
        if ext in ("jpg", "jpeg", "png", "gif", "webp", "bmp"):
            return ext
    return "jpg"


def _convert_image(src_path: str, target_ext: str) -> str | None:
    """Convert src_path to target_ext ('png' or 'jpg') using Pillow.
    Returns the new file path on success, or None if Pillow is unavailable or conversion fails.
    The caller is responsible for deleting the original file."""
    try:
        from PIL import Image
        img = Image.open(src_path)
        if target_ext == "jpg" and img.mode in ("RGBA", "LA", "P"):
            img = img.convert("RGB")
        new_path = src_path.rsplit(".", 1)[0] + "." + target_ext
        img.save(new_path, "JPEG" if target_ext == "jpg" else "PNG",
                 quality=95 if target_ext == "jpg" else None)
        return new_path
    except Exception:
        return None


def _best_video_url(videos: list) -> tuple[str, int] | None:
    """Return (url, filesize) for the highest-quality entry in the deviation videos array.

    DA API embeds direct CDN URLs in the videos array; prefer these over yt-dlp
    so we are not dependent on yt-dlp's DeviantArt extractor staying functional.
    Returns None if the list is empty or no entry has a src."""
    def _quality_px(v):
        try:
            return int(str(v.get("quality", "0")).rstrip("p"))
        except ValueError:
            return 0

    best = max(videos, key=_quality_px, default=None)
    if best:
        src = best.get("src", "")
        if src:
            return src, int(best.get("filesize", 0))
    return None


# ── Feed fetching ──────────────────────────────────────────────────────────────

def _fetch_feed(url, token, username, max_pages, page_size, log_fn, media_type="both",
                verbose=False):
    """Shared offset-based pagination loop for gallery and favourites endpoints."""
    headers = {"Authorization": f"Bearer {token}"}
    params_base = {
        "username":       username,
        "limit":          page_size,
        "mature_content": "true",
    }

    items  = []
    offset = 0
    tty    = sys.stdout is not None and sys.stdout.isatty()

    if verbose:
        log_fn(f"[verbose] GET {url}")
        log_fn(f"[verbose] base params: {params_base}")

    with tqdm(total=max_pages, desc="Scanning", unit="pg", disable=not tty) as pbar:
        for page_num in range(max_pages):
            params = {**params_base, "offset": offset}
            if verbose:
                log_fn(f"[verbose] page {page_num + 1}: offset={offset}")

            resp = requests.get(url, headers=headers, params=params, timeout=15)

            if verbose:
                log_fn(f"[verbose] HTTP {resp.status_code}")

            resp.raise_for_status()
            data = resp.json()

            if verbose:
                top_keys = list(data.keys())
                log_fn(f"[verbose] response keys: {top_keys}")
                if "error" in data:
                    log_fn(f"[verbose] API error: {data.get('error')} — {data.get('error_description', '')}")

            results = data.get("results", [])

            if verbose:
                type_counts: dict[str, int] = {}
                for dev in results:
                    t = _deviation_media_type(dev) or "unknown"
                    type_counts[t] = type_counts.get(t, 0) + 1
                log_fn(f"[verbose] page returned {len(results)} items — types: {type_counts}")
                if results:
                    log_fn(f"[verbose] first item keys: {list(results[0].keys())}")
                log_fn(f"[verbose] has_more={data.get('has_more')}  next_offset={data.get('next_offset')}")

            if not results:
                if verbose:
                    log_fn("[verbose] empty results — stopping pagination")
                break

            for dev in results:
                dev_type = _deviation_media_type(dev)
                if media_type in ("images", "both") and dev_type == "image":
                    items.append(dev)
                elif media_type in ("videos", "both") and dev_type == "film":
                    items.append(dev)

            pbar.update(1)
            pbar.set_postfix_str(f"found: {len(items)}")

            if not data.get("has_more", False):
                break
            offset = data.get("next_offset", offset + page_size)
            time.sleep(0.2)

    log_fn(f"Found {len(items)} deviations with media.")
    return items


def fetch_user_gallery(token, username, max_pages=25, page_size=24,
                        log_fn=print, media_type="both", verbose=False):
    log_fn(f"Scanning gallery of {username}…")
    return _fetch_feed(GALLERY_URL, token, username, max_pages, page_size, log_fn, media_type,
                       verbose=verbose)


def fetch_user_favourites(token, username, max_pages=25, page_size=24,
                           log_fn=print, media_type="both", verbose=False):
    log_fn(f"Scanning favourites of {username}…")
    return _fetch_feed(FAVOURITES_URL, token, username, max_pages, page_size, log_fn, media_type,
                       verbose=verbose)


# ── Download helpers ───────────────────────────────────────────────────────────

def _get_deviation_download_url(token: str, deviationid: str) -> tuple[str, str] | None:
    """Return (url, ext) for the full-resolution download, or None if unavailable."""
    try:
        resp = requests.get(
            f"{DOWNLOAD_URL}/{deviationid}",
            headers={"Authorization": f"Bearer {token}"},
            params={"mature_content": "true"},
            timeout=10,
        )
        if resp.status_code == 200:
            data     = resp.json()
            src      = data.get("src")
            filename = data.get("filename", "")
            ext      = filename.rsplit(".", 1)[-1].lower() if "." in filename else "jpg"
            if src:
                return src, ext
    except Exception:
        pass
    return None


def _download_video(url: str, output_template: str):
    import yt_dlp

    opts = {
        "format":              "bestvideo+bestaudio/best",
        "merge_output_format": "mp4",
        "outtmpl":             output_template,
        "quiet":               True,
        "no_warnings":         True,
    }
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        if os.path.isfile(os.path.join(sys._MEIPASS, "ffmpeg")):
            opts["ffmpeg_location"] = sys._MEIPASS

    with yt_dlp.YoutubeDL(opts) as ydl:
        ydl.download([url])


# ── Main download function ─────────────────────────────────────────────────────

def download_media(deviations, token, download_dir, media_type="both",
                   log_fn=print, error_fn=None, cancel_fn=None,
                   progress_fn=None, file_progress_fn=None, preview_fn=None,
                   delay_min=0.5, delay_max=2.0, convert_webp=None):
    """
    Download images and/or videos from a list of deviation objects.

    media_type:       "images" | "videos" | "both"
    convert_webp:     None | "png" | "jpg" — convert WebP images after download (requires Pillow)
    error_fn:         called for per-file errors; defaults to log_fn
    cancel_fn:        optional callable; stops when it returns True
    progress_fn:      called with (done_count, total_count) after each file
    file_progress_fn: called with (filename, bytes_done, bytes_total) during streaming
    preview_fn:       called with (filepath) after each successful save
    delay_min/max:    seconds to sleep between deviations; uniform random otherwise
    returns:          {"images": N, "videos": N, "bytes": N}
    """
    if error_fn is None:
        error_fn = log_fn

    os.makedirs(download_dir, exist_ok=True)
    tty = sys.stdout is not None and sys.stdout.isatty()

    total = len(deviations)
    if progress_fn:
        progress_fn(0, total)

    done_count  = 0
    images_ok   = 0
    videos_ok   = 0
    bytes_total = 0

    for dev in tqdm(deviations, desc="Downloading", unit="deviation", disable=not tty):
        if cancel_fn and cancel_fn():
            log_fn("Download cancelled.")
            return {"images": images_ok, "videos": videos_ok, "bytes": bytes_total}

        dev_type = _deviation_media_type(dev)
        author   = sanitize_filename(dev.get("author", {}).get("username", "unknown"))
        title    = sanitize_filename(dev.get("title", "untitled"))[:40]
        dev_id   = str(dev.get("deviationid", "noid"))
        short_id = dev_id.replace("-", "")[:12]
        ts       = format_timestamp(dev.get("published_time", 0))

        if dev_type == "image":
            content     = dev.get("content", {})
            content_url = content.get("src", "")

            # Prefer full-resolution download URL; fall back to content.src
            download_info = None
            if dev.get("is_downloadable") and dev_id != "noid":
                download_info = _get_deviation_download_url(token, dev_id)

            if download_info:
                img_url, ext = download_info
            elif content_url:
                img_url = content_url
                ext     = _image_ext_from_url(content_url)
            else:
                error_fn(f"No image URL for: {title}")
                done_count += 1
                if progress_fn:
                    progress_fn(done_count, total)
                continue

            fname = f"{author}_{ts}_{title}_{short_id}.{ext}"
            fpath = os.path.join(download_dir, fname)
            if os.path.exists(fpath):
                done_count += 1
                if progress_fn:
                    progress_fn(done_count, total)
                continue

            try:
                r = requests.get(img_url, stream=True, timeout=60)
                r.raise_for_status()
                total_size = int(r.headers.get("Content-Length", 0))
                # Correct extension from Content-Type if needed
                ct = r.headers.get("Content-Type", "")
                if ct.startswith("image/"):
                    ct_ext = ct.split("/")[-1].split(";")[0].strip()
                    if ct_ext in ("jpeg", "jpg", "png", "gif", "webp"):
                        ext   = "jpg" if ct_ext == "jpeg" else ct_ext
                        fname = f"{author}_{ts}_{title}_{short_id}.{ext}"
                        fpath = os.path.join(download_dir, fname)
                if file_progress_fn:
                    file_progress_fn(fname, 0, total_size)
                downloaded_bytes = 0
                with open(fpath, "wb") as f:
                    for chunk in r.iter_content(chunk_size=8192):
                        if chunk:
                            f.write(chunk)
                            downloaded_bytes += len(chunk)
                            if file_progress_fn:
                                file_progress_fn(fname, downloaded_bytes, total_size)
                if convert_webp and ext == "webp":
                    new_path = _convert_image(fpath, convert_webp)
                    if new_path:
                        os.remove(fpath)
                        fpath = new_path
                        fname = os.path.basename(fpath)
                        downloaded_bytes = os.path.getsize(fpath)
                        log_fn(f"Saved image (converted to {convert_webp.upper()}): {fname}")
                    else:
                        log_fn(f"Saved image (WebP conversion failed — Pillow missing?): {fname}")
                else:
                    log_fn(f"Saved image: {fname}")
                images_ok   += 1
                bytes_total += downloaded_bytes
                done_count  += 1
                if progress_fn:
                    progress_fn(done_count, total)
                if preview_fn:
                    preview_fn(fpath)
            except Exception as e:
                error_fn(f"Image failed ({title}): {e}")
                done_count += 1
                if progress_fn:
                    progress_fn(done_count, total)

        elif dev_type == "film":
            dev_url = dev.get("url", "")
            videos  = dev.get("videos", [])
            direct  = _best_video_url(videos)

            if direct:
                # Primary path: stream directly from the CDN URL in the videos array.
                # yt-dlp's DeviantArt extractor is unreliable for newer URL formats.
                vid_src, expected_size = direct
                url_path = vid_src.split("?")[0]
                vid_ext  = url_path.rsplit(".", 1)[-1].lower() if "." in url_path else "mp4"
                if vid_ext not in ("mp4", "webm", "mov", "avi", "mkv"):
                    vid_ext = "mp4"
                fname = f"{author}_{ts}_{title}_{short_id}_v.{vid_ext}"
                fpath = os.path.join(download_dir, fname)
                if os.path.exists(fpath):
                    done_count += 1
                    if progress_fn:
                        progress_fn(done_count, total)
                    continue
                if file_progress_fn:
                    file_progress_fn(fname, 0, 0)
                try:
                    r = requests.get(vid_src, stream=True, timeout=120)
                    r.raise_for_status()
                    total_size = int(r.headers.get("Content-Length", expected_size))
                    if file_progress_fn:
                        file_progress_fn(fname, 0, total_size)
                    downloaded_bytes = 0
                    with open(fpath, "wb") as fh:
                        for chunk in r.iter_content(chunk_size=65536):
                            if chunk:
                                fh.write(chunk)
                                downloaded_bytes += len(chunk)
                                if file_progress_fn:
                                    file_progress_fn(fname, downloaded_bytes, total_size)
                    log_fn(f"Saved video: {fname}")
                    videos_ok   += 1
                    bytes_total += downloaded_bytes
                    done_count  += 1
                    if progress_fn:
                        progress_fn(done_count, total)
                    if preview_fn:
                        preview_fn(fpath)
                except Exception as e:
                    error_fn(f"Video failed ({title}): {e}")
                    done_count += 1
                    if progress_fn:
                        progress_fn(done_count, total)

            elif dev_url:
                # Fallback: let yt-dlp attempt to extract from the deviation page URL.
                fname   = f"{author}_{ts}_{title}_{short_id}_v.mp4"
                out_tpl = os.path.join(download_dir, f"{author}_{ts}_{title}_{short_id}_v.%(ext)s")
                fpath   = os.path.join(download_dir, fname)
                if os.path.exists(fpath):
                    done_count += 1
                    if progress_fn:
                        progress_fn(done_count, total)
                    continue
                if file_progress_fn:
                    file_progress_fn(fname, 0, 0)
                try:
                    _download_video(dev_url, out_tpl)
                    log_fn(f"Saved video: {fname}")
                    videos_ok  += 1
                    done_count += 1
                    if progress_fn:
                        progress_fn(done_count, total)
                    if os.path.exists(fpath):
                        bytes_total += os.path.getsize(fpath)
                    if preview_fn and os.path.exists(fpath):
                        preview_fn(fpath)
                except Exception as e:
                    error_fn(f"Video failed ({title}): {e}")
                    done_count += 1
                    if progress_fn:
                        progress_fn(done_count, total)

            else:
                error_fn(f"No video URL for: {title}")
                done_count += 1
                if progress_fn:
                    progress_fn(done_count, total)

        time.sleep(random.uniform(delay_min, delay_max))

    return {"images": images_ok, "videos": videos_ok, "bytes": bytes_total}


# ── CLI entry point ────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="DeviantArt media downloader",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Modes:
  gallery    Download deviations from a user's gallery
  favourites Download deviations favourited by a user

Examples:
  python dadownload.py --mode gallery --user someartist
  python dadownload.py --mode favourites --user someartist --media images --pages 10

Register a DeviantArt app to get your client_id and client_secret:
  https://www.deviantart.com/developers/
        """,
    )
    parser.add_argument("--mode",   choices=["gallery", "favourites"], default="gallery")
    parser.add_argument("--user",   metavar="USERNAME", required=True,
                        help="Target DeviantArt username")
    parser.add_argument("--media",  choices=["images", "videos", "both"], default="both")
    parser.add_argument("--pages",  type=int, default=25, metavar="N",
                        help="Max pages to scan — 24 deviations per page (default: 25)")
    parser.add_argument("--output", metavar="DIR", default=DEFAULT_DOWNLOAD_DIR)
    parser.add_argument("--client-id",     metavar="ID",
                        help="DeviantArt client ID (override config)")
    parser.add_argument("--client-secret", metavar="SECRET",
                        help="DeviantArt client secret (override config)")
    parser.add_argument("--verbose", "-v", action="store_true",
                        help="Print detailed API request/response info for debugging")
    args = parser.parse_args()

    cfg           = load_config()
    client_id     = args.client_id     or cfg.get("credentials", "client_id", fallback=None)
    client_secret = args.client_secret or get_client_secret(cfg)

    if not client_id or not client_secret:
        print("Error: credentials not found.")
        print(f"  Configure {CONFIG_FILE}:")
        print("  [credentials]")
        print("  client_id = your_client_id")
        print("  client_secret = your_client_secret")
        print()
        print("  Or pass --client-id and --client-secret on the command line.")
        print()
        print("  Register an app at: https://www.deviantart.com/developers/")
        sys.exit(1)

    print("Getting access token…")
    try:
        token = get_or_refresh_token(client_id, client_secret)
    except Exception as e:
        print(f"Authentication failed: {e}")
        sys.exit(1)
    print("Authenticated.")

    if args.mode == "gallery":
        items = fetch_user_gallery(
            token, args.user, max_pages=args.pages, media_type=args.media,
            verbose=args.verbose,
        )
    else:
        items = fetch_user_favourites(
            token, args.user, max_pages=args.pages, media_type=args.media,
            verbose=args.verbose,
        )

    print(f"Downloading {len(items)} deviations → {args.output}")
    download_media(items, token, args.output, media_type=args.media)
    print("Done.")
