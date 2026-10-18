import json
import logging
import os
import shutil
import sqlite3
import flet as ft
from pathlib import Path
from typing import Callable
from mytunes.cache.lru_cache import DEFAULT_CACHE_DIR
from mytunes.core.media_artwork import ARTWORK_CACHE_DIR
from mytunes.providers.local import CACHE_DIR as LOCAL_ARTWORK_CACHE_DIR
from mytunes.providers.local import LocalProvider
from mytunes.ui.theme import MetroTheme, METRO_ACCENTS
from mytunes.ui.dialog_utils import safe_update, show_snackbar

logger = logging.getLogger(__name__)


class SettingsView(ft.Container):
    """
    Settings View for theme customization, audio preferences, and library folders.
    """

    def __init__(
        self,
        page: ft.Page,
        theme: MetroTheme,
        on_theme_changed: Callable[[], None],
        db_conn: sqlite3.Connection,
        local_provider: LocalProvider,
        on_library_updated: Callable[[], None],
        cloud_view: ft.Control | None = None,
    ):
        super().__init__()
        self.app_page = page
        self._mt = theme
        self.on_theme_changed = on_theme_changed
        self.conn = db_conn
        self.local_provider = local_provider
        self.on_library_updated = on_library_updated
        self.cloud_view = cloud_view
        self.scan_folders = self._load_scan_folders()
        self.is_scanning = False
        self.folder_picker = ft.FilePicker()

        self.expand = True
        self.padding = ft.Padding.all(28)

        self._build_view()

    def _build_view(self) -> None:
        title = ft.Text("SETTINGS", size=24, weight=ft.FontWeight.W_800, color=self._mt.text_primary)

        # 1. Appearance Section
        dark_mode_switch = ft.Switch(
            label="Dark Mode",
            value=self._mt.is_dark,
            on_change=self._toggle_dark_mode
        )

        accent_chips = []
        for name, hex_code in METRO_ACCENTS.items():
            is_selected = (self._mt.accent_color == hex_code)
            chip = ft.Container(
                width=32,
                height=32,
                bgcolor=hex_code,
                border=ft.Border.all(2, ft.Colors.WHITE if is_selected else ft.Colors.TRANSPARENT),
                border_radius=0, # Metro square color tiles
                ink=True,
                tooltip=name,
                on_click=lambda e, c=hex_code: self._change_accent(c)
            )
            accent_chips.append(chip)

        accents_row = ft.Row(spacing=10, controls=accent_chips)

        theme_card = ft.Container(
            bgcolor=self._mt.surface_color,
            border=ft.Border.all(1, self._mt.border_color),
            padding=20,
            border_radius=4,
            content=ft.Column(
                spacing=16,
                controls=[
                    ft.Text("Appearance & Metro Theme", size=16, weight=ft.FontWeight.BOLD),
                    dark_mode_switch,
                    ft.Text("Metro Accent Color", size=13, weight=ft.FontWeight.W_500),
                    accents_row,
                    ft.Text(
                        "Note: When playing songs with album covers, the dynamic color extractor will automatically adapt the player accent.",
                        size=12,
                        color=self._mt.text_secondary
                    )
                ]
            )
        )

        # 2. Audio & Cache Section
        cache_card = ft.Container(
            bgcolor=self._mt.surface_color,
            border=ft.Border.all(1, self._mt.border_color),
            padding=20,
            border_radius=4,
            content=ft.Column(
                spacing=12,
                controls=[
                    ft.Text("Audio & Caching", size=16, weight=ft.FontWeight.BOLD),
                    ft.Text(
                        "Clears cached audio, artwork, artist metadata, and podcast results. "
                        "Offline downloads and subscriptions are kept.",
                        size=13,
                        color=self._mt.text_secondary,
                    ),
                    ft.FilledButton("Clear App Caches", icon=ft.Icons.DELETE_SWEEP, on_click=self._clear_cache),
                ]
            )
        )

        # 3. Music Library
        self.folder_list = ft.Column(spacing=8)
        self.scan_status = ft.Text(
            "Scanning only happens when you request it.",
            size=12,
            color=self._mt.text_secondary,
        )
        self.add_folder_button = ft.OutlinedButton(
            "Add Folder",
            icon=ft.Icons.FOLDER_OPEN,
            on_click=self._on_add_folder,
        )
        self.scan_folders_button = ft.FilledButton(
            "Scan Folders",
            icon=ft.Icons.REFRESH,
            on_click=lambda e: self._start_scan(self.scan_folders),
        )
        music_card = ft.Container(
            bgcolor=self._mt.surface_color,
            border=ft.Border.all(1, self._mt.border_color),
            padding=20,
            border_radius=4,
            content=ft.Column(
                spacing=12,
                controls=[
                    ft.Text("Music Library Folders", size=16, weight=ft.FontWeight.BOLD),
                    ft.Text(
                        "Manage folders to include in your library. MyTunes will not scan them on startup.",
                        size=13,
                        color=self._mt.text_secondary,
                    ),
                    self.folder_list,
                    ft.Row(
                        controls=[self.add_folder_button, self.scan_folders_button],
                        spacing=10,
                    ),
                    self.scan_status,
                ],
            ),
        )

        # 3. About MyTunes
        about_card = ft.Container(
            bgcolor=self._mt.surface_color,
            border=ft.Border.all(1, self._mt.border_color),
            padding=20,
            border_radius=4,
            content=ft.Column(
                spacing=8,
                controls=[
                    ft.Text("MyTunes v0.1.0", size=16, weight=ft.FontWeight.BOLD),
                    ft.Text("Multiplatform Music Player built with Python & Flet (Flutter).", size=13, color=self._mt.text_secondary),
                    ft.Text("Local Library • Cloud Drives • Podcasts • 30k+ Radio Stations • Metro UI", size=12, color=ft.Colors.GREY_500),
                ]
            )
        )

        settings_sections: list[ft.Control] = [
            title,
            theme_card,
            cache_card,
            music_card,
        ]
        if self.cloud_view is not None:
            settings_sections.append(self.cloud_view)
        settings_sections.append(about_card)

        self.content = ft.Column(
            expand=True,
            scroll=ft.ScrollMode.AUTO,
            spacing=20,
            controls=settings_sections,
        )
        self._render_scan_folders()

    def _load_scan_folders(self) -> list[str]:
        row = self.conn.execute(
            "SELECT value FROM settings WHERE key = ?",
            ("music_scan_folders",),
        ).fetchone()
        if row is None:
            return []

        folders = json.loads(row[0])
        if not isinstance(folders, list) or not all(isinstance(path, str) for path in folders):
            raise ValueError("The saved music scan folders setting must be a list of paths.")
        return folders

    def _save_scan_folders(self) -> None:
        self.conn.execute(
            "INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)",
            ("music_scan_folders", json.dumps(self.scan_folders)),
        )
        self.conn.commit()

    def _render_scan_folders(self) -> None:
        self.folder_list.controls.clear()
        if not self.scan_folders:
            self.folder_list.controls.append(
                ft.Text("No folders added yet.", size=13, color=self._mt.text_secondary)
            )
        else:
            for folder in self.scan_folders:
                self.folder_list.controls.append(
                    ft.Row(
                        alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                        controls=[
                            ft.Text(folder, size=13, expand=True, selectable=True),
                            ft.IconButton(
                                icon=ft.Icons.REFRESH,
                                tooltip="Scan this folder",
                                disabled=self.is_scanning,
                                on_click=lambda e, path=folder: self._start_scan([path]),
                            ),
                            ft.IconButton(
                                icon=ft.Icons.DELETE_OUTLINE,
                                tooltip="Remove folder",
                                disabled=self.is_scanning,
                                on_click=lambda e, path=folder: self._remove_scan_folder(path),
                            ),
                        ],
                    )
                )
        self.scan_folders_button.disabled = self.is_scanning or not self.scan_folders
        self.add_folder_button.disabled = self.is_scanning

    async def _on_add_folder(self, e) -> None:
        path = await self.folder_picker.get_directory_path(dialog_title="Add Music Folder")
        if not path:
            return

        normalized_path = os.path.normpath(path)
        existing_paths = {os.path.normcase(os.path.normpath(folder)) for folder in self.scan_folders}
        if os.path.normcase(normalized_path) in existing_paths:
            show_snackbar(self.app_page, "That folder is already in your music library folders.")
            return

        self.scan_folders.append(normalized_path)
        self._save_scan_folders()
        self._render_scan_folders()
        self.scan_status.value = "Folder added. Choose when to scan it."
        safe_update(self)

    def _remove_scan_folder(self, path: str) -> None:
        if self.is_scanning:
            show_snackbar(self.app_page, "Wait for the current scan to finish before removing a folder.")
            return

        remaining_folders = [folder for folder in self.scan_folders if folder != path]
        try:
            local_tracks = self.conn.execute(
                "SELECT id, file_path FROM tracks WHERE source = 'local'"
            ).fetchall()
            track_ids_to_remove = [
                row["id"]
                for row in local_tracks
                if self._path_is_within(row["file_path"], path)
                and not any(
                    self._path_is_within(row["file_path"], folder)
                    for folder in remaining_folders
                )
            ]

            with self.conn:
                self.conn.execute(
                    "INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)",
                    ("music_scan_folders", json.dumps(remaining_folders)),
                )
                self.conn.executemany(
                    "DELETE FROM tracks WHERE id = ?",
                    ((track_id,) for track_id in track_ids_to_remove),
                )
        except sqlite3.Error as error:
            logger.exception("Failed to remove music scan folder %r.", path)
            show_snackbar(self.app_page, f"Could not remove folder from the library: {error}")
            return

        self.scan_folders = remaining_folders
        self._render_scan_folders()
        self.on_library_updated()
        show_snackbar(
            self.app_page,
            f"Folder removed; {len(track_ids_to_remove)} track(s) de-indexed. Music files were kept.",
        )
        safe_update(self)

    @staticmethod
    def _path_is_within(file_path: str, folder_path: str) -> bool:
        """Checks whether a file path is inside a scan root, including the root itself."""
        try:
            file_path = os.path.normcase(os.path.abspath(os.path.normpath(file_path)))
            folder_path = os.path.normcase(os.path.abspath(os.path.normpath(folder_path)))
            return os.path.commonpath((file_path, folder_path)) == folder_path
        except (OSError, ValueError):
            return False

    def _start_scan(self, folders: list[str]) -> None:
        if self.is_scanning or not folders:
            return

        self.is_scanning = True
        self.scan_status.value = f"Scanning {len(folders)} folder(s)..."
        self._render_scan_folders()
        safe_update(self)
        self.app_page.run_thread(self._scan_folders, list(folders))

    def _scan_folders(self, folders: list[str]) -> None:
        scanned_tracks = 0
        errors: list[str] = []
        for folder in folders:
            if not os.path.isdir(folder):
                errors.append(f"Folder not found: {folder}")
                continue
            try:
                scanned_tracks += len(self.local_provider.scan_directory(folder))
            except Exception as error:
                errors.append(f"{folder}: {error}")

        self.app_page.run_task(self._finish_scan, scanned_tracks, errors)

    async def _finish_scan(self, scanned_tracks: int, errors: list[str]) -> None:
        self.is_scanning = False
        self.on_library_updated()
        self._render_scan_folders()
        if errors:
            self.scan_status.value = f"Scanned {scanned_tracks} track(s); {len(errors)} folder(s) failed."
            show_snackbar(self.app_page, errors[0])
        else:
            self.scan_status.value = f"Scan complete: {scanned_tracks} track(s) found."
        safe_update(self)

    def _toggle_dark_mode(self, e) -> None:
        self._mt.is_dark = e.control.value
        self.app_page.theme_mode = ft.ThemeMode.DARK if self._mt.is_dark else ft.ThemeMode.LIGHT
        self.on_theme_changed()

    def _change_accent(self, color_hex: str) -> None:
        self._mt.accent_color = color_hex
        self._mt.reset_dynamic_accent()
        self.on_theme_changed()

    def _clear_cache(self, e) -> None:
        cache_directories = {
            Path(DEFAULT_CACHE_DIR),
            Path(ARTWORK_CACHE_DIR),
            Path(LOCAL_ARTWORK_CACHE_DIR),
        }
        removed_entries = 0
        try:
            for cache_dir in cache_directories:
                if cache_dir.is_symlink():
                    cache_dir.unlink()
                    removed_entries += 1
                elif cache_dir.is_dir():
                    entries = list(cache_dir.iterdir())
                    for entry in entries:
                        if entry.is_dir() and not entry.is_symlink():
                            shutil.rmtree(entry)
                        else:
                            entry.unlink()
                    removed_entries += len(entries)
                cache_dir.mkdir(parents=True, exist_ok=True)

            artwork_cache = Path(LOCAL_ARTWORK_CACHE_DIR)
            cached_art_tracks = [
                row["id"]
                for row in self.conn.execute(
                    "SELECT id, artwork_path FROM tracks WHERE artwork_path IS NOT NULL"
                ).fetchall()
                if self._path_is_within(row["artwork_path"], str(artwork_cache))
            ]
            with self.conn:
                self.conn.execute("DELETE FROM artist_metadata")
                self.conn.execute("DELETE FROM podcast_search_cache")
                self.conn.execute("DELETE FROM podcast_feed_cache")
                self.conn.executemany(
                    "UPDATE tracks SET artwork_path = NULL WHERE id = ?",
                    ((track_id,) for track_id in cached_art_tracks),
                )
        except (OSError, sqlite3.Error) as error:
            logger.exception("Failed to clear application caches.")
            show_snackbar(self.app_page, f"Could not clear all app caches: {error}")
            return

        self.on_library_updated()
        show_snackbar(
            self.app_page,
            f"App caches cleared ({removed_entries} cache entries). Offline downloads and media files were kept.",
        )
        safe_update(self)
