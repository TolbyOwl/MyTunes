import sqlite3
import flet as ft
from typing import List, Callable, Optional
from mytunes.models.radio import RadioStation
from mytunes.providers.radio import RadioProvider
from mytunes.ui.theme import MetroTheme
from mytunes.ui.dialog_utils import safe_update, open_dialog, close_dialog

class RadioView(ft.Container):
    """
    Online Radio View powered by Radio-Browser API (30,000+ stations worldwide)
    with local & synced favorites support.
    """

    def __init__(
        self,
        page: ft.Page,
        theme: MetroTheme,
        on_play_station: Callable[[RadioStation], None],
        db_conn: Optional[sqlite3.Connection] = None
    ):
        super().__init__()
        self.app_page = page
        self._mt = theme
        self.conn = db_conn
        self.provider = RadioProvider()
        self.on_play_station = on_play_station
        self.stations: List[RadioStation] = []
        self.current_tab: str = "explore"  # "explore" or "favorites"

        self.expand = True
        self.padding = ft.Padding.all(24)

        self._build_view()
        self.load_featured()

    def _build_view(self) -> None:
        self.search_input = ft.TextField(
            hint_text="Search worldwide radio stations (e.g. BBC, Jazz, Lofi, Rock)...",
            prefix_icon=ft.Icons.RADIO,
            height=40,
            text_size=14,
            border_color=self._mt.border_color,
            expand=True,
            on_submit=self._on_search_submit
        )

        search_btn = ft.FilledButton(
            "Search",
            icon=ft.Icons.SEARCH,
            on_click=lambda e: self._do_search()
        )

        custom_btn = ft.OutlinedButton(
            "Add Stream URL",
            icon=ft.Icons.ADD,
            on_click=self._show_add_custom_dialog
        )

        top_bar = ft.Row([self.search_input, search_btn, custom_btn], spacing=12)

        # Tab navigation: Explore vs Favorites
        self.btn_tab_explore = ft.TextButton(
            content=ft.Row([
                ft.Icon(ft.Icons.EXPLORE, size=16),
                ft.Text("Explore Stations", weight=ft.FontWeight.BOLD)
            ], spacing=6),
            style=ft.ButtonStyle(color=self._mt.current_accent),
            on_click=lambda e: self._switch_tab("explore")
        )

        self.btn_tab_favorites = ft.TextButton(
            content=ft.Row([
                ft.Icon(ft.Icons.FAVORITE, size=16, color=ft.Colors.RED_400),
                ft.Text("Favorite Stations", weight=ft.FontWeight.NORMAL)
            ], spacing=6),
            style=ft.ButtonStyle(color=self._mt.text_secondary),
            on_click=lambda e: self._switch_tab("favorites")
        )

        tabs_row = ft.Row(
            spacing=16,
            controls=[self.btn_tab_explore, self.btn_tab_favorites]
        )

        # Quick genre chips
        genres = ["Pop", "Rock", "Jazz", "Classical", "Electronic", "News", "Lofi", "Ambient"]
        chips = [
            ft.Chip(label=ft.Text(g), on_click=lambda e, tag=g: self._filter_by_tag(tag))
            for g in genres
        ]
        self.chips_row = ft.Row(spacing=8, scroll=ft.ScrollMode.AUTO, controls=chips)

        self.stations_grid = ft.GridView(
            expand=True,
            runs_count=3,
            max_extent=260,
            child_aspect_ratio=1.6,
            spacing=12,
            run_spacing=12,
        )

        self.content = ft.Column(
            expand=True,
            spacing=14,
            controls=[top_bar, tabs_row, self.chips_row, self.stations_grid]
        )

    def _switch_tab(self, tab: str) -> None:
        self.current_tab = tab
        if tab == "explore":
            self.btn_tab_explore.style = ft.ButtonStyle(color=self._mt.current_accent)
            self.btn_tab_explore.content.controls[1].weight = ft.FontWeight.BOLD
            self.btn_tab_favorites.style = ft.ButtonStyle(color=self._mt.text_secondary)
            self.btn_tab_favorites.content.controls[1].weight = ft.FontWeight.NORMAL
            self.chips_row.visible = True
            self.load_featured()
        else:
            self.btn_tab_explore.style = ft.ButtonStyle(color=self._mt.text_secondary)
            self.btn_tab_explore.content.controls[1].weight = ft.FontWeight.NORMAL
            self.btn_tab_favorites.style = ft.ButtonStyle(color=ft.Colors.RED_400)
            self.btn_tab_favorites.content.controls[1].weight = ft.FontWeight.BOLD
            self.chips_row.visible = False
            self.load_favorites()

    def _get_favorite_urls(self) -> set[str]:
        if not self.conn:
            return set()
        try:
            cursor = self.conn.execute("SELECT stream_url FROM radio_stations WHERE is_favorite = 1")
            return {r["stream_url"] for r in cursor.fetchall()}
        except Exception:
            return set()

    def load_favorites(self) -> None:
        """Loads favorited radio stations from SQLite database."""
        self.stations_grid.controls = [
            ft.Container(alignment=ft.Alignment.CENTER, padding=20, content=ft.ProgressRing())
        ]
        safe_update(self)

        fav_stations: List[RadioStation] = []
        if self.conn:
            try:
                cursor = self.conn.execute(
                    "SELECT id, name, stream_url, homepage, favicon, country, language, tags, codec, bitrate FROM radio_stations WHERE is_favorite = 1 ORDER BY name ASC"
                )
                for r in cursor.fetchall():
                    fav_stations.append(RadioStation(
                        id=r["id"],
                        name=r["name"],
                        stream_url=r["stream_url"],
                        homepage=r["homepage"] or "",
                        favicon=r["favicon"] or None,
                        country=r["country"] or "",
                        language=r["language"] or "",
                        tags=r["tags"] or "",
                        codec=r["codec"] or "",
                        bitrate=r["bitrate"] or 0,
                        is_favorite=True
                    ))
            except Exception:
                pass

        self.stations = fav_stations
        self._render_stations()

    def load_featured(self) -> None:
        self.stations_grid.controls = [
            ft.Container(alignment=ft.Alignment.CENTER, padding=20, content=ft.ProgressRing())
        ]
        safe_update(self)

        fetched = self.provider.get_top_stations(limit=30)
        fav_urls = self._get_favorite_urls()
        for s in fetched:
            s.is_favorite = s.stream_url in fav_urls
        self.stations = fetched
        self._render_stations()

    def _filter_by_tag(self, tag: str) -> None:
        self.stations_grid.controls = [
            ft.Container(alignment=ft.Alignment.CENTER, padding=20, content=ft.ProgressRing())
        ]
        safe_update(self)
        fetched = self.provider.search_stations(tag=tag.lower(), limit=30)
        fav_urls = self._get_favorite_urls()
        for s in fetched:
            s.is_favorite = s.stream_url in fav_urls
        self.stations = fetched
        self._render_stations()

    def _do_search(self) -> None:
        query = self.search_input.value.strip() if self.search_input.value else ""
        if not query:
            if self.current_tab == "favorites":
                self.load_favorites()
            else:
                self.load_featured()
            return

        self.stations_grid.controls = [
            ft.Container(alignment=ft.Alignment.CENTER, padding=20, content=ft.ProgressRing())
        ]
        safe_update(self)

        if self.current_tab == "favorites":
            # Search within favorites
            q_lower = query.lower()
            fav_urls = self._get_favorite_urls()
            fav_stations: List[RadioStation] = []
            if self.conn:
                cursor = self.conn.execute("SELECT id, name, stream_url, homepage, favicon, country, language, tags, codec, bitrate FROM radio_stations WHERE is_favorite = 1")
                for r in cursor.fetchall():
                    if q_lower in r["name"].lower() or q_lower in (r["tags"] or "").lower():
                        fav_stations.append(RadioStation(
                            id=r["id"],
                            name=r["name"],
                            stream_url=r["stream_url"],
                            homepage=r["homepage"] or "",
                            favicon=r["favicon"] or None,
                            country=r["country"] or "",
                            language=r["language"] or "",
                            tags=r["tags"] or "",
                            codec=r["codec"] or "",
                            bitrate=r["bitrate"] or 0,
                            is_favorite=True
                        ))
            self.stations = fav_stations
        else:
            fetched = self.provider.search_stations(name=query, limit=30)
            fav_urls = self._get_favorite_urls()
            for s in fetched:
                s.is_favorite = s.stream_url in fav_urls
            self.stations = fetched

        self._render_stations()

    def _on_search_submit(self, e) -> None:
        self._do_search()

    def _toggle_station_favorite(self, station: RadioStation, fav_btn: ft.IconButton) -> None:
        station.is_favorite = not station.is_favorite
        fav_btn.icon = ft.Icons.FAVORITE if station.is_favorite else ft.Icons.FAVORITE_BORDER
        fav_btn.icon_color = ft.Colors.RED_400 if station.is_favorite else ft.Colors.GREY_400

        if self.conn:
            try:
                self.conn.execute(
                    """
                    INSERT INTO radio_stations (id, name, stream_url, homepage, favicon, country, language, tags, codec, bitrate, is_favorite)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(stream_url) DO UPDATE SET is_favorite = excluded.is_favorite
                    """,
                    (
                        station.id,
                        station.name,
                        station.stream_url,
                        station.homepage or "",
                        station.favicon or "",
                        station.country or "",
                        station.language or "",
                        station.tags or "",
                        station.codec or "",
                        station.bitrate or 0,
                        1 if station.is_favorite else 0
                    )
                )
                self.conn.commit()
            except Exception:
                pass

        if self.current_tab == "favorites" and not station.is_favorite:
            self.load_favorites()
        else:
            safe_update(self)

    def _render_stations(self) -> None:
        self.stations_grid.controls.clear()
        if not self.stations:
            msg = "No favorite radio stations yet. Tap the heart on any station to save it!" if self.current_tab == "favorites" else "No stations found. Try another search query."
            self.stations_grid.controls.append(
                ft.Container(
                    alignment=ft.Alignment.CENTER,
                    content=ft.Text(msg, color=self._mt.text_secondary)
                )
            )
        else:
            for s in self.stations:
                self.stations_grid.controls.append(self._build_station_card(s))
        safe_update(self)

    def _build_station_card(self, station: RadioStation) -> ft.Container:
        favicon = ft.Image(
            src=station.favicon or None,
            width=36,
            height=36,
            fit=ft.BoxFit.COVER,
            error_content=ft.Container(
                bgcolor=self._mt.surface_variant,
                width=36,
                height=36,
                content=ft.Icon(ft.Icons.RADIO, size=20, color=ft.Colors.GREY_500)
            )
        )

        info_col = ft.Column(
            spacing=2,
            controls=[
                ft.Text(station.name, size=13, weight=ft.FontWeight.BOLD, no_wrap=True, max_lines=1, overflow=ft.TextOverflow.ELLIPSIS),
                ft.Text(f"{station.country or 'Global'} • {station.codec or 'MP3'} {station.bitrate or 128}k", size=11, color=self._mt.text_secondary),
            ],
            expand=True
        )

        fav_btn = ft.IconButton(
            icon=ft.Icons.FAVORITE if station.is_favorite else ft.Icons.FAVORITE_BORDER,
            icon_color=ft.Colors.RED_400 if station.is_favorite else ft.Colors.GREY_400,
            icon_size=18,
            tooltip="Add to Favorites" if not station.is_favorite else "Remove from Favorites"
        )
        fav_btn.on_click = lambda e, st=station, btn=fav_btn: self._toggle_station_favorite(st, btn)

        play_btn = ft.IconButton(
            icon=ft.Icons.PLAY_ARROW_ROUNDED,
            icon_color=self._mt.current_accent,
            tooltip="Play Station",
            on_click=lambda e, st=station: self.on_play_station(st)
        )

        return ft.Container(
            bgcolor=self._mt.surface_color,
            border=ft.Border.all(1, self._mt.border_color),
            border_radius=4,
            padding=10,
            ink=True,
            on_click=lambda e, st=station: self.on_play_station(st),
            content=ft.Row(
                spacing=8,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
                controls=[favicon, info_col, fav_btn, play_btn]
            )
        )

    def _show_add_custom_dialog(self, e) -> None:
        name_input = ft.TextField(label="Station Name", hint_text="e.g. My Favorite Stream")
        url_input = ft.TextField(label="Stream URL", hint_text="http://... (mp3, aac, pls, m3u)")

        def save_custom(e):
            if name_input.value and url_input.value:
                custom_st = RadioStation(
                    id=f"custom_{hash(url_input.value)}",
                    name=name_input.value,
                    stream_url=url_input.value,
                    codec="Stream"
                )
                self.stations.insert(0, custom_st)
                self._render_stations()
                close_dialog(self.page, self.dialog)

        self.dialog = ft.AlertDialog(
            title=ft.Text("Add Custom Radio Stream", weight=ft.FontWeight.BOLD),
            content=ft.Column(tight=True, spacing=12, controls=[name_input, url_input]),
            actions=[
                ft.TextButton("Cancel", on_click=lambda e: close_dialog(self.page, self.dialog)),
                ft.FilledButton("Add & Play", on_click=save_custom),
            ]
        )
        open_dialog(self.page, self.dialog)
