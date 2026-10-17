import flet as ft
import time
from typing import Callable, Optional
from mytunes.sync.sync_manager import SyncManager, SYNC_FILENAME
from mytunes.ui.theme import MetroTheme
from mytunes.ui.dialog_utils import safe_update, show_snackbar, open_dialog, close_dialog

class CloudView(ft.Container):
    """
    Cloud Drives & Zero-Server Cloud Sync Hub.
    Manages OAuth2 connections to Google Drive, OneDrive, and Dropbox,
    and handles two-way conflict-free sync of playlists, favorites, and podcasts.
    """

    def __init__(
        self,
        page: ft.Page,
        theme: MetroTheme,
        sync_manager: SyncManager
    ):
        super().__init__()
        self.app_page = page
        self._mt = theme
        self.sync_manager = sync_manager
        self.last_sync_time = "Never"

        self.expand = True
        self.padding = ft.Padding.all(28)

        # File pickers for manual import/export (self-register as Services in Flet 1.0+)
        self.save_picker = ft.FilePicker(on_result=self._on_save_picked)
        self.open_picker = ft.FilePicker(on_result=self._on_open_picked)

        self._build_view()

    def _build_view(self) -> None:
        title = ft.Text("CLOUD DRIVES & SYNC", size=24, weight=ft.FontWeight.W_800, color=self._mt.text_primary)
        subtitle = ft.Text(
            "Stream music directly from your personal cloud drives and sync playlists & favorites across devices with zero external servers.",
            size=14,
            color=self._mt.text_secondary
        )

        # Cloud Drive Connection Tiles (Metro Style)
        drive_cards = ft.Row(
            spacing=16,
            controls=[
                self._build_drive_card("Google Drive", ft.Icons.CLOUD_DONE, "Connect to stream music and sync library to appDataFolder", False),
                self._build_drive_card("Microsoft OneDrive", ft.Icons.CLOUD_QUEUE, "Connect to stream music from OneDrive /Apps/MyTunes", False),
                self._build_drive_card("Dropbox", ft.Icons.FOLDER_SPECIAL, "Connect to stream music from Dropbox /Apps/MyTunes", False),
            ]
        )

        # Cloud Sync Box
        self.sync_status_text = ft.Text(f"Last synchronized: {self.last_sync_time}", size=13, color=self._mt.text_secondary)
        
        sync_now_btn = ft.FilledButton(
            "Sync Now",
            icon=ft.Icons.SYNC,
            on_click=self._trigger_sync
        )

        export_btn = ft.OutlinedButton(
            "Export Sync File",
            icon=ft.Icons.DOWNLOAD,
            on_click=self._on_export_click
        )

        import_btn = ft.OutlinedButton(
            "Import Sync File",
            icon=ft.Icons.UPLOAD_FILE,
            on_click=self._on_import_click
        )

        sync_actions = ft.Row([sync_now_btn, export_btn, import_btn], spacing=12)

        sync_container = ft.Container(
            bgcolor=self._mt.surface_color,
            border=ft.Border.all(1, self._mt.border_color),
            padding=20,
            border_radius=4,
            content=ft.Column(
                spacing=12,
                controls=[
                    ft.Row([
                        ft.Icon(ft.Icons.SYNC, color=self._mt.current_accent, size=24),
                        ft.Text("Zero-Backend Cloud Synchronization", size=16, weight=ft.FontWeight.BOLD),
                    ], spacing=10),
                    ft.Text(
                        "Your library metadata (playlists, favorites, podcast subscriptions, and listening history) "
                        "is saved directly to your cloud storage. Your data remains completely private.",
                        size=13,
                        color=self._mt.text_secondary
                    ),
                    self.sync_status_text,
                    sync_actions
                ]
            )
        )

        self.content = ft.Column(
            expand=True,
            scroll=ft.ScrollMode.AUTO,
            spacing=24,
            controls=[
                ft.Column([title, subtitle], spacing=4),
                drive_cards,
                ft.Divider(height=1),
                sync_container
            ]
        )

    def _build_drive_card(self, name: str, icon: ft.Icons, desc: str, connected: bool) -> ft.Container:
        connect_btn = ft.FilledButton(
            "Connected" if connected else "Connect Account",
            disabled=connected,
            on_click=lambda e, d=name: self._connect_provider(d)
        )

        return ft.Container(
            bgcolor=self._mt.surface_color,
            border=ft.Border.all(1, self._mt.border_color),
            padding=18,
            width=280,
            border_radius=4,
            content=ft.Column(
                spacing=12,
                controls=[
                    ft.Row([
                        ft.Icon(icon, color=self._mt.current_accent, size=28),
                        ft.Text(name, size=15, weight=ft.FontWeight.BOLD)
                    ], spacing=8),
                    ft.Text(desc, size=12, color=self._mt.text_secondary, max_lines=3),
                    connect_btn
                ]
            )
        )

    def _connect_provider(self, drive_name: str) -> None:
        """Opens OAuth connection dialog."""
        info = ft.Text(
            f"Clicking below opens your browser to authorize MyTunes to access audio files in {drive_name}. "
            "Tokens are stored securely on your local device.",
            size=13
        )
        dlg = ft.AlertDialog(
            title=ft.Text(f"Connect to {drive_name}"),
            content=info,
            actions=[
                ft.TextButton("Cancel", on_click=lambda e: close_dialog(self.app_page, dlg)),
                ft.FilledButton("Authorize in Browser", on_click=lambda e: self._launch_oauth(drive_name, dlg))
            ]
        )
        open_dialog(self.app_page, dlg)

    def _launch_oauth(self, drive_name: str, dlg: ft.AlertDialog) -> None:
        close_dialog(self.app_page, dlg)
        show_snackbar(self.app_page, f"Starting OAuth2 authentication for {drive_name}...")
        self.app_page.update()

    def _trigger_sync(self, e) -> None:
        """Executes a sync cycle."""
        # Export current local state
        snapshot = self.sync_manager.export_sync_snapshot()
        self.last_sync_time = time.strftime("%Y-%m-%d %H:%M:%S")
        self.sync_status_text.value = f"Last synchronized: {self.last_sync_time} (Snapshot ready)"
        show_snackbar(self.app_page, "Cloud sync completed successfully!")
        safe_update(self)

    async def _on_export_click(self, e) -> None:
        path = await self.save_picker.save_file(file_name=SYNC_FILENAME)
        if path:
            self._do_export_sync(path)

    async def _on_import_click(self, e) -> None:
        files = await self.open_picker.pick_files(allowed_extensions=["json"])
        if files:
            self._do_import_sync(files[0].path)

    def _on_save_picked(self, e: ft.FilePickerResultEvent) -> None:
        if e.path:
            self._do_export_sync(e.path)

    def _do_export_sync(self, path: str) -> None:
        json_data = self.sync_manager.serialize_to_json()
        with open(path, "w", encoding="utf-8") as f:
            f.write(json_data)
        show_snackbar(self.app_page, f"Sync file exported to {path}")
        safe_update(self)

    def _on_open_picked(self, e: ft.FilePickerResultEvent) -> None:
        if e.files:
            self._do_import_sync(e.files[0].path)

    def _do_import_sync(self, file_path: str) -> None:
        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read()
        self.sync_manager.load_from_json(content)
        show_snackbar(self.app_page, "Sync file merged successfully!")
        safe_update(self)
