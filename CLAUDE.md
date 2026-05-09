# DeviantArtDownload — Claude Context

## Project at a glance

Personal Python tool to download media (images + videos) from DeviantArt using the official OAuth2 REST API.
Two entry points: a CLI (`dadownload.py`) and a PyQt6 GUI (`gui.py`).

- **GitHub:** https://github.com/Tamalero/deviantartDownload
- **Platform:** Arch/CachyOS, x86_64
- **Python:** system Python 3 (no virtualenv — all deps via pacman)
- **XDG config:** `~/.config/deviantartdownload/config.ini`
- **Default output:** `~/Pictures/DeviantArtDownload`
- **Latest release:** v1.1.0 — https://github.com/Tamalero/deviantartDownload/releases/tag/v1.1.0

---

## Repository state (as of 2026-05-08, updated 2026-05-09, code updated 2026-05-09)

Git is initialized. Remote is `https://github.com/Tamalero/deviantartDownload.git`, branch `main`.

Committed files:

```
.gitignore
CLAUDE.md
build_appimage.sh          ← AppImage Type 2 build script (executable)
dadownload.py              ← main CLI + shared library
deviantartdownload.desktop ← XDG desktop entry for AppImage
deviantartdownload.svg     ← SVG icon source (dark bg, green "DA" text)
gui.py                     ← PyQt6 GUI (imports dadownload)
requirements.txt
```

**Not committed** (covered by `.gitignore`): `config.ini`, `secret.key`, `credentials.txt`,
`__pycache__/`, `Downloads/`, `Downloaded_images/`, `*.AppImage`, `*.AppImage.zsync`,
`*.AppDir/`, `dist/`, `build/`, `*.spec`

---

## DeviantArt app registration

The tool requires a registered DeviantArt application to obtain OAuth2 credentials:

- **Registration URL:** https://www.deviantart.com/developers/
- **App type:** **Confidential (server side)** — this is the only type that provides both a
  client ID and a client secret. "Public (browser side)" only gives a client ID.
- **OAuth2 Redirect URI Whitelist:** must include `http://localhost:8765/callback` — this is
  the local callback address used by the Authorization Code flow. Add it exactly as written
  (HTTP, port 8765, path `/callback`).
- **client_id:** numeric ID assigned on registration (e.g. `12345`)
- **client_secret:** hex string shown immediately after registration — copy it then; it is not
  shown again after navigating away

### DA developer portal fields (complete list)

Title, Description, OAuth2 Redirect URI Whitelist, Client type, Download URL, Original URL
Whitelist. There are **no** grant type or response type toggles — all grant types are available
for Confidential apps.

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

### AppImage build dependencies

| Tool | Install |
|---|---|
| `python-pyinstaller` | `sudo pacman -S python-pyinstaller` or `pip install --user --break-system-packages pyinstaller` |
| `librsvg` | `sudo pacman -S librsvg` (provides `rsvg-convert` for icon conversion) |
| `fuse2` | `sudo pacman -S fuse2` (required to run the resulting AppImage) |
| `appimagetool` | downloaded automatically from GitHub if not in PATH; cached as `appimagetool-x86_64.AppImage` |

---

## Running

```bash
# GUI (from source)
python gui.py

# GUI (from AppImage)
./DeviantArtDownload-1.0.0-x86_64.AppImage

# CLI — user gallery
python dadownload.py --mode gallery --user someartist

# CLI — user favourites, images only, verbose debug output
python dadownload.py --mode favourites --user someartist --media images --pages 10 --verbose

# Build AppImage
bash build_appimage.sh
```

---

## AppImage packaging

The project ships as a **Type 2 AppImage** (SquashFS + ELF runtime).

### Build script: `build_appimage.sh`

Reads `VERSION` dynamically from the `dadownload` module. Full pipeline:

1. **Check PyInstaller** — errors with install instructions if missing
2. **Clean** previous `build/`, `dist/`, `*.AppDir/` artifacts
3. **PyInstaller** (`--onedir --windowed`) with:
   - `--collect-all yt_dlp` — bundles yt-dlp plugin tree
   - `--hidden-import cryptography.fernet` — not auto-detected by PyInstaller
   - 20 `--exclude-module` flags for heavy unused system packages (torch, torchvision,
     torchaudio, scipy, numpy, pandas, matplotlib, sympy, PIL, Pillow, sklearn, tensorflow,
     keras, jinja2, lxml, gi, pytest, pygments, IPython, ipykernel, notebook)
4. **Assemble AppDir** — copies PyInstaller onedir output to `AppDir/usr/bin/`; writes
   `AppRun` launcher script; copies `.desktop` entry
5. **Generate icon** — tries `rsvg-convert` → `inkscape` → `convert` (ImageMagick) → Python
   stdlib fallback (writes a raw 256×256 RGB PNG). Copies icon as both
   `deviantartdownload.png` and `.DirIcon`
6. **Locate or download `appimagetool`** — checks PATH first, then local cached file, then
   downloads from GitHub releases and caches
7. **Build AppImage** with embedded update info:
   ```
   gh-releases-zsync|Tamalero|deviantartDownload|latest|DeviantArtDownload-*-x86_64.AppImage.zsync
   ```
   Output: `DeviantArtDownload-<version>-x86_64.AppImage` (~117 MB)

> **Note on PEP 668 (Arch Linux):** system Python blocks `pip install --user pyinstaller`
> without `--break-system-packages`. Use:
> `pip install --user --break-system-packages pyinstaller`

### AppDir structure

```
DeviantArtDownload.AppDir/
  AppRun                          ← bash launcher; prepends usr/bin to PATH
  deviantartdownload.desktop
  deviantartdownload.png          ← 256×256 PNG converted from SVG
  .DirIcon                        ← copy of the PNG (AppImage spec)
  usr/bin/
    DeviantArtDownload            ← PyInstaller ELF launcher
    _internal/                   ← Python stdlib + all bundled packages
```

### zsync delta updates

`appimagetool --updateinformation` embeds the update URI so AppImageUpdate-compatible tools
can delta-patch to newer versions using the `.AppImage.zsync` companion file attached to
each GitHub release.

### ffmpeg in AppImage

System `ffmpeg` (from pacman) is used at runtime — it is **not** bundled in the AppImage.
To bundle it, uncomment the `--add-binary` line in `build_appimage.sh`. The `_download_video`
function only sets `ffmpeg_location` to `sys._MEIPASS` if an `ffmpeg` binary is actually
present there (`os.path.isfile` check).

---

## Update checker

### `dadownload.py` constants

```python
GITHUB_REPO = "Tamalero/deviantartDownload"
_GITHUB_API = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
```

### `check_for_update() → (tag | None, url | None)`

GETs `_GITHUB_API` with a 5-second timeout. Returns `(tag_without_v, release_html_url)` or
`(None, None)` on network failure, non-200 response, or no releases.

### `_version_tuple(v: str) → tuple[int, ...]`

Splits a version string on `.` and returns a tuple of ints for comparison. Falls back to
`(0,)` on any parse error.

### `UpdateChecker(QThread)` in `gui.py`

| Signal | Signature | Emitted when |
|---|---|---|
| `update_available` | `(str, str)` | Latest release tag > current VERSION |
| `up_to_date` | `()` | Latest release tag ≤ current VERSION |

- **Automatic check**: started once in `showEvent` on first window show; stored in
  `self._update_checker`. Silent on network failure (no signal emitted if `tag is None`).
- **Manual check**: `Help → Check for Updates` triggers `_check_updates_manual()` which
  creates `self._manual_checker` and connects both signals.

### Status bar update label

A `QLabel` (`self._update_label`) is added as a permanent status bar widget. Hidden until an
update is detected. When shown:
```html
<a href="{release_url}" style="color: #05cc47;">↑ v{version} available</a>
```
`setOpenExternalLinks(True)` — clicking opens the release page in the system browser.

---

## Authentication flow

### OAuth 2.1 — Authorization Code + PKCE (current)

DeviantArt **requires PKCE** for all newly registered apps (OAuth 2.1). The tool uses the
**Authorization Code** grant with S256 PKCE, which authenticates as the user's DA account
(enabling mature content access). A one-time browser login is required; the resulting token
pair is stored encrypted in config and refreshed automatically.

**Why auth code instead of client_credentials:**
`client_credentials` returns a token with no user identity. DeviantArt blocks mature content
for these tokens with `{"error": "unauthorized", "error_description": "Content blocked due to
user's mature content setting"}`, regardless of `mature_content=true` in the request. The user's
DA account must have mature content viewing enabled and be age-verified on DA's side.

**Authorization flow:**

```
1. GET https://www.deviantart.com/oauth2/authorize
     ?response_type=code
     &client_id=<id>
     &redirect_uri=http://localhost:8765/callback
     &scope=browse
     &state=<random_hex>
     &code_challenge=<base64url(SHA256(code_verifier))>
     &code_challenge_method=S256

   → DA opens browser login page → user approves → DA redirects to localhost:8765/callback?code=...

2. POST https://www.deviantart.com/oauth2/token
     grant_type=authorization_code
     client_id=<id>
     client_secret=<secret>
     code=<code>
     redirect_uri=http://localhost:8765/callback
     code_verifier=<original_random_verifier>

   → { "access_token": "...", "refresh_token": "...", "expires_in": 3600, ... }
```

**Token refresh (automatic):**
```
POST https://www.deviantart.com/oauth2/token
  grant_type=refresh_token
  client_id=<id>
  client_secret=<secret>
  refresh_token=<refresh_token>
```

Token lifetime is ~1 hour. Refresh happens automatically on next Start if expired (GUI) or
on next CLI invocation via `get_or_refresh_token`. Re-auth via browser is only needed if the
refresh token is also expired or revoked.

`scope=browse` is required — omitting it results in 403 on gallery/collections endpoints.

### PKCE implementation detail

```python
code_verifier  = base64.urlsafe_b64encode(os.urandom(32)).rstrip(b"=").decode()
code_challenge = base64.urlsafe_b64encode(
    hashlib.sha256(code_verifier.encode()).digest()
).rstrip(b"=").decode()
```

Uses only Python stdlib (`base64`, `hashlib`, `os`) — no extra dependencies.

### `client_credentials` (legacy, kept for reference)

`get_access_token(client_id, client_secret)` still exists in `dadownload.py` but is no longer
called by the GUI or CLI. It cannot access mature content.

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
| `GITHUB_REPO` | `"Tamalero/deviantartDownload"` — used by update checker and About dialog |
| `_GITHUB_API` | GitHub Releases API URL constructed from `GITHUB_REPO` |
| `CONFIG_FILE` | `Path` to `~/.config/deviantartdownload/config.ini` |
| `KEY_FILE` | `Path` to `~/.config/deviantartdownload/secret.key` (Fernet key, mode 600) |
| `DEFAULT_DOWNLOAD_DIR` | `~/Pictures/DeviantArtDownload` |
| `TOKEN_URL` | `https://www.deviantart.com/oauth2/token` |
| `AUTH_URL` | `https://www.deviantart.com/oauth2/authorize` |
| `REDIRECT_PORT` | `8765` — localhost port for OAuth2 callback; whitelist `http://localhost:8765/callback` in DA app |
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
| `get_access_token(id, secret)` | Legacy `client_credentials` grant — kept but not called by GUI/CLI; cannot access mature content |
| `get_access_token_auth_code(id, secret, port, log_fn)` | OAuth2 Authorization Code + PKCE flow — opens browser, runs local callback server on `port`, returns full token dict |
| `refresh_access_token(id, secret, refresh_token)` | Exchange refresh token for new access token; returns token dict |
| `save_token(token_data)` | Encrypts and persists `access_token`, `refresh_token`, `token_expires_at` to `[credentials]` config section |
| `load_token(cfg)` | Returns `(access_token, refresh_token, expires_at)` from loaded config; decrypts values |
| `get_or_refresh_token(id, secret, log_fn)` | CLI helper — returns valid token from config, refreshes if expired, re-authorizes via browser if refresh fails |
| `sanitize_filename(text)` | Strip non-alphanumeric chars (keep `_` and `-`) |
| `format_timestamp(unix_ts)` | Unix timestamp → `YYYYMMDD_HHMMSS` string |
| `_image_ext_from_url(url)` | Best-effort extension from CDN URL path |
| `_best_video_url(videos)` | Pick highest-quality entry from deviation `videos` array → `(url, filesize)` or `None`; used to bypass yt-dlp for direct CDN streaming |
| `_deviation_media_type(dev)` | Infer `"image"` / `"film"` / `""` from deviation fields (`content`, `videos`, `is_downloadable`) — DA API does not send a `type` field |
| `_version_tuple(v)` | Split version string → `tuple[int, ...]` for comparison |
| `check_for_update()` | GET GitHub Releases API → `(tag, url)` or `(None, None)` |
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

#### Auth countdown timer

`MainWindow` owns a `QTimer` (`self._auth_timer`, 10 s interval) that calls `_tick_auth_status()` while the window is open. The timer is a no-op when `self._token_expires_at == 0` (never authorized) or `self._authorizing is True` (browser flow in progress, avoids overwriting the "Authorizing…" label).

`_update_auth_status(expires_at)` stores the value and applies thresholds:

| Remaining | Color | Text |
|---|---|---|
| > 15 min | `#05cc47` green | `Authorized · expires in X min` |
| 5–15 min | `#f8c800` yellow | `Authorized · expires in X min` |
| < 5 min | `#ff5555` red | `Authorized · expires in Xm YYs` |
| expired | `#ff9900` orange | `Token expired — click Authorize…` |

`self._authorizing` is set `True` in `_authorize()` and cleared in `_on_authorized()` / `_on_auth_error()`.

#### `AuthWorker(QThread)`

| Signal | Signature | Purpose |
|---|---|---|
| `authorized` | `int` | Auth succeeded: `expires_at` unix timestamp |
| `auth_error` | `str` | Auth failed: error message |
| `log` | `str` | Progress messages (forwarded to log panel) |

Runs `da.get_access_token_auth_code()` in background, calls `da.save_token()` on success,
emits `authorized(expires_at)`. Started by clicking "Authorize with DeviantArt…".

#### `UpdateChecker(QThread)`

| Signal | Signature | Purpose |
|---|---|---|
| `update_available` | `(str, str)` | New version detected: `(tag, release_url)` |
| `up_to_date` | `()` | Current version is latest |

Started automatically on first `showEvent`; also triggered manually via Help menu.

#### `MainWindow(QMainWindow)` — UI layout

```
Menu bar               (Help → Check for Updates, Help → About)
Credentials Group      (client_id, client_secret [password field], auth status label,
                        Authorize button, deviantart.com/developers link)
Options Group          (mode, username, media type, pages, post delay, verbose checkbox)
Output Folder Group    (path + Browse button)
Start / Cancel buttons
Progress Group         (total bar + count label, file bar + filename/size label)
QSplitter (horizontal, non-collapsible):
  ├── Preview Group    (QLabel — scales with panel, KeepAspectRatio)
  └── Log Group        (QTextEdit — read-only, monospace, HTML-colored)
StatusBar              (left: messages, right: update link label — hidden until update detected)
```

#### Help menu (`_build_menu`)

- **Check for Updates** → `_check_updates_manual()` — fires a fresh `UpdateChecker`; shows
  "Checking for updates…" in status bar; on result shows either the update label or
  "Already up to date."
- **About v{VERSION}** → `_show_about()` — `QMessageBox.about` with version, description,
  and link to `github.com/{GITHUB_REPO}`

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

#### Credentials group auth flow

- `_lbl_auth_status`: green "Authorized · expires in N min" / orange "Token expired" / red "Not authorized"
- `_btn_authorize`: starts `AuthWorker`; disabled while auth is in progress
- `_authorize()`: validates fields, saves client_id/secret, starts `AuthWorker`
- `_on_authorized(expires_at)`: re-enables button, calls `_update_auth_status`
- `_on_auth_error(msg)`: re-enables button, shows error in red
- `_update_auth_status(expires_at)`: updates label color and text from `time.time()` comparison
- `_load_saved_credentials()`: loads client_id, client_secret, then calls `_update_auth_status` with stored `expires_at`

#### `_start()` token resolution

1. Load `(access_token, refresh_token, expires_at)` via `da.load_token()`
2. If `access_token` valid and not expired → use it
3. Elif `refresh_token` exists → call `da.refresh_access_token()` inline (synchronous), save, update status label
4. Else → show error "Not authorized. Click Authorize first." and return
5. Pass resolved token as `cfg["access_token"]` to `DownloadWorker` — worker does **not** fetch its own token

#### Config persistence

- `[credentials]`: `client_id` (plaintext), `client_secret` (Fernet-encrypted), `access_token`
  (Fernet-encrypted), `refresh_token` (Fernet-encrypted), `token_expires_at` (plaintext unix
  timestamp) — credentials saved on Authorize/Start; token fields saved by `da.save_token()`
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

- **Token expiry / refresh:** access tokens expire after ~1 hour. The GUI refreshes automatically
  on Start if a refresh_token is stored. CLI uses `get_or_refresh_token` which also auto-refreshes.
  Full re-auth (browser) is only needed if the refresh token itself expires or is revoked.
- **Mature content requires user account setup:** `mature_content=true` is effective only when
  the authenticated DA account has mature content viewing enabled in DA account settings AND is
  age-verified on DA. The Authorization Code flow carries the user's session, so this is now
  user-controlled rather than app-controlled.
- **Empty results investigation:** verbose mode was added because the app initially returned 0
  deviations. The `[verbose]` per-page type breakdown (now based on `_deviation_media_type`)
  shows whether DA is returning items that can't be classified. The verbose block also logs
  `first item keys` to inspect the actual response shape when debugging.
- **Video downloads:** primary path streams directly from `dev["videos"][N]["src"]` (highest
  quality chosen by `_best_video_url`), using the same chunked-streaming path as images — so
  the file progress bar works for videos too. yt-dlp is a fallback only for the rare case where
  `videos` has no `src` but a page URL is present. Fixed "Unsupported URL" errors that appeared
  with newer long-ID DA URLs (yt-dlp's DA extractor did not handle them).
- **Private content:** the auth code token grants access to the authenticated user's own private
  deviations/collections if they are the target username. Other users' private content remains
  inaccessible.
- **No cross-run dedup:** skips files if the output filename already exists on disk.
- **Literature/Flash:** silently skipped (not downloaded).
- **AppImage size:** ~117 MB after excluding heavy system packages from PyInstaller. If new
  system packages are installed globally that trigger PyInstaller hooks, the bundle can grow;
  re-add `--exclude-module` flags as needed.
- **AppImage auth flow:** the OAuth2 browser flow works from AppImage as-is since it uses
  `webbrowser.open()` and a local HTTP server — no GUI browser dependency.

---

## Differences from BlueSkyDownload

| Aspect | BlueSkyDownload | DeviantArtDownload |
|---|---|---|
| Auth | Handle + App Password (AT Protocol) | Client ID + Client Secret + OAuth2 Authorization Code + PKCE (user browser login) |
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
| Update checker | Yes (GitHub Releases API) | Yes — GUI (Help menu + status bar) + `check_for_update()` in CLI module |
| AppImage | No | Yes — `build_appimage.sh`, published at v1.0.0 |
| Verbose mode | No | Yes (checkbox + `--verbose` CLI flag) |
