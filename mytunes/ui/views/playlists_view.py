import os
import time
import flet as ft
from typing import List, Callable, Optional
import sqlite3
from mytunes.models.playlist import Playlist
from mytunes.models.track import Track
from mytunes.ui.theme import MetroTheme
from mytunes.ui.dialog_utils import safe_update, show_snackbar, open_dialog, close_dialog

class PlaylistsView(ft.Container):
    """
    Playlists management view supporting .m3u import/export,
    playlist creation, and cloud sync.
    """

    def __init__(
        self,
        page: ft.Page,
        db_conn: sqlite3.Connection,
        theme: MetroTheme,
        on_play_track: Callable[[Track, List[Track]], None],
        on_play_next: Optional[Callable[[Track], None]] = None,
    ):
        super().__init__()
        self.app_page = page
        self.conn = db_conn
        self._mt = theme
        self.on_play_track = on_play_track
        self.on_play_next = on_play_next

        self.playlists: List[Playlist] = []
        self.selected_playlist: Optional[Playlist] = None
        self.playlist_tracks: List[Track] = []

        self.expand = True
        self.padding = ft.Padding.all(24)

        # File pickers for M3U import & export (self-register as Services in Flet 1.0+)
        self.import_picker = ft.FilePicker(on_result=self._on_m3u_import)
        self.export_picker = ft.FilePicker(on_result=self._on_m3u_export)

        self._build_view()
        self.load_playlists()

    def _build_view(self) -> None:
        title = ft.Text("PLAYLISTS", size=24, weight=ft.FontWeight.W_800, color=self._mt.text_primary)

        new_btn = ft.FilledButton("New Playlist", icon=ft.Icons.ADD, on_click=self._show_create_dialog)
        import_btn = ft.OutlinedButton(
            "Import .M3U",
            icon=ft.Icons.FILE_OPEN,
            on_click=self._on_import_click
        )

        header_row = ft.Row([title, ft.Row([new_btn, import_btn], spacing=10)], alignment=ft.MainAxisAlignment.SPACE_BETWEEN)

        self.sidebar_list = ft.ListView(width=220, spacing=4)
        self.tracks_view = ft.ListView(expand=True, spacing=4)

        self.content = ft.Column(
            expand=True,
            spacing=16,
            controls=[
                header_row,
                ft.Row(
                    expand=True,
                    spacing=20,
                    controls=[
                        ft.Container(
                            width=220,
                            content=self.sidebar_list,
                            border=ft.Border.only(right=ft.BorderSide(1, self._mt.border_color)),
                            padding=ft.Padding.only(right=12)
                        ),
                        self.tracks_view
                    ]
                )
            ]
        )

    def load_playlists(self) -> None:
        cursor = self.conn.execute("SELECT id, name, description, created_at, updated_at FROM playlists ORDER BY name")
        self.playlists = [
            Playlist(id=r["id"], name=r["name"], description=r["description"] or "", created_at=r["created_at"], updated_at=r["updated_at"])
            for r in cursor.fetchall()
        ]
        self._render_sidebar()

    def _render_sidebar(self) -> None:
        self.sidebar_list.controls.clear()
        if not self.playlists:
            self.sidebar_list.controls.append(
                ft.Text("No playlists yet", size=13, color=self._mt.text_secondary, italic=True)
            )
        else:
            for p in self.playlists:
                is_selected = (self.selected_playlist and self.selected_playlist.id == p.id)
                item = ft.Container(
                    padding=ft.Padding.symmetric(horizontal=12, vertical=8),
                    border_radius=4,
                    bgcolor=self._mt.surface_variant if is_selected else ft.Colors.TRANSPARENT,
                    ink=True,
                    on_click=lambda e, pl=p: self._select_playlist(pl),
                    content=ft.Row([
                        ft.Icon(ft.Icons.PLAYLIST_PLAY, size=20, color=self._mt.current_accent if is_selected else self._mt.text_secondary),
                        ft.Text(p.name, size=14, weight=ft.FontWeight.BOLD if is_selected else ft.FontWeight.W_400, no_wrap=True, max_lines=1, overflow=ft.TextOverflow.ELLIPSIS, expand=True)
                    ], spacing=8)
                )
                self.sidebar_list.controls.append(item)

        safe_update(self)

    def _select_playlist(self, playlist: Playlist) -> None:
        self.selected_playlist = playlist
        self._render_sidebar()
        self._load_playlist_tracks(playlist.id)

    def _load_playlist_tracks(self, playlist_id: str) -> None:
        sql = """
        SELECT t.* FROM tracks t
        JOIN playlist_tracks pt ON t.id = pt.track_id
        WHERE pt.playlist_id = ?
        ORDER BY pt.position ASC
        """
        cursor = self.conn.execute(sql, (playlist_id,))
        self.playlist_tracks = [
            Track(
                id=r["id"], title=r["title"], artist=r["artist"], album=r["album"],
                file_path=r["file_path"], duration=r["duration"] or 0.0,
                artwork_path=r["artwork_path"], is_favorite=bool(r["is_favorite"])
            ) for r in cursor.fetchall()
        ]

        self.tracks_view.controls.clear()

        # Playlist Header
        export_btn = ft.OutlinedButton(
            "Export to .M3U",
            icon=ft.Icons.SAVE_ALT,
            on_click=self._on_export_click
        )
        p_header = ft.Row([
            ft.Text(f"{self.selected_playlist.name} ({len(self.playlist_tracks)} tracks)", size=18, weight=ft.FontWeight.BOLD),
            export_btn
        ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN)

        self.tracks_view.controls.append(p_header)
        self.tracks_view.controls.append(ft.Divider(height=1))

        if not self.playlist_tracks:
            self.tracks_view.controls.append(
                ft.Container(
                    alignment=ft.Alignment.CENTER,
                    padding=40,
                    content=ft.Text("This playlist has no tracks. Add songs from your Music Library!", color=self._mt.text_secondary)
                )
            )
        else:
            for t in self.playlist_tracks:
                song_controls: list[ft.Control] = [
                    ft.Icon(ft.Icons.MUSIC_NOTE, size=18, color=self._mt.text_secondary),
                    ft.Column([
                        ft.Text(t.title, size=13, weight=ft.FontWeight.BOLD),
                        ft.Text(f"{t.artist} • {t.album}", size=11, color=self._mt.text_secondary)
                    ], expand=True),
                    ft.Text(t.formatted_duration, size=12, color=self._mt.text_secondary),
                ]
                if self.on_play_next:
                    song_controls.append(
                        ft.PopupMenuButton(
                            icon=ft.Icons.MORE_VERT,
                            tooltip="Song options",
                            items=[
                                ft.PopupMenuItem(
                                    content="Play Next",
                                    icon=ft.Icons.PLAY_ARROW,
                                    on_click=lambda e, track=t: self.on_play_next(track),
                                )
                            ],
                        )
                    )
                row = ft.Container(
                    padding=ft.Padding.symmetric(horizontal=12, vertical=6),
                    border_radius=4,
                    ink=True,
                    on_click=lambda e, tr=t: self.on_play_track(tr, self.playlist_tracks),
                    content=ft.Row(song_controls, spacing=12)
                )
                self.tracks_view.controls.append(row)

        safe_update(self)

    def _show_create_dialog(self, e) -> None:
        name_input = ft.TextField(label="Playlist Name", autofocus=True)

        def create_playlist(e):
            if name_input.value.strip():
                p_id = f"pl_{int(time.time()*1000)}"
                self.conn.execute(
                    "INSERT INTO playlists (id, name, created_at, updated_at) VALUES (?, ?, ?, ?)",
                    (p_id, name_input.value.strip(), time.time(), time.time())
                )
                self.conn.commit()
                close_dialog(self.app_page, self.dialog)
                self.load_playlists()

        self.dialog = ft.AlertDialog(
            title=ft.Text("Create New Playlist", weight=ft.FontWeight.BOLD),
            content=name_input,
            actions=[
                ft.TextButton("Cancel", on_click=lambda e: close_dialog(self.app_page, self.dialog)),
                ft.FilledButton("Create", on_click=create_playlist)
            ]
        )
        open_dialog(self.app_page, self.dialog)

    async def _on_import_click(self, e) -> None:
        files = await self.import_picker.pick_files(allowed_extensions=["m3u", "m3u8"])
        if files:
            self._do_m3u_import(files[0].path)

    async def _on_export_click(self, e) -> None:
        if self.selected_playlist:
            path = await self.export_picker.save_file(file_name=f"{self.selected_playlist.name}.m3u")
            if path:
                self._do_m3u_export(path)

    def _on_m3u_import(self, e: ft.FilePickerResultEvent) -> None:
        if e.files:
            self._do_m3u_import(e.files[0].path)

    def _do_m3u_import(self, file_path: str) -> None:
        p_id = f"pl_m3u_{int(time.time()*1000)}"
        pl = Playlist.from_m3u(file_path, p_id)
        self.conn.execute(
            "INSERT INTO playlists (id, name, created_at, updated_at) VALUES (?, ?, ?, ?)",
            (pl.id, pl.name, pl.created_at, pl.updated_at)
        )
        # Link tracks if in library
        for pos, track_path in enumerate(pl.track_ids):
            match = self.conn.execute("SELECT id FROM tracks WHERE file_path = ?", (track_path,)).fetchone()
            if match:
                self.conn.execute(
                    "INSERT OR IGNORE INTO playlist_tracks (playlist_id, track_id, position) VALUES (?, ?, ?)",
                    (pl.id, match["id"], pos)
                )
        self.conn.commit()
        self.load_playlists()
        show_snackbar(self.app_page, f"Imported playlist '{pl.name}'")
        self.app_page.update()

    def _on_m3u_export(self, e: ft.FilePickerResultEvent) -> None:
        if e.path:
            self._do_m3u_export(e.path)

    def _do_m3u_export(self, path: str) -> None:
        if self.selected_playlist:
            paths = [t.file_path for t in self.playlist_tracks if t.file_path]
            self.selected_playlist.export_m3u(path, paths)
            show_snackbar(self.app_page, f"Exported to {path}")
            self.app_page.update()
