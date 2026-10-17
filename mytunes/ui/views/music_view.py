from __future__ import annotations
from mytunes.ui.dialog_utils import safe_update, show_snackbar
import os
import re
import random
import urllib.parse
import flet as ft
from typing import List, Callable, Optional, Dict
from mytunes.models.track import Track, Album
from mytunes.providers.local import LocalProvider
from mytunes.providers.metadata import ArtistMetadataProvider
from mytunes.ui.theme import MetroTheme
import threading

class MusicView(ft.Container):
    """
    Main Music Library View.
    Supports viewing Songs, Albums, Artists, and Favorites,
    with instant full-text search, album details page, and directory scanning.
    """

    def __init__(
        self,
        page: ft.Page,
        local_provider: LocalProvider,
        theme: MetroTheme,
        on_play_track: Callable[[Track, List[Track]], None],
        on_play_next: Callable[[Track], None],
        on_add_queue: Callable[[Track], None],
    ):
        super().__init__()
        self.app_page = page
        self.provider = local_provider
        self._mt = theme
        self.on_play_track = on_play_track
        self.on_play_next = on_play_next
        self.on_add_queue = on_add_queue

        self.all_tracks: List[Track] = []
        self.displayed_tracks: List[Track] = []
        self.current_subview = "songs"  # songs, albums, artists, favorites, album_detail, artist_detail
        self.selected_album_name: Optional[str] = None
        self.selected_album_artist: Optional[str] = None
        self.selected_artist_name: Optional[str] = None
        self.metadata_provider = ArtistMetadataProvider(db_conn=self.provider.conn)

        self.expand = True
        self.padding = ft.Padding.all(24)

        # File picker for scanning folders (self-registers as a Service in Flet 1.0+)
        self.file_picker = ft.FilePicker(on_result=self._on_folder_picked)

        self._build_view()
        self.load_tracks()

    def _build_view(self) -> None:
        # Search Field
        self.search_input = ft.TextField(
            hint_text="Search songs, artists, albums, or genres...",
            prefix_icon=ft.Icons.SEARCH,
            height=40,
            text_size=14,
            border_color=self._mt.border_color,
            expand=True,
            on_change=self._on_search_change
        )

        scan_btn = ft.FilledButton(
            "Scan Folder",
            icon=ft.Icons.FOLDER_OPEN,
            on_click=self._on_scan_clicked
        )

        self.top_bar = ft.Row([self.search_input, scan_btn], spacing=16)

        # Sub-tabs (Metro text style)
        self.tab_songs = self._create_subtab("Songs", "songs", True)
        self.tab_albums = self._create_subtab("Albums", "albums", False)
        self.tab_artists = self._create_subtab("Artists", "artists", False)
        self.tab_favorites = self._create_subtab("Favorites", "favorites", False)

        self.subtabs_row = ft.Row(
            spacing=20,
            controls=[self.tab_songs, self.tab_albums, self.tab_artists, self.tab_favorites]
        )

        # Dynamic content area container that swaps between list and album view
        self.content_area = ft.Container(expand=True)

        self.content = ft.Column(
            expand=True,
            spacing=16,
            controls=[self.top_bar, self.subtabs_row, self.content_area]
        )

    def _create_subtab(self, label: str, mode: str, is_active: bool) -> ft.Container:
        return ft.Container(
            content=ft.Text(
                label,
                size=15,
                weight=ft.FontWeight.BOLD if is_active else ft.FontWeight.W_500,
                color=self._mt.current_accent if is_active else self._mt.text_secondary
            ),
            ink=True,
            on_click=lambda e, m=mode: self._switch_subview(m),
            padding=ft.Padding.symmetric(horizontal=8, vertical=4)
        )

    def _switch_subview(self, mode: str) -> None:
        self.current_subview = mode
        self.subtabs_row.visible = True
        # Update tab colors
        for container, m in [(self.tab_songs, "songs"), (self.tab_albums, "albums"),
                             (self.tab_artists, "artists"), (self.tab_favorites, "favorites")]:
            active = (m == mode)
            text_ctrl = container.content
            if isinstance(text_ctrl, ft.Text):
                text_ctrl.weight = ft.FontWeight.BOLD if active else ft.FontWeight.W_500
                text_ctrl.color = self._mt.current_accent if active else self._mt.text_secondary

        self._filter_and_render()

    def load_tracks(self) -> None:
        """Loads tracks from database and populates list."""
        self.all_tracks = self.provider.get_all_tracks()
        self._filter_and_render()

    def _filter_and_render(self) -> None:
        query = self.search_input.value.strip().lower() if self.search_input.value else ""
        tracks = self.all_tracks

        if query:
            tracks = [t for t in tracks if query in t.title.lower() or query in t.artist.lower() or query in t.album.lower()]

        if self.current_subview == "favorites":
            tracks = [t for t in tracks if t.is_favorite]

        self.displayed_tracks = tracks

        if self.current_subview == "albums":
            self._render_albums_tab(tracks, query)
        elif self.current_subview == "artists":
            self._render_artists_tab(tracks, query)
        elif self.current_subview == "album_detail":
            if self.selected_album_name:
                self._render_album_page(self.selected_album_name, self.selected_album_artist)
            else:
                self._switch_subview("albums")
        elif self.current_subview == "artist_detail":
            if self.selected_artist_name:
                self._render_artist_page(self.selected_artist_name)
            else:
                self._switch_subview("artists")
        else:
            self._render_songs_tab(tracks)

    def _render_songs_tab(self, tracks: List[Track]) -> None:
        """Renders standard songs/favorites list."""
        songs_list = ft.ListView(expand=True, spacing=4, divider_thickness=0.5)

        if not tracks:
            songs_list.controls.append(
                ft.Container(
                    alignment=ft.Alignment.CENTER,
                    padding=40,
                    content=ft.Column(
                        horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                        spacing=12,
                        controls=[
                            ft.Icon(ft.Icons.MUSIC_OFF, size=48, color=ft.Colors.GREY_600),
                            ft.Text("No tracks found", size=16, weight=ft.FontWeight.W_600, color=self._mt.text_secondary),
                            ft.Text("Click 'Scan Folder' to import your local music library.", size=13, color=ft.Colors.GREY_500)
                        ]
                    )
                )
            )
        else:
            for t in tracks:
                songs_list.controls.append(self._build_track_row(t))

        self.content_area.content = songs_list
        safe_update(self)

    def _render_albums_tab(self, tracks: List[Track], query: str = "") -> None:
        """Renders Album tiles grid: square container (Metro style), album name, and smaller artist name below."""
        albums_map: Dict[str, Dict] = {}
        for t in tracks:
            alb_key = (t.album or "Unknown Album").strip()
            art = (t.album_artist or t.artist or "Unknown Artist").strip()
            key = (alb_key.lower(), art.lower())
            if key not in albums_map:
                albums_map[key] = {
                    "name": alb_key,
                    "artist": art,
                    "artwork_path": t.artwork_path,
                    "year": t.year,
                    "tracks": [t]
                }
            else:
                albums_map[key]["tracks"].append(t)
                if not albums_map[key]["artwork_path"] and t.artwork_path:
                    albums_map[key]["artwork_path"] = t.artwork_path
                if not albums_map[key]["year"] and t.year:
                    albums_map[key]["year"] = t.year

        albums_list = sorted(list(albums_map.values()), key=lambda a: a["name"].lower())

        if not albums_list:
            self.content_area.content = ft.Container(
                alignment=ft.Alignment.CENTER,
                padding=40,
                content=ft.Text("No albums found.", size=16, color=self._mt.text_secondary)
            )
            safe_update(self)
            return

        albums_grid = ft.GridView(
            expand=True,
            runs_count=5,
            max_extent=190,
            child_aspect_ratio=0.76,
            spacing=16,
            run_spacing=16,
        )

        for alb in albums_list:
            albums_grid.controls.append(self._build_album_card(alb))

        self.content_area.content = albums_grid
        safe_update(self)

    def _build_album_card(self, album_info: Dict) -> ft.Container:
        """Square Metro tile for album with album title and smaller artist name below."""
        alb_name = album_info["name"]
        artist_name = album_info["artist"]
        art_path = album_info.get("artwork_path")

        cover_img = ft.Image(
            src=art_path or None,
            width=160,
            height=160,
            fit=ft.BoxFit.COVER,
            border_radius=0,  # Square Metro style
            error_content=ft.Container(
                bgcolor=self._mt.surface_variant,
                width=160,
                height=160,
                alignment=ft.Alignment(0, 0),
                content=ft.Icon(ft.Icons.ALBUM, size=56, color=ft.Colors.GREY_500)
            )
        )

        return ft.Container(
            bgcolor=self._mt.surface_color,
            border=ft.Border.all(1, self._mt.border_color),
            padding=10,
            ink=True,
            tooltip=f"{alb_name} - {artist_name}",
            on_click=lambda e, name=alb_name, art=artist_name: self._open_album_page(name, art),
            content=ft.Column(
                spacing=6,
                horizontal_alignment=ft.CrossAxisAlignment.START,
                controls=[
                    cover_img,
                    ft.Text(
                        alb_name,
                        size=13,
                        weight=ft.FontWeight.BOLD,
                        color=self._mt.text_primary,
                        no_wrap=True,
                        max_lines=1,
                        overflow=ft.TextOverflow.ELLIPSIS
                    ),
                    ft.Text(
                        artist_name,
                        size=11,  # Smaller than album name
                        weight=ft.FontWeight.NORMAL,
                        color=self._mt.text_secondary,
                        no_wrap=True,
                        max_lines=1,
                        overflow=ft.TextOverflow.ELLIPSIS
                    )
                ]
            )
        )

    def _render_artists_tab(self, tracks: List[Track], query: str = "") -> None:
        """Renders Metro tiles grid for Artists in your library."""
        artists_map: Dict[str, Dict] = {}
        for t in tracks:
            art = (t.artist or "Unknown Artist").strip()
            if not art:
                art = "Unknown Artist"
            art_lower = art.lower()
            if art_lower not in artists_map:
                # Check if we have cached metadata in sqlite
                cached = self.metadata_provider.get_cached_metadata(art)
                artists_map[art_lower] = {
                    "name": art,
                    "picture_url": cached.get("picture_medium") if cached else None,
                    "local_fallback_art": t.artwork_path,
                    "albums": {t.album} if t.album else set(),
                    "tracks": [t]
                }
            else:
                artists_map[art_lower]["tracks"].append(t)
                if t.album:
                    artists_map[art_lower]["albums"].add(t.album)
                if not artists_map[art_lower]["local_fallback_art"] and t.artwork_path:
                    artists_map[art_lower]["local_fallback_art"] = t.artwork_path

        artists_list = sorted(list(artists_map.values()), key=lambda a: a["name"].lower())

        if not artists_list:
            self.content_area.content = ft.Container(
                alignment=ft.Alignment.CENTER,
                padding=40,
                content=ft.Text("No artists found.", size=16, color=self._mt.text_secondary)
            )
            safe_update(self)
            return

        artists_grid = ft.GridView(
            expand=True,
            runs_count=5,
            max_extent=190,
            child_aspect_ratio=0.76,
            spacing=16,
            run_spacing=16,
        )

        for art_info in artists_list:
            artists_grid.controls.append(self._build_artist_card(art_info))

        self.content_area.content = artists_grid
        safe_update(self)

    def _build_artist_card(self, artist_info: Dict) -> ft.Container:
        """Square Metro tile for an artist with name and album/song count below."""
        art_name = artist_info["name"]
        nb_albums = len(artist_info.get("albums", []))
        nb_songs = len(artist_info.get("tracks", []))
        alb_text = f"{nb_albums} album{'s' if nb_albums != 1 else ''} • {nb_songs} song{'s' if nb_songs != 1 else ''}"

        pic_src = artist_info.get("picture_url") or artist_info.get("local_fallback_art")

        artist_img = ft.Image(
            src=pic_src or None,
            width=160,
            height=160,
            fit=ft.BoxFit.COVER,
            border_radius=0,  # Metro square style
            error_content=ft.Container(
                bgcolor=self._mt.surface_variant,
                width=160,
                height=160,
                alignment=ft.Alignment(0, 0),
                content=ft.Icon(ft.Icons.PERSON, size=60, color=ft.Colors.GREY_500)
            )
        )

        # Trigger background fetch if artist has no cached picture yet
        if not artist_info.get("picture_url"):
            def _bg_fetch(name: str, img_ctrl: ft.Image):
                meta = self.metadata_provider.fetch_and_cache(name)
                pic = meta.get("picture_medium") or meta.get("picture_url")
                if pic and img_ctrl.src != pic:
                    img_ctrl.src = pic
                    safe_update(img_ctrl)

            threading.Thread(target=_bg_fetch, args=(art_name, artist_img), daemon=True).start()

        return ft.Container(
            bgcolor=self._mt.surface_color,
            border=ft.Border.all(1, self._mt.border_color),
            padding=10,
            ink=True,
            tooltip=f"{art_name} ({alb_text})",
            on_click=lambda e, name=art_name: self._open_artist_page(name),
            content=ft.Column(
                spacing=6,
                horizontal_alignment=ft.CrossAxisAlignment.START,
                controls=[
                    artist_img,
                    ft.Text(
                        art_name,
                        size=13,
                        weight=ft.FontWeight.BOLD,
                        color=self._mt.text_primary,
                        no_wrap=True,
                        max_lines=1,
                        overflow=ft.TextOverflow.ELLIPSIS
                    ),
                    ft.Text(
                        alb_text,
                        size=11,
                        weight=ft.FontWeight.NORMAL,
                        color=self._mt.text_secondary,
                        no_wrap=True,
                        max_lines=1,
                        overflow=ft.TextOverflow.ELLIPSIS
                    )
                ]
            )
        )

    def _open_album_page(self, album_name: str, album_artist: str) -> None:
        """Transitions into the detailed album page."""
        self.selected_album_name = album_name
        self.selected_album_artist = album_artist
        self.current_subview = "album_detail"
        self._render_album_page(album_name, album_artist)

    def _open_artist_page(self, artist_name: str) -> None:
        """Transitions into the detailed artist page."""
        self.selected_artist_name = artist_name
        self.current_subview = "artist_detail"
        self._render_artist_page(artist_name)

    def _render_artist_page(self, artist_name: str) -> None:
        """
        Renders the Artist Page with:
        - Back button placed on top-left (Arrow icon and 'Back' text)
        - Artist picture from Deezer (or local library artwork fallback)
        - Artist name, listener count (fans), total albums & songs in library
        - Artist biography (clean readable text with scrollable or expandable container)
        - Discography: grid/carousel of albums by this artist in your library
        - All songs by this artist in your library with 3-dots menus
        """
        artist_name = (artist_name or "Unknown Artist").strip()
        # Find all tracks by this artist in library
        artist_tracks = [
            t for t in self.all_tracks
            if (t.artist or "").strip().lower() == artist_name.lower() or (t.album_artist or "").strip().lower() == artist_name.lower()
        ]

        if not artist_tracks:
            self._switch_subview("artists")
            return

        # Back button on top left
        back_btn = ft.Container(
            alignment=ft.Alignment(-1.0, -1.0),
            padding=ft.Padding.only(bottom=4),
            content=ft.TextButton(
                "Back",
                icon=ft.Icons.ARROW_BACK,
                on_click=lambda e: self._switch_subview("artists")
            )
        )

        # Local fallback image from their tracks
        local_art = next((t.artwork_path for t in artist_tracks if t.artwork_path), None)

        # Check cached metadata from SQLite
        cached_meta = self.metadata_provider.get_cached_metadata(artist_name)
        initial_pic = (cached_meta.get("picture_url") or cached_meta.get("picture_medium")) if cached_meta else local_art
        initial_bio = cached_meta.get("bio", "") if cached_meta else ""
        initial_fans = cached_meta.get("nb_fan", 0) if cached_meta else 0

        # Unique albums
        albums_set = set()
        for t in artist_tracks:
            if t.album:
                albums_set.add(t.album)
        total_albums = len(albums_set)
        total_songs = len(artist_tracks)
        total_dur_sec = sum(t.duration for t in artist_tracks)
        mins = int(total_dur_sec // 60)
        hrs = mins // 60
        rem_m = mins % 60
        dur_label = f"{hrs} hr {rem_m} min" if hrs > 0 else f"{mins} min"

        # Metro Artist Photo widget
        artist_photo = ft.Image(
            src=initial_pic or None,
            width=180,
            height=180,
            fit=ft.BoxFit.COVER,
            border_radius=0,  # Metro square style
            error_content=ft.Container(
                bgcolor=self._mt.surface_variant,
                width=180,
                height=180,
                alignment=ft.Alignment(0, 0),
                content=ft.Icon(ft.Icons.PERSON, size=80, color=ft.Colors.GREY_500)
            )
        )

        # Fans / stats subtitle
        fans_text = ft.Text(
            f"{initial_fans:,} Deezer Fans" if initial_fans > 0 else "",
            size=12,
            color=self._mt.current_accent,
            weight=ft.FontWeight.W_600
        )

        # Bio text and link widgets
        initial_lastfm_url = cached_meta.get("lastfm_url") if cached_meta else None

        def _strip_bio(raw: str) -> str:
            """Remove 'Read more on Last.fm' and CC licence boilerplate from display text."""
            text = re.sub(r'User-contributed text is available under the Creative Commons.*$', '', raw, flags=re.IGNORECASE | re.DOTALL).strip()
            text = re.sub(r'\.?\s*Read more on Last\.fm\.?\s*$', '', text, flags=re.IGNORECASE).strip()
            return text

        # Strip "Read more on Last.fm" from the displayed body — button handles the link
        display_bio = _strip_bio(initial_bio) if initial_bio else ""

        bio_text = ft.Text(
            display_bio if display_bio else "Loading artist bio & details...",
            size=13,
            color=self._mt.text_secondary,
            selectable=True
        )

        # Mutable container for the lastfm URL so the closure in read_more_btn can be updated
        _lastfm_url_holder = {"url": initial_lastfm_url or (f"https://www.last.fm/music/{urllib.parse.quote(artist_name)}" if initial_lastfm_url is None else initial_lastfm_url)}

        async def _open_lastfm(e):
            url_launcher = ft.UrlLauncher()
            await url_launcher.launch_url(_lastfm_url_holder["url"])

        read_more_btn = ft.TextButton(
            content=ft.Row(
                spacing=4,
                tight=True,
                controls=[
                    ft.Text("Read more on Last.fm", size=12, color=self._mt.current_accent, weight=ft.FontWeight.W_600),
                    ft.Icon(ft.Icons.OPEN_IN_NEW, size=13, color=self._mt.current_accent)
                ]
            ),
            style=ft.ButtonStyle(padding=0),
            # Show if we already have a lastfm_url cached or if bio contains the phrase
            visible=bool(initial_lastfm_url or "Read more on Last.fm" in initial_bio),
            on_click=_open_lastfm
        )

        bio_container = ft.Container(
            padding=ft.Padding.only(top=6),
            content=ft.Column(
                spacing=4,
                controls=[bio_text, read_more_btn]
            )
        )

        # Three dots options for Artist
        all_artist_fav = bool(artist_tracks) and all(t.is_favorite for t in artist_tracks)
        artist_menu = ft.PopupMenuButton(
            icon=ft.Icons.MORE_HORIZ,
            tooltip="Artist Options",
            items=[
                ft.PopupMenuItem(
                    content=ft.Row([
                        ft.Icon(ft.Icons.FAVORITE_BORDER if all_artist_fav else ft.Icons.FAVORITE, size=18, color=ft.Colors.GREY_400 if all_artist_fav else ft.Colors.RED_400),
                        ft.Text("Remove all from Favourites" if all_artist_fav else "Add all to Favourites")
                    ]),
                    on_click=lambda e, trks=artist_tracks, rem=all_artist_fav: self._unfavorite_album(trks) if rem else self._favorite_album(trks)
                ),
                ft.PopupMenuItem(
                    content=ft.Row([ft.Icon(ft.Icons.PLAY_ARROW, size=18), ft.Text("Play Next")]),
                    on_click=lambda e, trks=artist_tracks: self._play_next_album(trks)
                ),
                ft.PopupMenuItem(
                    content=ft.Row([ft.Icon(ft.Icons.QUEUE_MUSIC, size=18), ft.Text("Add to Currently Playing")]),
                    on_click=lambda e, trks=artist_tracks: self._add_album_to_queue(trks)
                ),
                ft.PopupMenuItem(
                    content=ft.Row([ft.Icon(ft.Icons.SHUFFLE, size=18), ft.Text("Play on Random")]),
                    on_click=lambda e, trks=artist_tracks: self._play_album_random(trks)
                ),
            ]
        )

        artist_info_col = ft.Column(
            spacing=4,
            expand=True,
            controls=[
                ft.Row(
                    spacing=8,
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    controls=[
                        ft.Text(artist_name, size=26, weight=ft.FontWeight.W_800, color=self._mt.text_primary, selectable=True),
                        artist_menu
                    ]
                ),
                fans_text,
                ft.Text(f"{total_albums} Album{'s' if total_albums != 1 else ''} • {total_songs} Songs • {dur_label} in Library", size=12, color=self._mt.text_secondary),
                bio_container
            ]
        )

        header_card = ft.Container(
            bgcolor=self._mt.surface_color,
            border=ft.Border.all(1, self._mt.border_color),
            padding=18,
            content=ft.Row(
                spacing=20,
                vertical_alignment=ft.CrossAxisAlignment.START,
                controls=[artist_photo, artist_info_col]
            )
        )

        # Background fetch worker to get Deezer image & Last.fm/Wikipedia bio if not cached
        if not cached_meta or not cached_meta.get("bio") or not cached_meta.get("picture_url"):
            def _load_artist_meta():
                meta = self.metadata_provider.fetch_and_cache(artist_name)
                pic = meta.get("picture_url") or meta.get("picture_medium")
                bio_content = meta.get("bio", "")
                fans = meta.get("nb_fan", 0)
                fetched_url = meta.get("lastfm_url")

                updated = False
                if pic and artist_photo.src != pic:
                    artist_photo.src = pic
                    updated = True

                if bio_content:
                    # Strip the Read more phrase from body text; button handles the link
                    clean = _strip_bio(bio_content)
                    bio_text.value = clean if clean else bio_content
                    # Show/update Read more button
                    lfm_url = fetched_url or f"https://www.last.fm/music/{urllib.parse.quote(artist_name)}"
                    _lastfm_url_holder["url"] = lfm_url
                    read_more_btn.visible = True
                    updated = True
                elif not display_bio:
                    bio_text.value = f"No biography found for {artist_name}."
                    updated = True

                if fans > 0:
                    fans_text.value = f"{fans:,} Deezer Fans"
                    updated = True

                if updated:
                    safe_update(self.content_area)

            threading.Thread(target=_load_artist_meta, daemon=True).start()

        # Section: Albums by this Artist
        albums_by_artist_cards = []
        for alb_name in sorted(list(albums_set)):
            alb_tracks = [t for t in artist_tracks if (t.album or "").lower() == alb_name.lower()]
            if alb_tracks:
                a_info = {
                    "name": alb_name,
                    "artist": artist_name,
                    "artwork_path": next((t.artwork_path for t in alb_tracks if t.artwork_path), None),
                    "year": next((t.year for t in alb_tracks if t.year), None),
                    "tracks": alb_tracks
                }
                albums_by_artist_cards.append(self._build_album_card(a_info))

        albums_section: List[ft.Control] = []
        if albums_by_artist_cards:
            albums_section.extend([
                ft.Text("ALBUMS", size=14, weight=ft.FontWeight.BOLD, color=self._mt.current_accent),
                ft.Row(
                    spacing=16,
                    scroll=ft.ScrollMode.AUTO,
                    controls=albums_by_artist_cards
                )
            ])

        # Section: Songs by this Artist
        # Sort by album then track number
        artist_tracks_sorted = sorted(
            artist_tracks,
            key=lambda t: (t.album or "", t.disc_number or 1, t.track_number or 999, t.title)
        )
        song_rows = []
        for idx, t in enumerate(artist_tracks_sorted, 1):
            song_num = ft.Container(
                width=32,
                alignment=ft.Alignment.CENTER_RIGHT,
                content=ft.Text(str(idx), size=12, color=self._mt.text_secondary, weight=ft.FontWeight.BOLD)
            )
            title_col = ft.Column(
                spacing=1,
                expand=True,
                controls=[
                    ft.Text(t.title, size=13, weight=ft.FontWeight.W_600, color=self._mt.text_primary, no_wrap=True, max_lines=1, overflow=ft.TextOverflow.ELLIPSIS),
                    ft.Text(t.album or "Unknown Album", size=11, color=self._mt.text_secondary, no_wrap=True, max_lines=1, overflow=ft.TextOverflow.ELLIPSIS)
                ]
            )
            dur_widget = ft.Text(t.formatted_duration, size=12, color=self._mt.text_secondary)
            track_menu = ft.PopupMenuButton(
                icon=ft.Icons.MORE_VERT,
                items=[
                    ft.PopupMenuItem(content="Play Next", icon=ft.Icons.PLAY_ARROW, on_click=lambda e, tr=t: self.on_play_next(tr)),
                    ft.PopupMenuItem(content="Add to Queue", icon=ft.Icons.QUEUE_MUSIC, on_click=lambda e, tr=t: self.on_add_queue(tr)),
                    ft.PopupMenuItem(
                        content="Remove from Favourites" if t.is_favorite else "Add to Favourites",
                        icon=ft.Icons.FAVORITE if t.is_favorite else ft.Icons.FAVORITE_BORDER,
                        on_click=lambda e, tr=t: self._toggle_fav(tr)
                    ),
                ]
            )

            row = ft.Container(
                padding=ft.Padding.symmetric(horizontal=12, vertical=6),
                border_radius=4,
                ink=True,
                on_click=lambda e, tr=t, trks=artist_tracks_sorted: self.on_play_track(tr, trks),
                content=ft.Row(
                    spacing=12,
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    controls=[song_num, title_col, dur_widget, track_menu]
                )
            )
            song_rows.append(row)

        songs_container = ft.Container(
            bgcolor=self._mt.surface_color,
            border=ft.Border.all(1, self._mt.border_color),
            padding=12,
            content=ft.Column(spacing=2, controls=song_rows)
        )

        artist_scroll_view = ft.ListView(
            expand=True,
            spacing=16,
            controls=[
                back_btn,
                header_card,
                *albums_section,
                ft.Text("SONGS", size=14, weight=ft.FontWeight.BOLD, color=self._mt.current_accent),
                songs_container
            ]
        )

        self.content_area.content = artist_scroll_view
        safe_update(self)

    def _render_album_page(self, album_name: str, album_artist: str) -> None:
        """
        Renders the Album Page with:
        - Album cover on top, album name, duration, year, album artist, additional artists, composers, genre, media location
        - Three dots button: Add to favourites, Play next, Add to currently playing (end of queue), Play on random, Add to a playlist
        - Multi-disc verification: List disc 1 and its songs, then disc 2, etc.
        - Clickable artist names redirecting to artist page placeholder
        - Other albums from that artist in library
        """
        # Find all songs for this album
        album_tracks = [
            t for t in self.all_tracks
            if (t.album or "").strip().lower() == album_name.strip().lower()
        ]

        if not album_tracks:
            self._switch_subview("albums")
            return

        # Sort all album tracks by disc_number and track_number for canonical album playback
        album_tracks_sorted = sorted(
            album_tracks,
            key=lambda t: (t.disc_number or 1, t.track_number or 999, t.title)
        )

        # Primary album metadata
        first_t = album_tracks_sorted[0]
        art_path = next((t.artwork_path for t in album_tracks_sorted if t.artwork_path), None)
        album_year = next((str(t.year) for t in album_tracks_sorted if t.year), "Unknown")
        genres = sorted(list({t.genre for t in album_tracks_sorted if t.genre and t.genre != "Unknown Genre"}))
        genre_str = ", ".join(genres) if genres else "Unknown Genre"

        # Media location / folder directory
        media_locations = sorted(list({os.path.dirname(t.file_path) for t in album_tracks_sorted if t.file_path}))
        location_str = ", ".join(media_locations) if media_locations else "Unknown Location"

        # Total duration
        total_duration_sec = sum(t.duration for t in album_tracks_sorted)
        total_mins = int(total_duration_sec // 60)
        total_hrs = total_mins // 60
        rem_mins = total_mins % 60
        dur_str = f"{total_hrs} hr {rem_mins} min" if total_hrs > 0 else f"{total_mins} min"

        # Artists & Composers
        main_artist = first_t.album_artist or first_t.artist or album_artist or "Unknown Artist"
        all_track_artists = sorted(list({t.artist for t in album_tracks_sorted if t.artist and t.artist != main_artist}))
        
        # Check composers from local provider database
        composer_set = set()
        for t in album_tracks_sorted:
            # Check if any composer tag exists in database or extra metadata
            try:
                row = self.provider.conn.execute("SELECT composer FROM tracks WHERE id = ?", (t.id,)).fetchone()
                if row and row["composer"]:
                    composer_set.add(row["composer"])
            except Exception:
                pass
        composers_list = sorted(list(composer_set))

        # Check if all songs in this album are favorited
        all_favorited = bool(album_tracks_sorted) and all(t.is_favorite for t in album_tracks_sorted)

        # Back button: placed on top left side, clean Arrow icon and "Back" string (no redundant arrow symbol)
        back_btn = ft.Container(
            alignment=ft.Alignment(-1.0, -1.0),
            padding=ft.Padding.only(bottom=4),
            content=ft.TextButton(
                "Back",
                icon=ft.Icons.ARROW_BACK,
                on_click=lambda e: self._switch_subview("albums")
            )
        )

        # Three dots album menu with dynamic favourite / remove from favourite option
        fav_album_item = ft.PopupMenuItem(
            content=ft.Row([
                ft.Icon(ft.Icons.FAVORITE_BORDER if all_favorited else ft.Icons.FAVORITE, size=18, color=ft.Colors.GREY_400 if all_favorited else ft.Colors.RED_400),
                ft.Text("Remove from Favourites" if all_favorited else "Add to Favourites")
            ]),
            on_click=lambda e, trks=album_tracks_sorted, rem=all_favorited: self._unfavorite_album(trks) if rem else self._favorite_album(trks)
        )

        album_menu = ft.PopupMenuButton(
            icon=ft.Icons.MORE_HORIZ,
            tooltip="Album Options",
            items=[
                fav_album_item,
                ft.PopupMenuItem(
                    content=ft.Row([ft.Icon(ft.Icons.PLAY_ARROW, size=18), ft.Text("Play Next")]),
                    on_click=lambda e, trks=album_tracks_sorted: self._play_next_album(trks)
                ),
                ft.PopupMenuItem(
                    content=ft.Row([ft.Icon(ft.Icons.QUEUE_MUSIC, size=18), ft.Text("Add to Currently Playing")]),
                    on_click=lambda e, trks=album_tracks_sorted: self._add_album_to_queue(trks)
                ),
                ft.PopupMenuItem(
                    content=ft.Row([ft.Icon(ft.Icons.SHUFFLE, size=18), ft.Text("Play on Random")]),
                    on_click=lambda e, trks=album_tracks_sorted: self._play_album_random(trks)
                ),
                ft.PopupMenuItem(
                    content=ft.Row([ft.Icon(ft.Icons.PLAYLIST_ADD, size=18), ft.Text("Add to a Playlist")]),
                    on_click=lambda e: show_snackbar(self.app_page, "Add to Playlist dialog coming soon!")
                ),
            ]
        )

        # Header Album Cover
        album_cover = ft.Image(
            src=art_path or None,
            width=160,
            height=160,
            fit=ft.BoxFit.COVER,
            border_radius=0,  # Metro square style
            error_content=ft.Container(
                bgcolor=self._mt.surface_variant,
                width=160,
                height=160,
                alignment=ft.Alignment(0, 0),
                content=ft.Icon(ft.Icons.ALBUM, size=64, color=ft.Colors.GREY_500)
            )
        )

        # Clickable main artist widget
        main_artist_btn = ft.TextButton(
            content=ft.Text(main_artist, size=15, weight=ft.FontWeight.W_600, color=self._mt.current_accent),
            style=ft.ButtonStyle(padding=0),
            on_click=lambda e, a=main_artist: self._open_artist_page(a)
        )

        # Additional artists row
        additional_artists_widgets: List[ft.Control] = [
            ft.Text("Additional Artists: ", size=12, color=self._mt.text_secondary, weight=ft.FontWeight.BOLD)
        ]
        if all_track_artists:
            for i, a in enumerate(all_track_artists):
                btn = ft.TextButton(
                    content=ft.Text(a, size=12, color=self._mt.current_accent),
                    style=ft.ButtonStyle(padding=0),
                    on_click=lambda e, art=a: self._open_artist_page(art)
                )
                additional_artists_widgets.append(btn)
                if i < len(all_track_artists) - 1:
                    additional_artists_widgets.append(ft.Text(", ", size=12, color=self._mt.text_secondary))
        else:
            additional_artists_widgets.append(ft.Text("None", size=12, color=self._mt.text_secondary))

        # Composers row
        composers_text = ", ".join(composers_list) if composers_list else "Not specified"

        # Album metadata column
        metadata_col = ft.Column(
            spacing=4,
            expand=True,
            controls=[
                ft.Row(
                    spacing=8,
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    controls=[
                        ft.Text(album_name, size=24, weight=ft.FontWeight.W_800, color=self._mt.text_primary, selectable=True),
                        album_menu
                    ]
                ),
                main_artist_btn,
                ft.Row([
                    ft.Text(f"Year: {album_year} • {len(album_tracks_sorted)} songs • Duration: {dur_str} • Genre: {genre_str}", size=12, color=self._mt.text_secondary)
                ]),
                ft.Row(wrap=True, controls=additional_artists_widgets),
                ft.Text(f"Composers: {composers_text}", size=12, color=self._mt.text_secondary),
                ft.Text(f"Media Location: {location_str}", size=11, color=ft.Colors.GREY_500, no_wrap=True, max_lines=1, overflow=ft.TextOverflow.ELLIPSIS, selectable=True)
            ]
        )

        header_card = ft.Container(
            bgcolor=self._mt.surface_color,
            border=ft.Border.all(1, self._mt.border_color),
            padding=18,
            content=ft.Row(
                spacing=20,
                vertical_alignment=ft.CrossAxisAlignment.START,
                controls=[album_cover, metadata_col]
            )
        )

        # Multi-disc handling: group tracks by disc_number
        discs_map: Dict[int, List[Track]] = {}
        for t in album_tracks_sorted:
            d_num = t.disc_number or 1
            if d_num not in discs_map:
                discs_map[d_num] = []
            discs_map[d_num].append(t)

        has_multiple_discs = len(discs_map) > 1
        discs_sorted = sorted(discs_map.keys())

        tracklist_controls: List[ft.Control] = []

        for d_num in discs_sorted:
            d_tracks = discs_map[d_num]
            if has_multiple_discs:
                tracklist_controls.append(
                    ft.Container(
                        padding=ft.Padding.only(top=14, bottom=6, left=6),
                        content=ft.Row([
                            ft.Icon(ft.Icons.DISC_FULL, size=16, color=self._mt.current_accent),
                            ft.Text(f"DISC {d_num}", size=13, weight=ft.FontWeight.BOLD, color=self._mt.current_accent),
                            ft.Text(f"({len(d_tracks)} tracks)", size=11, color=self._mt.text_secondary)
                        ], spacing=8)
                    )
                )

            for t in d_tracks:
                # Number on the left
                track_num_str = f"{t.track_number:02d}" if t.track_number else "—"
                num_widget = ft.Container(
                    width=28,
                    alignment=ft.Alignment.CENTER_RIGHT,
                    content=ft.Text(track_num_str, size=12, color=self._mt.text_secondary, weight=ft.FontWeight.BOLD)
                )

                title_widget = ft.Column(
                    spacing=1,
                    expand=True,
                    controls=[
                        ft.Text(t.title, size=13, weight=ft.FontWeight.W_600, color=self._mt.text_primary, no_wrap=True, max_lines=1, overflow=ft.TextOverflow.ELLIPSIS),
                        ft.Text(t.artist, size=11, color=self._mt.text_secondary, no_wrap=True, max_lines=1, overflow=ft.TextOverflow.ELLIPSIS) if t.artist != main_artist else ft.Container()
                    ]
                )

                dur_widget = ft.Text(t.formatted_duration, size=12, color=self._mt.text_secondary)

                # Track popup menu with dynamic favourite / remove from favourite option
                track_menu = ft.PopupMenuButton(
                    icon=ft.Icons.MORE_VERT,
                    items=[
                        ft.PopupMenuItem(content="Play Next", icon=ft.Icons.PLAY_ARROW, on_click=lambda e, tr=t: self.on_play_next(tr)),
                        ft.PopupMenuItem(content="Add to Queue", icon=ft.Icons.QUEUE_MUSIC, on_click=lambda e, tr=t: self.on_add_queue(tr)),
                        ft.PopupMenuItem(
                            content="Remove from Favourites" if t.is_favorite else "Add to Favourites",
                            icon=ft.Icons.FAVORITE if t.is_favorite else ft.Icons.FAVORITE_BORDER,
                            on_click=lambda e, tr=t: self._toggle_fav(tr)
                        ),
                    ]
                )

                row = ft.Container(
                    padding=ft.Padding.symmetric(horizontal=12, vertical=6),
                    border_radius=4,
                    ink=True,
                    # Tapping any song plays from that song with the entire album treated as a single list
                    on_click=lambda e, tr=t, trks=album_tracks_sorted: self.on_play_track(tr, trks),
                    content=ft.Row(
                        spacing=12,
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                        controls=[num_widget, title_widget, dur_widget, track_menu]
                    )
                )
                tracklist_controls.append(row)

        tracks_container = ft.Container(
            bgcolor=self._mt.surface_color,
            border=ft.Border.all(1, self._mt.border_color),
            padding=12,
            content=ft.Column(spacing=2, controls=tracklist_controls)
        )

        # Other albums from that artist in library
        other_albums = [
            t.album for t in self.all_tracks
            if (t.artist == main_artist or t.album_artist == main_artist) and t.album and t.album.lower() != album_name.lower()
        ]
        other_album_names = sorted(list(set(other_albums)))

        other_albums_section: List[ft.Control] = []
        if other_album_names:
            other_albums_section.append(
                ft.Text(f"MORE ALBUMS BY {main_artist.upper()}", size=14, weight=ft.FontWeight.BOLD, color=self._mt.current_accent)
            )
            other_cards = []
            for o_name in other_album_names:
                o_tracks = [t for t in self.all_tracks if (t.album or "").lower() == o_name.lower()]
                if o_tracks:
                    o_info = {
                        "name": o_name,
                        "artist": main_artist,
                        "artwork_path": next((t.artwork_path for t in o_tracks if t.artwork_path), None),
                        "year": next((t.year for t in o_tracks if t.year), None),
                        "tracks": o_tracks
                    }
                    other_cards.append(self._build_album_card(o_info))

            other_albums_row = ft.Row(
                spacing=16,
                scroll=ft.ScrollMode.AUTO,
                controls=other_cards
            )
            other_albums_section.append(other_albums_row)

        # Assemble full scrollable page with back button on the top left
        album_scroll_view = ft.ListView(
            expand=True,
            spacing=16,
            controls=[
                back_btn,
                header_card,
                ft.Text("TRACKLIST", size=14, weight=ft.FontWeight.BOLD, color=self._mt.current_accent),
                tracks_container,
                *other_albums_section
            ]
        )

        self.content_area.content = album_scroll_view
        safe_update(self)

    # --- Album Context Actions ---

    def _favorite_album(self, tracks: List[Track]) -> None:
        for t in tracks:
            t.is_favorite = True
            try:
                self.provider.conn.execute("UPDATE tracks SET is_favorite = 1 WHERE id = ?", (t.id,))
            except Exception:
                pass
        self.provider.conn.commit()
        show_snackbar(self.app_page, f"Added all {len(tracks)} songs to favourites!")
        self._filter_and_render()

    def _unfavorite_album(self, tracks: List[Track]) -> None:
        for t in tracks:
            t.is_favorite = False
            try:
                self.provider.conn.execute("UPDATE tracks SET is_favorite = 0 WHERE id = ?", (t.id,))
            except Exception:
                pass
        self.provider.conn.commit()
        show_snackbar(self.app_page, f"Removed all {len(tracks)} songs from favourites.")
        self._filter_and_render()

    def _play_next_album(self, tracks: List[Track]) -> None:
        for t in reversed(tracks):
            self.on_play_next(t)
        show_snackbar(self.app_page, f"Album queued to play next ({len(tracks)} songs)")

    def _add_album_to_queue(self, tracks: List[Track]) -> None:
        for t in tracks:
            self.on_add_queue(t)
        show_snackbar(self.app_page, f"Added {len(tracks)} songs to queue")

    def _play_album_random(self, tracks: List[Track]) -> None:
        shuffled = list(tracks)
        random.shuffle(shuffled)
        if shuffled:
            self.on_play_track(shuffled[0], shuffled)
            show_snackbar(self.app_page, f"Playing album on random ({len(shuffled)} songs)")

    def _build_track_row(self, track: Track) -> ft.Container:
        # Album art thumbnail
        art_img = ft.Image(
            src=track.artwork_path or None,
            width=40,
            height=40,
            fit=ft.BoxFit.COVER,
            border_radius=0,
            error_content=ft.Container(
                bgcolor=self._mt.surface_variant,
                width=40,
                height=40,
                content=ft.Icon(ft.Icons.MUSIC_NOTE, size=20, color=ft.Colors.GREY_500)
            )
        )

        title_col = ft.Column(
            spacing=1,
            controls=[
                ft.Text(track.title, size=14, weight=ft.FontWeight.W_600, color=self._mt.text_primary, no_wrap=True, max_lines=1, overflow=ft.TextOverflow.ELLIPSIS),
                ft.Text(f"{track.artist} • {track.album}", size=12, color=self._mt.text_secondary, no_wrap=True, max_lines=1, overflow=ft.TextOverflow.ELLIPSIS)
            ],
            expand=True
        )

        duration_text = ft.Text(track.formatted_duration, size=12, color=self._mt.text_secondary)

        fav_item = ft.PopupMenuItem(
            content="Remove from Favourites" if track.is_favorite else "Add to Favourites",
            icon=ft.Icons.FAVORITE if track.is_favorite else ft.Icons.FAVORITE_BORDER,
            on_click=lambda e, tr=track: self._toggle_fav(tr)
        )

        menu_btn = ft.PopupMenuButton(
            icon=ft.Icons.MORE_VERT,
            items=[
                ft.PopupMenuItem(content="Play Next", icon=ft.Icons.PLAY_ARROW, on_click=lambda e, tr=track: self.on_play_next(tr)),
                ft.PopupMenuItem(content="Add to Queue", icon=ft.Icons.QUEUE_MUSIC, on_click=lambda e, tr=track: self.on_add_queue(tr)),
                fav_item,
            ]
        )

        return ft.Container(
            padding=ft.Padding.symmetric(horizontal=12, vertical=6),
            border_radius=4,
            ink=True,
            on_click=lambda e, tr=track: self.on_play_track(tr, self.displayed_tracks),
            content=ft.Row(
                spacing=12,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
                controls=[art_img, title_col, duration_text, menu_btn]
            )
        )

    def _toggle_fav(self, track: Track) -> None:
        track.is_favorite = not track.is_favorite
        self.provider.conn.execute("UPDATE tracks SET is_favorite = ? WHERE id = ?", (1 if track.is_favorite else 0, track.id))
        self.provider.conn.commit()
        self._filter_and_render()

    def _on_search_change(self, e) -> None:
        self._filter_and_render()

    async def _on_scan_clicked(self, e) -> None:
        path = await self.file_picker.get_directory_path(dialog_title="Select Music Folder")
        if path:
            self._scan_folder(path)

    def _on_folder_picked(self, e: ft.FilePickerResultEvent) -> None:
        if e.path:
            self._scan_folder(e.path)

    def _scan_folder(self, path: str) -> None:
        # Show progress indicator
        self.content_area.content = ft.Container(
            alignment=ft.Alignment.CENTER,
            padding=40,
            content=ft.Column(
                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                spacing=12,
                controls=[
                    ft.ProgressRing(),
                    ft.Text(f"Scanning {path}...", size=14, color=self._mt.text_primary)
                ]
            )
        )
        safe_update(self)

        self.provider.scan_directory(path)
        self.load_tracks()
