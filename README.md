# DeviantArt Downloader

Download images and videos from DeviantArt galleries and favourites using the official OAuth2 API.

Available as a **PyQt6 GUI** and a **command-line tool**.

---

## Features

- Download a user's full **gallery** or **favourites**
- **Images** — full-resolution download via the official `/deviation/download` endpoint (falls back to CDN URL)
- **Videos** — direct CDN streaming from the deviation's embedded video URL
- OAuth2 Authorization Code + PKCE login — authenticates as your DA account, enabling mature content access
- Automatic token refresh (re-login only needed when refresh token expires)
- **WebP → PNG/JPG conversion** — DeviantArt often serves WebP; convert on download
- Configurable post-delay between downloads (fixed or random range)
- File progress bar per download and overall progress counter
- In-app image preview after each save
- Auth status countdown (turns yellow → red as expiry approaches)
- Update checker via GitHub Releases API
- **Cancel stops immediately**, even mid-file — the partial file is discarded, not left behind

---

## Requirements

| Dependency | Install |
|---|---|
| Python 3.10+ | system |
| `python-requests` | `sudo pacman -S python-requests` |
| `python-pyqt6` | `sudo pacman -S python-pyqt6` |
| `python-cryptography` | `sudo pacman -S python-cryptography` |
| `python-tqdm` | `sudo pacman -S python-tqdm` |
| `python-pillow` | `sudo pacman -S python-pillow` (WebP conversion) |
| `yt-dlp` | `sudo pacman -S yt-dlp` |
| `ffmpeg` | `sudo pacman -S ffmpeg` |

> On non-Arch systems install the equivalent packages via your package manager or `pip`.

---

## Installation

### Option A — AppImage (recommended, Linux x86_64)

Download `DeviantArtDownload-<version>-x86_64.AppImage` from the [latest release](https://github.com/Tamalero/deviantartDownload/releases/latest), make it executable, and run:

```bash
chmod +x DeviantArtDownload-1.2.1-x86_64.AppImage
./DeviantArtDownload-1.2.1-x86_64.AppImage
```

> `ffmpeg` must still be installed on the host system — it is **not** bundled in the AppImage.

### Option B — From source

```bash
git clone https://github.com/Tamalero/deviantartDownload.git
cd deviantartDownload
python gui.py          # GUI
python dadownload.py --help   # CLI
```

---

## DeviantArt app setup (one-time)

The downloader requires an OAuth2 application registered on DeviantArt to obtain a Client ID and Client Secret.

1. Go to **https://www.deviantart.com/developers/** and click **Register your Application**.
2. Set **Client type** to **Confidential (server side)** — this is the only type that issues both a Client ID and a Client Secret.
3. Add the following to the **OAuth2 Redirect URI Whitelist** (exactly as shown):
   ```
   http://localhost:8765/callback
   ```
4. Save the application. Copy your **Client ID** (numeric) and **Client Secret** (hex string) — the secret is shown only once.

---

## Authentication

Paste your Client ID and Client Secret into the **Credentials** panel, then click **Authorize with DeviantArt**.

A browser window opens and prompts you to log in with your DeviantArt account. After approving access, the token is saved locally (Fernet-encrypted in `~/.config/deviantartdownload/config.ini`). You will not need to log in again until the refresh token expires.

### Mature content

To download mature-rated deviations your DeviantArt account must:

- Have **Mature Content** viewing enabled in DA account settings
- Be **age-verified** on DeviantArt

The downloader passes `mature_content=true` automatically; the above DA-side settings are what actually unlock access.

---

## Usage

### GUI

Launch the app (AppImage or `python gui.py`), fill in your credentials, select a mode and username, and click **Start Download**.

| Field | Description |
|---|---|
| Mode | **User Gallery** or **User Favourites** |
| Username | Target DeviantArt username (no URL, no `@`) |
| Media Type | Both / Images Only / Videos Only |
| Max Pages | How many pages to scan (24 deviations per page) |
| Post Delay | Pause between downloads — Fixed or random Variable range |
| WebP images | Convert downloaded WebP files to PNG or JPG |
| Output Folder | Where files are saved (default: `~/Pictures/DeviantArtDownload`) |

### CLI

```bash
# Download a user's gallery (images + videos)
python dadownload.py --mode gallery --user someartist

# Download favourites, images only, 10 pages
python dadownload.py --mode favourites --user someartist --media images --pages 10

# Show verbose API output for debugging
python dadownload.py --mode gallery --user someartist --verbose
```

Full options:

```
--mode      gallery | favourites
--user      DeviantArt username (required)
--media     images | videos | both  (default: both)
--pages     Max pages to scan, 24 deviations each (default: 25)
--output    Download directory (default: ~/Pictures/DeviantArtDownload)
--verbose   Print per-page API request/response detail
```

---

## Output filenames

```
{author}_{YYYYMMDD_HHMMSS}_{title}_{short_id}.{ext}      # images
{author}_{YYYYMMDD_HHMMSS}_{title}_{short_id}_v.mp4      # videos
```

- `author` — deviation author username, non-alphanumeric characters replaced with `_`
- `YYYYMMDD_HHMMSS` — deviation publish date (UTC)
- `title` — deviation title, sanitized, truncated to 40 characters
- `short_id` — first 12 hex characters of the deviation UUID

Files that already exist on disk are skipped.

---

## Config files

| Path | Contents |
|---|---|
| `~/.config/deviantartdownload/config.ini` | Client ID, encrypted secret, encrypted tokens, last-run UI state |
| `~/.config/deviantartdownload/secret.key` | Fernet encryption key (mode 600, auto-generated) |

These files are **not** committed — they are covered by `.gitignore`.

---

## Known limitations

- **Literature and Flash deviations** are silently skipped (not downloadable via the API).
- **Private content** — the token gives access to the authenticated user's own private deviations/collections only. Other users' private content remains inaccessible.
- **Cross-run deduplication** is filename-based only; the same file downloaded under a different name will be re-downloaded.
- **AppImage size** is ~126 MB (Python + Qt6 runtime). `ffmpeg` is not bundled; install it separately.

---

## License

Personal / private use. No license for redistribution.
