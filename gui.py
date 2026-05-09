import html
import sys
import time
from pathlib import Path

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget,
    QVBoxLayout, QHBoxLayout, QFormLayout,
    QGroupBox, QLabel, QLineEdit, QPushButton,
    QComboBox, QSpinBox, QDoubleSpinBox, QFileDialog,
    QTextEdit, QStatusBar, QProgressBar, QSplitter, QSizePolicy,
    QMessageBox, QCheckBox,
)
from PyQt6.QtCore import QThread, pyqtSignal, Qt, QTimer, QUrl
from PyQt6.QtGui import QFont, QPixmap, QDesktopServices

import dadownload as da


# ── Background download worker ─────────────────────────────────────────────────

class DownloadWorker(QThread):
    log           = pyqtSignal(str)
    error         = pyqtSignal(str)
    done          = pyqtSignal(bool, str)
    progress      = pyqtSignal(int, int)        # (done_count, total)
    file_progress = pyqtSignal(str, int, int)   # (filename, bytes_done, bytes_total)
    preview       = pyqtSignal(str)             # filepath

    def __init__(self, cfg: dict):
        super().__init__()
        self.cfg   = cfg
        self._stop = False

    def cancel(self):
        self._stop = True

    def run(self):
        cfg = self.cfg
        try:
            token = cfg["access_token"]
            self.log.emit("Authenticated.")

            media_map  = {"Both": "both", "Images Only": "images", "Videos Only": "videos"}
            media_type = media_map[cfg["media"]]

            if cfg["mode"] == "User Gallery":
                deviations = da.fetch_user_gallery(
                    token, cfg["username"],
                    max_pages=cfg["pages"],
                    media_type=media_type,
                    log_fn=self.log.emit,
                    verbose=cfg["verbose"],
                )
            else:
                deviations = da.fetch_user_favourites(
                    token, cfg["username"],
                    max_pages=cfg["pages"],
                    media_type=media_type,
                    log_fn=self.log.emit,
                    verbose=cfg["verbose"],
                )

            stats = da.download_media(
                deviations,
                token,
                cfg["output"],
                media_type=media_type,
                log_fn=self.log.emit,
                error_fn=self.error.emit,
                cancel_fn=lambda: self._stop,
                progress_fn=lambda d, t: self.progress.emit(d, t),
                file_progress_fn=lambda fn, d, t: self.file_progress.emit(fn, d, t),
                preview_fn=self.preview.emit,
                delay_min=cfg["delay_min"],
                delay_max=cfg["delay_max"],
            )

            total_files = stats["images"] + stats["videos"]
            nb          = stats["bytes"]
            size_str    = (f"{nb / 1_048_576:.1f} MB" if nb >= 1_048_576
                           else f"{nb / 1024:.1f} KB")
            self.log.emit(
                f"── Summary ──  Images: {stats['images']}  │  "
                f"Videos: {stats['videos']}  │  "
                f"Total: {total_files} files  │  {size_str}"
            )

            if self._stop:
                self.done.emit(False, "Cancelled.")
            else:
                self.done.emit(True, f"Done — {total_files} files · {size_str}")

        except Exception as e:
            self.done.emit(False, str(e))


# ── Authorization worker ───────────────────────────────────────────────────────

class AuthWorker(QThread):
    authorized = pyqtSignal(int)   # expires_at (unix timestamp)
    auth_error = pyqtSignal(str)
    log        = pyqtSignal(str)

    def __init__(self, client_id: str, client_secret: str):
        super().__init__()
        self.client_id     = client_id
        self.client_secret = client_secret

    def run(self):
        try:
            token_data = da.get_access_token_auth_code(
                self.client_id, self.client_secret, log_fn=self.log.emit
            )
            da.save_token(token_data)
            expires_at = int(time.time()) + int(token_data.get("expires_in", 3600)) - 60
            self.authorized.emit(expires_at)
        except Exception as e:
            self.auth_error.emit(str(e))


# ── Update checker ─────────────────────────────────────────────────────────────

class UpdateChecker(QThread):
    update_available = pyqtSignal(str, str)  # (version, release_url)
    up_to_date       = pyqtSignal()

    def run(self):
        tag, url = da.check_for_update()
        if tag is None:
            return
        if da._version_tuple(tag) > da._version_tuple(da.VERSION):
            self.update_available.emit(tag, url)
        else:
            self.up_to_date.emit()


# ── Main window ────────────────────────────────────────────────────────────────

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"DeviantArt Downloader v{da.VERSION}")
        self.setMinimumWidth(640)
        self.worker: DownloadWorker | None  = None
        self._current_preview_pixmap: QPixmap | None = None
        self._update_checker: UpdateChecker | None = None
        self._manual_checker: UpdateChecker | None = None
        self._auth_worker:    AuthWorker    | None = None
        self._token_expires_at: int  = 0
        self._authorizing:      bool = False
        self._build_ui()
        self._load_saved_credentials()
        self._load_ui_state()

        # Countdown timer — ticks every 10 s, updates the auth status label
        self._auth_timer = QTimer(self)
        self._auth_timer.setInterval(10_000)
        self._auth_timer.timeout.connect(self._tick_auth_status)
        self._auth_timer.start()

    # ── UI construction ────────────────────────────────────────────────────────

    def _build_ui(self):
        self._build_menu()

        root = QWidget()
        self.setCentralWidget(root)
        layout = QVBoxLayout(root)
        layout.setSpacing(10)
        layout.setContentsMargins(14, 14, 14, 14)

        layout.addWidget(self._credentials_group())
        layout.addWidget(self._options_group())
        layout.addWidget(self._output_group())
        layout.addLayout(self._buttons_row())
        layout.addWidget(self._progress_group())

        self._bottom_splitter = QSplitter(Qt.Orientation.Horizontal)
        self._bottom_splitter.setChildrenCollapsible(False)
        self._bottom_splitter.addWidget(self._preview_group())
        self._bottom_splitter.addWidget(self._log_group())
        layout.addWidget(self._bottom_splitter, 1)

        self.statusbar = QStatusBar()
        self.setStatusBar(self.statusbar)

        self._update_label = QLabel()
        self._update_label.setOpenExternalLinks(True)
        self._update_label.setVisible(False)
        self.statusbar.addPermanentWidget(self._update_label)

        self.statusbar.showMessage("Ready")

    def _build_menu(self):
        mb = self.menuBar()
        help_menu = mb.addMenu("&Help")

        act_check = help_menu.addAction("Check for &Updates")
        act_check.triggered.connect(self._check_updates_manual)

        help_menu.addSeparator()

        act_about = help_menu.addAction(f"&About v{da.VERSION}")
        act_about.triggered.connect(self._show_about)

    def _credentials_group(self) -> QGroupBox:
        g = QGroupBox("Credentials")
        outer = QVBoxLayout(g)
        outer.setSpacing(8)

        info = QLabel(
            "<b>One-time setup required to download galleries:</b><br>"
            "① Register a <b>Confidential</b> app at "
            '<a href="https://www.deviantart.com/developers/">deviantart.com/developers</a> '
            "— add <code>http://localhost:8765/callback</code> to the Redirect URI whitelist.<br>"
            "② Enter the Client ID and Secret below, then click <b>Authorize</b>.<br>"
            "&nbsp;&nbsp;&nbsp;A browser window will open for a one-time login with your DeviantArt account.<br>"
            "③ <b>Mature content:</b> to download mature-rated images your DeviantArt account "
            "must have mature content viewing <b>enabled</b> and be <b>age-verified</b> "
            "in your DA account settings."
        )
        info.setWordWrap(True)
        info.setOpenExternalLinks(True)
        info.setStyleSheet("color: #bbbbbb; font-size: 11px; padding: 2px 0px;")
        outer.addWidget(info)

        f = QFormLayout()
        f.setContentsMargins(0, 4, 0, 0)
        self.le_client_id     = QLineEdit(placeholderText="Numeric ID (from deviantart.com/developers)")
        self.le_client_secret = QLineEdit(placeholderText="Hex secret — copy it right after registration")
        self.le_client_secret.setEchoMode(QLineEdit.EchoMode.Password)

        self._lbl_auth_status = QLabel("Not authorized")
        self._lbl_auth_status.setStyleSheet("color: #ff5555;")

        self._btn_authorize = QPushButton("Authorize with DeviantArt…")
        self._btn_authorize.clicked.connect(self._authorize)

        f.addRow("Client ID:", self.le_client_id)
        f.addRow("Client Secret:", self.le_client_secret)
        f.addRow("Auth status:", self._lbl_auth_status)
        f.addRow("", self._btn_authorize)
        outer.addLayout(f)
        return g

    def _options_group(self) -> QGroupBox:
        g = QGroupBox("Download Options")
        f = QFormLayout(g)

        self.cb_mode = QComboBox()
        self.cb_mode.addItems(["User Gallery", "User Favourites"])

        self.le_username = QLineEdit(placeholderText="e.g.  tamalero  (username only, no URL)")

        self.cb_media = QComboBox()
        self.cb_media.addItems(["Both", "Images Only", "Videos Only"])

        self.sp_pages = QSpinBox()
        self.sp_pages.setRange(1, 200)
        self.sp_pages.setValue(25)
        self.sp_pages.setSuffix("  pages  (~24 deviations each)")

        self.chk_verbose = QCheckBox("Show detailed API output (for debugging)")

        f.addRow("Mode:", self.cb_mode)
        f.addRow("Username:", self.le_username)
        f.addRow("Media Type:", self.cb_media)
        f.addRow("Max Pages:", self.sp_pages)
        f.addRow("Post Delay:", self._build_delay_widget())
        f.addRow("", self.chk_verbose)
        return g

    def _output_group(self) -> QGroupBox:
        g = QGroupBox("Output Folder")
        h = QHBoxLayout(g)
        self.le_output = QLineEdit(da.DEFAULT_DOWNLOAD_DIR)
        btn = QPushButton("Browse…")
        btn.setFixedWidth(80)
        btn.clicked.connect(self._browse_output)
        h.addWidget(self.le_output)
        h.addWidget(btn)
        return g

    def _buttons_row(self) -> QHBoxLayout:
        h = QHBoxLayout()
        self.btn_start  = QPushButton("Start Download")
        self.btn_cancel = QPushButton("Cancel")
        for btn in (self.btn_start, self.btn_cancel):
            btn.setFixedHeight(34)
        self.btn_cancel.setEnabled(False)
        self.btn_start.clicked.connect(self._start)
        self.btn_cancel.clicked.connect(self._cancel)
        h.addWidget(self.btn_start)
        h.addWidget(self.btn_cancel)
        return h

    def _progress_group(self) -> QGroupBox:
        g = QGroupBox("Progress")
        v = QVBoxLayout(g)
        v.setSpacing(4)

        h_overall = QHBoxLayout()
        lbl_total = QLabel("Total:")
        lbl_total.setFixedWidth(42)
        self.pb_overall = QProgressBar()
        self.pb_overall.setTextVisible(False)
        self.pb_overall.setFixedHeight(16)
        self.lbl_overall_count = QLabel("–")
        self.lbl_overall_count.setFixedWidth(90)
        self.lbl_overall_count.setAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        )
        h_overall.addWidget(lbl_total)
        h_overall.addWidget(self.pb_overall, 1)
        h_overall.addWidget(self.lbl_overall_count)

        h_current = QHBoxLayout()
        lbl_file = QLabel("File:")
        lbl_file.setFixedWidth(42)
        self.pb_current = QProgressBar()
        self.pb_current.setTextVisible(False)
        self.pb_current.setFixedHeight(16)
        h_current.addWidget(lbl_file)
        h_current.addWidget(self.pb_current, 1)

        self.lbl_current_file = QLabel("")
        self.lbl_current_file.setFont(QFont("Monospace", 8))

        v.addLayout(h_overall)
        v.addLayout(h_current)
        v.addWidget(self.lbl_current_file)
        return g

    def _preview_group(self) -> QGroupBox:
        g = QGroupBox("Preview")
        g.setMinimumWidth(150)
        v = QVBoxLayout(g)
        self.lbl_preview = QLabel("No preview")
        self.lbl_preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_preview.setMinimumSize(100, 150)
        self.lbl_preview.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        self.lbl_preview.setStyleSheet(
            "background-color: #1a1a2e; color: #666; border-radius: 4px;"
        )
        v.addWidget(self.lbl_preview)
        return g

    def _log_group(self) -> QGroupBox:
        g = QGroupBox("Log")
        v = QVBoxLayout(g)
        self.te_log = QTextEdit()
        self.te_log.setReadOnly(True)
        self.te_log.setFont(QFont("Monospace", 9))
        self.te_log.setMinimumHeight(160)
        v.addWidget(self.te_log)
        return g

    # ── Window events ──────────────────────────────────────────────────────────

    def showEvent(self, event):
        super().showEvent(event)
        self._apply_splitter_ratio()
        if self._update_checker is None:
            self._update_checker = UpdateChecker()
            self._update_checker.update_available.connect(self._on_update_available)
            self._update_checker.start()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._rescale_preview()

    def _apply_splitter_ratio(self):
        screen   = QApplication.primaryScreen()
        screen_h = screen.size().height() if screen else 1080

        if screen_h <= 1080:
            preview_ratio = 0.30
            self._bottom_splitter.setStretchFactor(0, 3)
            self._bottom_splitter.setStretchFactor(1, 7)
        else:
            preview_ratio = 0.50
            self._bottom_splitter.setStretchFactor(0, 1)
            self._bottom_splitter.setStretchFactor(1, 1)

        total = self._bottom_splitter.width()
        if total > 0:
            preview_w = int(total * preview_ratio)
            self._bottom_splitter.setSizes([preview_w, total - preview_w])

    # ── Slots ──────────────────────────────────────────────────────────────────

    def _on_update_available(self, version: str, url: str):
        self._update_label.setText(
            f'<a href="{url}" style="color: #05cc47;">&#8593; v{version} available</a>'
        )
        self._update_label.setVisible(True)
        self.statusbar.showMessage(
            f"Update available: v{version} — click the link in the status bar or use Help menu",
            8000,
        )

    def _check_updates_manual(self):
        self.statusbar.showMessage("Checking for updates…")
        self._manual_checker = UpdateChecker()
        self._manual_checker.update_available.connect(self._on_update_available)
        self._manual_checker.up_to_date.connect(
            lambda: self.statusbar.showMessage("Already up to date.", 4000)
        )
        self._manual_checker.start()

    def _show_about(self):
        QMessageBox.about(
            self,
            f"DeviantArt Downloader v{da.VERSION}",
            f"<b>DeviantArt Downloader</b> v{da.VERSION}<br><br>"
            "Download images and videos from DeviantArt using the official API.<br><br>"
            f'<a href="https://github.com/{da.GITHUB_REPO}">'
            f"github.com/{da.GITHUB_REPO}</a>",
        )

    def _authorize(self):
        client_id     = self.le_client_id.text().strip()
        client_secret = self.le_client_secret.text().strip()
        if not client_id or not client_secret:
            self._append_error("Client ID and Client Secret are required before authorizing.")
            return

        da.save_config(client_id, client_secret)

        self._authorizing = True
        self._btn_authorize.setEnabled(False)
        self._lbl_auth_status.setText("Authorizing… (check your browser)")
        self._lbl_auth_status.setStyleSheet("color: #f8f8a0;")
        self.statusbar.showMessage("Waiting for browser authorization…")

        self._auth_worker = AuthWorker(client_id, client_secret)
        self._auth_worker.log.connect(self._append_log)
        self._auth_worker.authorized.connect(self._on_authorized)
        self._auth_worker.auth_error.connect(self._on_auth_error)
        self._auth_worker.start()

    def _on_authorized(self, expires_at: int):
        self._authorizing = False
        self._btn_authorize.setEnabled(True)
        self._update_auth_status(expires_at)
        self.statusbar.showMessage("Authorized successfully.", 5000)

    def _on_auth_error(self, msg: str):
        self._authorizing = False
        self._btn_authorize.setEnabled(True)
        self._lbl_auth_status.setText("Authorization failed")
        self._lbl_auth_status.setStyleSheet("color: #ff5555;")
        self._append_error(f"Authorization failed: {msg}")
        self.statusbar.showMessage("Authorization failed.", 5000)

    def _tick_auth_status(self):
        """Called every 10 s by the countdown timer; no-op while authorizing or never authorized."""
        if not self._authorizing and self._token_expires_at > 0:
            self._update_auth_status(self._token_expires_at)

    def _update_auth_status(self, expires_at: int):
        self._token_expires_at = expires_at
        remaining = expires_at - int(time.time())
        if remaining > 900:       # > 15 min — green
            mins  = remaining // 60
            text  = f"Authorized · expires in {mins} min"
            color = "#05cc47"
        elif remaining > 300:     # 5–15 min — yellow
            mins  = remaining // 60
            text  = f"Authorized · expires in {mins} min"
            color = "#f8c800"
        elif remaining > 0:       # < 5 min — red, show mm:ss
            mins  = remaining // 60
            secs  = remaining % 60
            text  = (f"Authorized · expires in {mins}m {secs:02d}s"
                     if mins else f"Authorized · expires in {secs}s")
            color = "#ff5555"
        else:                     # expired — orange, actionable
            text  = "Token expired — click Authorize to re-authorize"
            color = "#ff9900"
        self._lbl_auth_status.setText(text)
        self._lbl_auth_status.setStyleSheet(f"color: {color};")

    def _build_delay_widget(self) -> QWidget:
        w = QWidget()
        h = QHBoxLayout(w)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(6)

        self.cb_delay_type = QComboBox()
        self.cb_delay_type.addItems(["Fixed", "Variable"])
        self.cb_delay_type.setFixedWidth(84)

        self.dsb_delay_fixed = QDoubleSpinBox()
        self.dsb_delay_fixed.setRange(0.0, 60.0)
        self.dsb_delay_fixed.setSingleStep(0.1)
        self.dsb_delay_fixed.setValue(1.0)
        self.dsb_delay_fixed.setSuffix(" s")
        self.dsb_delay_fixed.setFixedWidth(72)

        self.dsb_delay_min = QDoubleSpinBox()
        self.dsb_delay_min.setRange(0.0, 60.0)
        self.dsb_delay_min.setSingleStep(0.1)
        self.dsb_delay_min.setValue(0.5)
        self.dsb_delay_min.setSuffix(" s")
        self.dsb_delay_min.setFixedWidth(72)
        self.dsb_delay_min.setVisible(False)

        self._lbl_delay_to = QLabel("to")
        self._lbl_delay_to.setVisible(False)

        self.dsb_delay_max = QDoubleSpinBox()
        self.dsb_delay_max.setRange(0.0, 60.0)
        self.dsb_delay_max.setSingleStep(0.1)
        self.dsb_delay_max.setValue(2.0)
        self.dsb_delay_max.setSuffix(" s")
        self.dsb_delay_max.setFixedWidth(72)
        self.dsb_delay_max.setVisible(False)

        h.addWidget(self.cb_delay_type)
        h.addWidget(self.dsb_delay_fixed)
        h.addWidget(self.dsb_delay_min)
        h.addWidget(self._lbl_delay_to)
        h.addWidget(self.dsb_delay_max)
        h.addStretch()

        self.cb_delay_type.currentTextChanged.connect(self._on_delay_type_changed)
        return w

    def _on_delay_type_changed(self, mode: str):
        fixed = mode == "Fixed"
        self.dsb_delay_fixed.setVisible(fixed)
        self.dsb_delay_min.setVisible(not fixed)
        self._lbl_delay_to.setVisible(not fixed)
        self.dsb_delay_max.setVisible(not fixed)

    def _browse_output(self):
        path = QFileDialog.getExistingDirectory(
            self, "Select Output Folder", self.le_output.text()
        )
        if path:
            self.le_output.setText(path)

    def _load_saved_credentials(self):
        cfg = da.load_config()
        if cfg.has_option("credentials", "client_id"):
            self.le_client_id.setText(cfg.get("credentials", "client_id"))
        if cfg.has_option("credentials", "client_secret"):
            secret = da.get_client_secret(cfg)
            if secret is not None:
                self.le_client_secret.setText(secret)
            else:
                self.statusBar().showMessage(
                    "Saved client secret could not be decrypted — please re-enter it.", 8000
                )
        _, _, expires_at = da.load_token(cfg)
        self._update_auth_status(expires_at)

    def _load_ui_state(self):
        cfg = da.load_config()
        if not cfg.has_section("last_run"):
            return
        lr = cfg["last_run"]
        if "mode" in lr:
            idx = self.cb_mode.findText(lr["mode"])
            if idx >= 0:
                self.cb_mode.setCurrentIndex(idx)
        if "username" in lr:
            self.le_username.setText(lr["username"])
        if "media" in lr:
            idx = self.cb_media.findText(lr["media"])
            if idx >= 0:
                self.cb_media.setCurrentIndex(idx)
        if "pages" in lr:
            try:
                self.sp_pages.setValue(int(lr["pages"]))
            except ValueError:
                pass
        if "output" in lr:
            self.le_output.setText(lr["output"])
        if "delay_type" in lr:
            idx = self.cb_delay_type.findText(lr["delay_type"])
            if idx >= 0:
                self.cb_delay_type.setCurrentIndex(idx)
        for field, spinbox in [
            ("delay_fixed", self.dsb_delay_fixed),
            ("delay_min",   self.dsb_delay_min),
            ("delay_max",   self.dsb_delay_max),
        ]:
            if field in lr:
                try:
                    spinbox.setValue(float(lr[field]))
                except ValueError:
                    pass

    def _save_ui_state(self):
        da.save_ui_state({
            "mode":        self.cb_mode.currentText(),
            "username":    self.le_username.text().strip(),
            "media":       self.cb_media.currentText(),
            "pages":       str(self.sp_pages.value()),
            "output":      self.le_output.text().strip(),
            "delay_type":  self.cb_delay_type.currentText(),
            "delay_fixed": str(self.dsb_delay_fixed.value()),
            "delay_min":   str(self.dsb_delay_min.value()),
            "delay_max":   str(self.dsb_delay_max.value()),
        })

    def _append_log(self, msg: str):
        self.te_log.append(html.escape(msg))
        self._scroll_log()

    def _append_error(self, msg: str):
        self.te_log.append(
            f'<span style="color: #ff5555;">{html.escape(msg)}</span>'
        )
        self._scroll_log()

    def _scroll_log(self):
        sb = self.te_log.verticalScrollBar()
        sb.setValue(sb.maximum())

    def _update_progress(self, done: int, total: int):
        self.pb_overall.setMaximum(max(total, 1))
        self.pb_overall.setValue(done)
        self.lbl_overall_count.setText(f"{done} / {total} files")

    def _update_file_progress(self, fname: str, done: int, total: int):
        if total > 0:
            self.pb_current.setMaximum(total)
            self.pb_current.setValue(done)
            if total >= 1_048_576:
                size_str = f"{done / 1_048_576:.1f} / {total / 1_048_576:.1f} MB"
            else:
                size_str = f"{done / 1024:.1f} / {total / 1024:.1f} KB"
            self.lbl_current_file.setText(f"{fname}  ({size_str})")
        else:
            self.pb_current.setMaximum(0)
            self.pb_current.setValue(0)
            self.lbl_current_file.setText(fname)

    def _rescale_preview(self):
        if self._current_preview_pixmap and not self._current_preview_pixmap.isNull():
            size   = self.lbl_preview.size()
            scaled = self._current_preview_pixmap.scaled(
                size,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            self.lbl_preview.setPixmap(scaled)

    def _update_preview(self, filepath: str):
        pixmap = QPixmap(filepath)
        if not pixmap.isNull():
            self._current_preview_pixmap = pixmap
            self._rescale_preview()
        else:
            self._current_preview_pixmap = None
            self.lbl_preview.setText("▶ Video")

    def _start(self):
        client_id     = self.le_client_id.text().strip()
        client_secret = self.le_client_secret.text().strip()
        username      = self.le_username.text().strip()

        if not client_id or not client_secret:
            self._append_error("Client ID and Client Secret are required.")
            return
        if not username:
            self._append_error("Username is required.")
            return

        # Resolve a valid access token — refresh inline if expired, else ask to authorize
        cfg_data                            = da.load_config()
        access_token, refresh_token, expires_at = da.load_token(cfg_data)

        if access_token and time.time() < expires_at:
            token = access_token
        elif refresh_token:
            self.statusbar.showMessage("Refreshing token…")
            try:
                token_data = da.refresh_access_token(client_id, client_secret, refresh_token)
                da.save_token(token_data)
                token   = token_data["access_token"]
                new_exp = int(time.time()) + int(token_data.get("expires_in", 3600)) - 60
                self._update_auth_status(new_exp)
            except Exception as e:
                self._append_error(f"Token refresh failed: {e} — please re-authorize.")
                return
        else:
            self._append_error(
                'Not authorized. Click "Authorize with DeviantArt…" first.'
            )
            return

        da.save_config(client_id, client_secret)
        self._save_ui_state()

        if self.cb_delay_type.currentText() == "Fixed":
            d = self.dsb_delay_fixed.value()
            delay_min, delay_max = d, d
        else:
            delay_min = self.dsb_delay_min.value()
            delay_max = max(self.dsb_delay_max.value(), delay_min)

        cfg = {
            "client_id":     client_id,
            "client_secret": client_secret,
            "access_token":  token,
            "mode":          self.cb_mode.currentText(),
            "username":      username,
            "media":         self.cb_media.currentText(),
            "pages":         self.sp_pages.value(),
            "output":        self.le_output.text().strip(),
            "delay_min":     delay_min,
            "delay_max":     delay_max,
            "verbose":       self.chk_verbose.isChecked(),
        }

        self.te_log.clear()
        self.pb_overall.setMaximum(100)
        self.pb_overall.setValue(0)
        self.pb_current.setMaximum(100)
        self.pb_current.setValue(0)
        self.lbl_overall_count.setText("–")
        self.lbl_current_file.setText("")
        self._current_preview_pixmap = None
        self.lbl_preview.setText("No preview")

        self.btn_start.setEnabled(False)
        self.btn_cancel.setEnabled(True)
        self.statusbar.showMessage("Downloading…")

        self.worker = DownloadWorker(cfg)
        self.worker.log.connect(self._append_log)
        self.worker.error.connect(self._append_error)
        self.worker.done.connect(self._on_done)
        self.worker.progress.connect(self._update_progress)
        self.worker.file_progress.connect(self._update_file_progress)
        self.worker.preview.connect(self._update_preview)
        self.worker.start()

    def _cancel(self):
        if self.worker:
            self.worker.cancel()
        self.btn_cancel.setEnabled(False)
        self.statusbar.showMessage("Cancelling…")

    def _on_done(self, ok: bool, msg: str):
        self.btn_start.setEnabled(True)
        self.btn_cancel.setEnabled(False)
        if ok or msg == "Cancelled.":
            self._append_log(msg)
        else:
            self._append_error(msg)
        self.statusbar.showMessage(msg)
        self.lbl_current_file.setText("")
        self.pb_current.setMaximum(100)
        self.pb_current.setValue(0)


# ── Entry point ────────────────────────────────────────────────────────────────

def main():
    app = QApplication(sys.argv)
    app.setApplicationName("DeviantArt Downloader")
    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
