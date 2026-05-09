# DeviantArtDownload — Claude Context

## Project at a glance

Personal Python tool to download media (images + videos) from DeviantArt using the official OAuth2 REST API.
Two entry points: a CLI (`dadownload.py`) and a PyQt6 GUI (`gui.py`).

- **GitHub:** https://github.com/Tamalero/deviantartDownload
- **Platform:** Arch/CachyOS, x86_64
- **Python:** system Python 3 (no virtualenv — all deps via pacman)
- **XDG config:** `~/.config/deviantartdownload/config.ini`
- **Default output:** `~/Pictures/DeviantArtDownload`
- **Latest release:** v1.0.0

---

## Repository state (as of 2026-05-08, updated 2026-05-08)

Git is initialized. Remote is `https://github.com/Tamalero/deviantartDownload.git`, branch `main`.

Committed files:

```
.gitignore
CLAUDE.md
dadownload.py         ← main CLI + shared library
gui.py                ← PyQt6 GUI (imports dadownload)
requirements.txt
```

**Not committed** (covered by `.gitignore`): `config.ini`, `secret.key`, `__pycache__/`,
`Downloads/`, `Downloaded_images/`, `*.AppImage`, `*.AppDir/`, `dist/`, `build/`, `*.spec`

---

## DeviantArt app registration

The tool requires a registered DeviantArt application to obtain OAuth2 credentials:

- **Registration URL:** https://www.deviantart.com/developers/
- **App type:** **Confidential (server side)** — this is the only type that provides both a
  client ID and a client secret. "Public (browser side)" only gives a client ID.
- **OAuth2 Redirect URI Whitelist:** set to `https://localhost` (placeholder — never actually
  called because the tool uses `client_credentials` grant, which has no redirect)
- **client_id:** numeric ID assigned on registration (e.g. `12345`)
- **client_secret:** hex string shown immediately after registration — copy it then; it is not
  shown again after navigating away

---

## System dependencies (all installed via pacman)

| Package | Status |
|---|---|
| `python-requests` | installed |
| `python-tqdm` | installed |
| `python-pyqt6` | installed |
| `python-cryptography` | installed |
| `yt-dlp` | installed |
| `ffmpeg` | installed |

---

## Running

```bash
# GUI
python gui.py

# CLI — user gallery
python dadownload.py --mode gallery --user someartist

# CLI — user favourites, images only, verbose debug output
python dadownload.py --mode favourites --user someartist --media images --pages 10 --verbose
```

---

## Authentication flow

DeviantArt uses OAuth2. The tool uses the **client_credentials** grant — no user browser login
is required. A fresh token is fetched at the start of every download session.

```
POST https://www.deviantart.com/oauth2/token
  client_id=<id>
  client_secret=<secret>
  grant_type=client_credentials

→ { "access_token": "...", "token_type": "Bearer", "expires_in": 3600, ... }
```

Token lifetime is typically 1 hour. Long downloads may hit expiry; no automatic refresh is
implemented — the token is fetched once per session and reused.

All subsequent API calls send `Authorization: Bearer <access_token>` and include
`mature_content=true` to include NSFW deviations (requires the app to have that permission
enabled in DA developer settings).

---

## DeviantArt API endpoints

Base URL: `https://www.deviantart.com/api/v1/oauth2/`

| Endpoint | Used for |
|---|---|
| `POST /oauth2/token` | Exchange client credentials for access token |
| `GET /api/v1/oauth2/gallery/all` | All deviations in a user's gallery (paginated) |
| `GET /api/v1/oauth2/collections/all` | All favourited deviations of a user (paginated) |
| `GET /api/v1/oauth2/deviation/download/{deviationid}` | Full-resolution download URL for a deviation |

### Pagination

Both gallery and favourites use **offset-based** pagination (not cursor-based):

- Request params: `username`, `limit` (max 24), `offset`, `mature_content`
- Response fields: `results` (array), `has_more` (bool), `next_offset` (int)
- Loop stops when `has_more` is false or `results` is empty
- 0.2 s sleep between page requests to avoid rate limiting

### Deviation object structure (relevant fields)

```json
{
  "deviationid": "UUID-string",
  "title":       "Artwork Title",
  "url":         "https://www.deviantart.com/artist/art/title-123456",
  "published_time": 1234567890,
  "author":      { "username": "artistname", ... },
  "content":     { "src": "https://cdn...", "width": N, "height": N, "filesize": N },
  "is_downloadable": true,
  "is_mature":   false,
  "videos":      []
}
```

**Important:** The DA API does **not** include a `type` field in deviation objects. Media type
is inferred from the presence of other fields via `_deviation_media_type()`:

- `videos` array non-empty → `"film"`
- `content` dict present **or** `is_downloadable` is true → `"image"`
- neither → `""` (literature, flash, etc. — silently skipped)

Only `"image"` and `"film"` deviations are downloaded.

### Full-resolution download

For `type == "image"` deviations where `is_downloadable` is true, the tool calls
`/deviation/download/{deviationid}` which returns:

```json
{ "src": "https://download.deviantart.net/...", "filename": "title.png", "filesize": N, "type": "png" }
```

The extension is parsed from `filename`. If the download endpoint fails or returns non-200,
the tool falls back to `content.src` (the display-resolution CDN URL).

---

## Code architecture

### `dadownload.py` — core module + CLI

All functions are importable (no module-level side effects). `__main__` block handles CLI via `argparse`.

| Symbol | Purpose |
|---|---|
| `VERSION` | Current version string (`"1.0.0"`) |
| `CONFIG_FILE` | `Path` to `~/.config/deviantartdownload/config.ini` |
| `KEY_FILE` | `Path` to `~/.config/deviantartdownload/secret.key` (Fernet key, mode 600) |
| `DEFAULT_DOWNLOAD_DIR` | `~/Pictures/DeviantArtDownload` |
| `TOKEN_URL` | `https://www.deviantart.com/oauth2/token` |
| `GALLERY_URL` | `https://www.deviantart.com/api/v1/oauth2/gallery/all` |
| `FAVOURITES_URL` | `https://www.deviantart.com/api/v1/oauth2/collections/all` |
| `DOWNLOAD_URL` | `https://www.deviantart.com/api/v1/oauth2/deviation/download` |
| `load_config()` | Reads full config (credentials + last_run sections) |
| `save_config(id, secret)` | Read-modify-write; encrypts client_secret before storing |
| `save_ui_state(dict)` | Writes `[last_run]` section without touching credentials |
| `_get_or_create_key()` | Returns Fernet key bytes; generates + saves key file on first call |
| `encrypt_password(pw)` | Fernet-encrypt a string → base64 token |
| `decrypt_password(token)` | Decrypt Fernet token; returns `None` if token looks like Fernet but key is wrong/missing; returns token unchanged for legacy plaintext (migration path) |
| `get_client_secret(cfg)` | Read + decrypt `client_secret` from loaded config; returns `None` if absent or undecryptable |
| `get_access_token(id, secret)` | POST client_credentials → returns access token string |
| `sanitize_filename(text)` | Strip non-alphanumeric chars (keep `_` and `-`) |
| `format_timestamp(unix_ts)` | Unix timestamp → `YYYYMMDD_HHMMSS` string |
| `_image_ext_from_url(url)` | Best-effort extension from CDN URL path |
| `_deviation_media_type(dev)` | Infer `"image"` / `"film"` / `""` from deviation fields (`content`, `videos`, `is_downloadable`) — DA API does not send a `type` field |
| `_fetch_feed(url, token, username, ...)` | Shared offset pagination loop; client-side filters by deviation media type |
| `fetch_user_gallery(token, username, ...)` | Wraps `_fetch_feed` → `gallery/all` |
| `fetch_user_favourites(token, username, ...)` | Wraps `_fetch_feed` → `collections/all` |
| `_get_deviation_download_url(token, id)` | Calls `/deviation/download/{id}`; returns `(url, ext)` or `None` |
| `_download_video(url, output_template)` | Downloads via `yt_dlp` Python API using the deviation page URL |
| `download_media(deviations, token, dir, ...)` | Downloads images (streaming) and videos (yt-dlp); returns stats dict |

#### `download_media` full signature

```python
def download_media(deviations, token, download_dir, media_type="both",
                   log_fn=print, error_fn=None, cancel_fn=None,
                   progress_fn=None, file_progress_fn=None, preview_fn=None,
                   delay_min=0.5, delay_max=2.0):
```

**Return value:** `{"images": N, "videos": N, "bytes": N}` — partial stats also returned on cancel.

#### Callback parameters

| Parameter | Type | Purpose |
|---|---|---|
| `log_fn` | `str → None` | Normal log messages (default: `print`) |
| `error_fn` | `str → None` | Per-file error messages; defaults to `log_fn` |
| `cancel_fn` | `() → bool` | Download stops when this returns `True` |
| `progress_fn` | `(int, int) → None` | Called with `(done_count, total_count)` after each file |
| `file_progress_fn` | `(str, int, int) → None` | Called with `(filename, bytes_done, bytes_total)` during streaming |
| `preview_fn` | `str → None` | Called with the saved file path after each successful download |
| `delay_min` | `float` | Minimum seconds between deviations (default: 0.5) |
| `delay_max` | `float` | Maximum seconds between deviations (default: 2.0) |

Sleep uses `random.uniform(delay_min, delay_max)` — when min == max this is a fixed delay.

#### Verbose mode

`_fetch_feed` accepts `verbose=False`. When `True`, `log_fn` is called with `[verbose]`-prefixed
lines for each page showing:

- Full request URL and base params (once at start)
- Offset for each page request
- HTTP status code
- Response top-level keys
- API error field if present
- Per-page item count broken down by deviation type (e.g. `{'image': 12, 'literature': 4}`)
- `has_more` and `next_offset` values
- "empty results — stopping pagination" on early exit

`fetch_user_gallery` and `fetch_user_favourites` both accept and forward `verbose`.

CLI flag: `--verbose` / `-v`. GUI: "Show detailed API output (for debugging)" checkbox in
the Download Options group.

#### `decrypt_password` — key-loss safety

Same pattern as BlueSkyDownload:
1. Valid Fernet token + correct key → returns plaintext
2. Looks like Fernet token (`startswith("gAAAAA")`) but decryption fails → returns `None`
3. Does not look like Fernet → returns token unchanged (legacy plaintext migration path)

`get_client_secret` returns `None` in case 2. The GUI leaves the Client Secret field empty and
shows a status bar warning when this happens.

### `gui.py` — PyQt6 frontend

Imports `dadownload as da`. No logic lives here — only UI wiring.

#### `DownloadWorker(QThread)`

| Signal | Signature | Purpose |
|---|---|---|
| `log` | `str` | Normal log line |
| `error` | `str` | Error log line (rendered red) |
| `done` | `(bool, str)` | Download finished: `(success, message)` |
| `progress` | `(int, int)` | `(done_count, total_count)` for overall bar |
| `file_progress` | `(str, int, int)` | `(filename, bytes_done, bytes_total)` for file bar |
| `preview` | `str` | File path of the latest successfully saved file |

`cancel()` sets `self._stop = True`; `download_media` checks it between deviations via `cancel_fn`.

After `download_media` returns, the worker emits a summary line:
```
── Summary ──  Images: N  │  Videos: N  │  Total: N files  │  X.X MB
```

#### `MainWindow(QMainWindow)` — UI layout

```
Credentials Group      (client_id, client_secret [password field], deviantart.com/developers link)
Options Group          (mode, username, media type, pages, post delay, verbose checkbox)
Output Folder Group    (path + Browse button)
Start / Cancel buttons
Progress Group         (total bar + count label, file bar + filename/size label)
QSplitter (horizontal, non-collapsible):
  ├── Preview Group    (QLabel — scales with panel, KeepAspectRatio)
  └── Log Group        (QTextEdit — read-only, monospace, HTML-colored)
StatusBar
```

No menu bar (no update checker — no GitHub releases yet).

#### Download Options fields

| Field | Widget | Notes |
|---|---|---|
| Mode | `QComboBox` | "User Gallery" \| "User Favourites" |
| Username | `QLineEdit` | Placeholder: `e.g.  tamalero  (username only, no URL)` |
| Media Type | `QComboBox` | "Both" \| "Images Only" \| "Videos Only" |
| Max Pages | `QSpinBox` | 1–200, default 25, suffix `  pages  (~24 deviations each)` |
| Post Delay | composite widget | Fixed/Variable spinboxes (same as BlueSkyDownload) |
| Verbose | `QCheckBox` | "Show detailed API output (for debugging)" |

`verbose` is not persisted to `[last_run]` — it defaults to unchecked on every launch.

#### Post Delay widget

Identical to BlueSkyDownload:
- `cb_delay_type`: "Fixed" | "Variable"
- Fixed mode: `dsb_delay_fixed` (0–60 s, default 1.0 s)
- Variable mode: `dsb_delay_min` (default 0.5 s) + `dsb_delay_max` (default 2.0 s)
- Visibility toggled by `_on_delay_type_changed`

#### Config persistence

- `[credentials]`: `client_id` (plaintext), `client_secret` (Fernet-encrypted) — saved on Start
- `[last_run]`: `mode`, `username`, `media`, `pages`, `output`, `delay_type`, `delay_fixed`,
  `delay_min`, `delay_max` — saved on Start; `verbose` is NOT persisted
- Both sections use read-modify-write via `save_config` / `save_ui_state`

#### Splitter ratio — screen-responsive

| Screen height | Preview | Log | Stretch |
|---|---|---|---|
| ≤ 1080 px | 30 % | 70 % | 3 : 7 |
| > 1080 px | 50 % | 50 % | 1 : 1 |

#### Log coloring

- Normal: `html.escape(msg)` as plain text
- Errors: `<span style="color: #ff5555;">…</span>`
- "Cancelled." uses plain text; all other failure messages use red

---

## Output filename format

```
{author}_{YYYYMMDD_HHMMSS}_{safe_title}_{short_id}.{ext}     # images
{author}_{YYYYMMDD_HHMMSS}_{safe_title}_{short_id}_v.mp4     # videos
```

- `author`: `deviation.author.username`, sanitized (non-alphanumeric → `_`)
- `YYYYMMDD_HHMMSS`: from `deviation.published_time` (Unix timestamp, UTC)
- `safe_title`: `deviation.title`, sanitized, truncated to **40 chars**
- `short_id`: first 12 hex chars of `deviationid` UUID (hyphens stripped)
- `ext`: from `/deviation/download` filename, or inferred from `content.src` URL, or corrected
  from `Content-Type` header at download time; `"jpeg"` is normalized to `"jpg"`

---

## Known limitations / open issues

- **Token expiry:** client_credentials tokens expire after ~1 hour. No auto-refresh; very long
  sessions will fail with 401 after expiry.
- **Empty results investigation:** verbose mode was added because the app initially returned 0
  deviations. The `[verbose]` per-page type breakdown (now based on `_deviation_media_type`)
  shows whether DA is returning items that can't be classified. The verbose block also logs
  `first item keys` to inspect the actual response shape when debugging.
- **Mature content:** `mature_content=true` is sent on all requests but requires the registered
  app to have the `browse` scope with mature content enabled in DA developer settings. Without
  it, mature deviations will be omitted silently by the API.
- **Video downloads:** uses yt-dlp with the deviation page `url` field (not a direct video URL).
  yt-dlp must be installed via pacman. Progress bar shows indeterminate for videos (no byte
  callback from yt-dlp).
- **Private content:** client_credentials grant cannot access private deviations or private
  collections — only public content is visible.
- **No cross-run dedup:** skips files if the output filename already exists on disk.
- **Literature/Flash:** silently skipped (not downloaded).

---

## Differences from BlueSkyDownload

| Aspect | BlueSkyDownload | DeviantArtDownload |
|---|---|---|
| Auth | Handle + App Password (AT Protocol) | Client ID + Client Secret (OAuth2 client_credentials) |
| Core module | `apitest.py` | `dadownload.py` |
| Mode 1 | Liked Posts | User Favourites |
| Mode 2 | User Gallery | User Gallery |
| Target field | Optional (blank = own account) | Required (DA API always needs a username) |
| Page size | 50 posts | 24 deviations (DA API max) |
| Pagination | Cursor-based | Offset-based (`has_more` + `next_offset`) |
| Images | CDN `fullsize` URL | Full-res via `/deviation/download`, fallback to `content.src` |
| Videos | HLS playlist via yt-dlp | Deviation page URL via yt-dlp |
| Config dir | `~/.config/blueskydownload/` | `~/.config/deviantartdownload/` |
| Default output | `~/Pictures/BlueSkyDownload` | `~/Pictures/DeviantArtDownload` |
| Update checker | Yes (GitHub Releases API) | No (no releases yet) |
| Verbose mode | No | Yes (checkbox + `--verbose` CLI flag) |
