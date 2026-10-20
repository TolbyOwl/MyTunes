import asyncio
import threading
import flet as ft
import time
import sqlite3
import re
import html
import logging
import hashlib
import os
from typing import List, Callable, Optional
from mytunes.models.podcast import PodcastShow, Episode
from mytunes.models.track import Track
from mytunes.cache import CacheManager, OFFLINE_DIR
from mytunes.providers.podcast_cache import PodcastCache
from mytunes.providers.podcasts import PodcastProvider
from mytunes.ui.theme import MetroTheme
from mytunes.ui.dialog_utils import safe_update, show_snackbar, open_dialog, close_dialog

logger = logging.getLogger(__name__)
PODCAST_CACHE_TTL_SECONDS = 24 * 60 * 60
INITIAL_EPISODE_BATCH_SIZE = 100
EPISODE_BATCH_SIZE = 20

class PodcastsView(ft.Container):
    """
    Podcasts View with iTunes search, direct RSS subscriptions,
    persistent SQLite storage, and episode playback.
    """

    def __init__(
        self,
        page: ft.Page,
        db_conn: sqlite3.Connection,
        theme: MetroTheme,
        on_play_episode: Callable[[Episode, PodcastShow], None],
        on_play_next: Optional[Callable[[Track], None]] = None,
        on_add_queue: Optional[Callable[[Track], None]] = None,
    ):
        super().__init__()
        self.app_page = page
        self.conn = db_conn
        self._mt = theme
        self.provider = PodcastProvider()
        self.on_play_episode = on_play_episode
        self.on_play_next = on_play_next
        self.on_add_queue = on_add_queue
        self._audio_cache: Optional[CacheManager] = None
        self._downloading_episode_ids: set[str] = set()

        self.subscribed_shows: List[PodcastShow] = []
        self.search_results: List[PodcastShow] = []
        self.selected_show: Optional[PodcastShow] = None
        self.selected_episode: Optional[Episode] = None
        self._current_screen: str = "subscriptions"  # "subscriptions", "search", "loading", "details", "episode_detail", "error"
        self._active_load_id: int = 0
        self._active_search_id: int = 0
        self._episode_render_id: int = 0
        self._episode_render_offset: int = 0
        self._episode_render_episodes: List[Episode] = []
        self._episode_sort_order = "date_desc"
        self._episode_batch_loading = False
        self._search_error: Optional[str] = None
        self._feed_refresh_error: Optional[str] = None
        self._feed_refresh_status: Optional[str] = None
        self._feed_refreshing = False
        self.cache = PodcastCache(db_conn)

        self.expand = True
        self.padding = ft.Padding.all(24)

        self._build_view()
        self.load_subscriptions()

    def _build_view(self) -> None:
        self.search_input = ft.TextField(
            hint_text="Search millions of podcasts (iTunes directory)...",
            prefix_icon=ft.Icons.PODCASTS,
            height=40,
            text_size=14,
            border_color=self._mt.border_color,
            expand=True,
            on_submit=self._on_search_submit
        )

        search_btn = ft.FilledButton("Search", icon=ft.Icons.SEARCH, on_click=lambda e: self._do_search())
        rss_btn = ft.OutlinedButton("Add RSS URL", icon=ft.Icons.RSS_FEED, on_click=self._show_add_rss_dialog)

        top_bar = ft.Row([self.search_input, search_btn, rss_btn], spacing=12)

        self.content_area = ft.Column(
            expand=True,
            scroll=ft.ScrollMode.AUTO,
            spacing=20
        )

        self.content = ft.Column(
            expand=True,
            spacing=16,
            controls=[top_bar, self.content_area]
        )

    def load_subscriptions(self) -> None:
        """Loads subscribed podcasts from SQLite database."""
        self._active_load_id += 1
        self._current_screen = "subscriptions"
        cursor = self.conn.execute("SELECT id, title, author, description, feed_url, artwork_url, date_subscribed FROM podcasts ORDER BY date_subscribed DESC")
        self.subscribed_shows = [
            PodcastShow(
                id=r["id"],
                title=r["title"],
                author=r["author"] or "",
                description=r["description"] or "",
                feed_url=r["feed_url"],
                artwork_url=r["artwork_url"],
                date_subscribed=r["date_subscribed"]
            )
            for r in cursor.fetchall()
        ]
        self._render_subscriptions_view()

    def _is_subscribed(self, feed_url: str) -> bool:
        cursor = self.conn.execute("SELECT 1 FROM podcasts WHERE feed_url = ?", (feed_url,))
        return cursor.fetchone() is not None

    def _toggle_subscription(self, show: PodcastShow, sub_btn: ft.FilledButton) -> None:
        """Toggles subscription state in database."""
        if self._is_subscribed(show.feed_url):
            # Unsubscribe
            self.conn.execute("DELETE FROM podcasts WHERE feed_url = ?", (show.feed_url,))
            self.conn.commit()
            sub_btn.content = "Subscribe"
            sub_btn.icon = ft.Icons.ADD
            show_snackbar(self.app_page, f"Unsubscribed from '{show.title}'")
        else:
            # Subscribe
            self.conn.execute(
                """
                INSERT INTO podcasts (id, title, author, description, feed_url, artwork_url, date_subscribed)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(feed_url) DO UPDATE SET
                    title=excluded.title,
                    author=excluded.author,
                    artwork_url=excluded.artwork_url
                """,
                (show.id, show.title, show.author, show.description, show.feed_url, show.artwork_url, time.time())
            )
            self.conn.commit()
            sub_btn.content = "Subscribed"
            sub_btn.icon = ft.Icons.CHECK
            show_snackbar(self.app_page, f"Subscribed to '{show.title}'!")

        self.app_page.update()

    def _render_subscriptions_view(self) -> None:
        self._current_screen = "subscriptions"
        self.content_area.scroll = ft.ScrollMode.AUTO
        self.content_area.controls.clear()

        if self.subscribed_shows:
            # Header
            header = ft.Row([
                ft.Icon(ft.Icons.SUBSCRIPTIONS, color=self._mt.current_accent, size=22),
                ft.Text(f"MY SUBSCRIPTIONS ({len(self.subscribed_shows)})", size=18, weight=ft.FontWeight.W_800),
            ], spacing=8)

            sub_grid = ft.GridView(
                runs_count=4,
                max_extent=200,
                child_aspect_ratio=0.8,
                spacing=16,
                run_spacing=16,
            )

            for show in self.subscribed_shows:
                sub_grid.controls.append(self._build_show_card(show))

            self.content_area.controls.extend([header, sub_grid])
        else:
            self._show_empty_welcome()

        safe_update(self)

    def _show_empty_welcome(self) -> None:
        self.content_area.controls = [
            ft.Container(
                alignment=ft.Alignment.CENTER,
                padding=60,
                content=ft.Column(
                    horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                    spacing=12,
                    controls=[
                        ft.Icon(ft.Icons.PODCASTS, size=56, color=ft.Colors.PURPLE_400),
                        ft.Text("No Podcast Subscriptions Yet", size=18, weight=ft.FontWeight.BOLD, color=self._mt.text_primary),
                        ft.Text("Search for any podcast in the search bar above or add an RSS feed directly to subscribe.", size=13, color=self._mt.text_secondary)
                    ]
                )
            )
        ]
        safe_update(self)

    def _do_search(self) -> None:
        query = self.search_input.value.strip() if self.search_input.value else ""
        if not query:
            self.load_subscriptions()
            return

        self.content_area.scroll = ft.ScrollMode.AUTO
        self._active_search_id += 1
        request_id = self._active_search_id
        self._search_error = None
        cached = self.cache.get_search_results(query, limit=20)
        if cached is not None:
            self.search_results, fetched_at = cached
            self._render_search_results()
            if time.time() - fetched_at < PODCAST_CACHE_TTL_SECONDS:
                return
        else:
            self._current_screen = "loading"
            self.content_area.controls = [
                ft.Container(alignment=ft.Alignment.CENTER, padding=40, content=ft.ProgressRing())
            ]
            safe_update(self)

        threading.Thread(
            target=self._search_worker,
            args=(query, request_id),
            daemon=True,
        ).start()

    def _search_worker(self, query: str, request_id: int) -> None:
        try:
            shows = self.provider.search_itunes(query, limit=20)
            self.cache.store_search_results(query, 20, shows)
            error = None
        except Exception as exc:
            logger.warning("Podcast search refresh failed for %r: %s", query, exc)
            shows = None
            error = str(exc)

        async def apply_results() -> None:
            self._apply_search_results(query, request_id, shows, error)

        self.app_page.run_task(apply_results)

    def _apply_search_results(
        self,
        query: str,
        request_id: int,
        shows: Optional[List[PodcastShow]],
        error: Optional[str],
    ) -> None:
        if (
            request_id != self._active_search_id
            or self._current_screen not in ("search", "loading")
            or (self.search_input.value or "").strip() != query
        ):
            return

        if shows is not None:
            self.search_results = shows
            self._search_error = None
        else:
            self._search_error = error or "The podcast search could not be completed."
        self._render_search_results()

    def _on_search_submit(self, e) -> None:
        self._do_search()

    def _render_search_results(self) -> None:
        self._current_screen = "search"
        self.content_area.scroll = ft.ScrollMode.AUTO
        self.content_area.controls.clear()

        back_to_subs_btn = self._build_back_button(
            "My Subscriptions",
            lambda e: self.load_subscriptions(),
        )
        header = ft.Text(
            f"Search Results ({len(self.search_results)} podcasts)",
            size=16,
            weight=ft.FontWeight.BOLD,
        )

        if not self.search_results:
            message = (
                "Search could not be completed. Please check your connection and try again."
                if self._search_error
                else "No podcasts found."
            )
            self.content_area.controls.extend([
                back_to_subs_btn,
                header,
                ft.Container(alignment=ft.Alignment.CENTER, content=ft.Text(message, color=self._mt.text_secondary))
            ])
            safe_update(self)
            return

        results_grid = ft.GridView(
            runs_count=4,
            max_extent=200,
            child_aspect_ratio=0.8,
            spacing=16,
            run_spacing=16,
        )

        for show in self.search_results:
            results_grid.controls.append(self._build_show_card(show))

        controls: list[ft.Control] = [back_to_subs_btn, header]
        if self._search_error:
            controls.append(
                ft.Text("Showing saved results; the directory could not be refreshed.", color=self._mt.text_secondary, size=12)
            )
        controls.append(results_grid)
        self.content_area.controls.extend(controls)
        safe_update(self)

    def _build_show_card(self, show: PodcastShow) -> ft.Container:
        artwork = ft.Image(
            src=show.artwork_url or "",
            width=160,
            height=160,
            fit=ft.BoxFit.COVER,
            border_radius=0, # Metro square tiles
            error_content=ft.Container(
                bgcolor=self._mt.surface_variant,
                width=160,
                height=160,
                content=ft.Icon(ft.Icons.PODCASTS, size=48, color=ft.Colors.GREY_500)
            )
        )

        is_sub = self._is_subscribed(show.feed_url)

        return ft.Container(
            bgcolor=self._mt.surface_color,
            border=ft.Border.all(1, self._mt.border_color),
            padding=10,
            ink=True,
            on_click=lambda e, s=show: self._open_show_details(s),
            content=ft.Column(
                spacing=6,
                horizontal_alignment=ft.CrossAxisAlignment.START,
                controls=[
                    artwork,
                    ft.Text(show.title, size=13, weight=ft.FontWeight.BOLD, no_wrap=True, max_lines=1, overflow=ft.TextOverflow.ELLIPSIS),
                    ft.Row([
                        ft.Text(show.author, size=11, color=self._mt.text_secondary, no_wrap=True, max_lines=1, overflow=ft.TextOverflow.ELLIPSIS, expand=True),
                        ft.Icon(ft.Icons.CHECK_CIRCLE, size=14, color=self._mt.current_accent) if is_sub else ft.Container()
                    ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN)
                ]
            )
        )

    def _navigate_back(self) -> None:
        """Navigates back to the appropriate previous screen."""
        self._active_load_id += 1  # Invalidate any in-progress loading requests
        self._feed_refreshing = False
        self._feed_refresh_status = None
        if self._current_screen == "episode_detail" and self.selected_show:
            self._render_show_episodes(self.selected_show)
            return

        if self.search_results and self.search_input.value and self.search_input.value.strip():
            self._render_search_results()
        else:
            self.load_subscriptions()

    @staticmethod
    def _build_back_button(label: str, on_click: Callable) -> ft.Container:
        return ft.Container(
            alignment=ft.Alignment(-1.0, -1.0),
            padding=ft.Padding.only(bottom=4),
            content=ft.TextButton(
                label,
                icon=ft.Icons.ARROW_BACK,
                on_click=on_click,
            ),
        )

    def _open_show_details(self, show: PodcastShow, force_refresh: bool = False) -> None:
        """Displays cached feed data immediately and refreshes it when stale or requested."""
        self._active_load_id += 1
        request_id = self._active_load_id
        self._feed_refreshing = False
        self._feed_refresh_status = None
        cached = self.cache.get_feed(show.feed_url)

        if cached is not None:
            cached_show, fetched_at = cached
            self.selected_show = cached_show
            self._feed_refresh_error = None
            self._feed_refresh_status = None
            self._render_show_episodes(cached_show)
            if not force_refresh and time.time() - fetched_at < PODCAST_CACHE_TTL_SECONDS:
                return
            self._begin_feed_refresh(show, request_id, had_cached_data=True)
            return

        self._current_screen = "loading"
        loading_card = ft.Container(
            bgcolor=self._mt.surface_color,
            border=ft.Border.all(1, self._mt.border_color),
            border_radius=8,
            padding=32,
            width=500,
            content=ft.Column(
                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                spacing=16,
                controls=[
                    ft.ProgressRing(width=44, height=44, stroke_width=3, color=self._mt.current_accent),
                    ft.Text("Loading Podcast Episodes...", size=18, weight=ft.FontWeight.BOLD, color=self._mt.text_primary),
                    ft.Text(show.title, size=15, weight=ft.FontWeight.W_600, color=self._mt.current_accent, max_lines=1, overflow=ft.TextOverflow.ELLIPSIS),
                    ft.Text(f"by {show.author}" if show.author else "Connecting to RSS feed...", size=13, color=self._mt.text_secondary, max_lines=1, overflow=ft.TextOverflow.ELLIPSIS),
                    ft.Text("Fetching feed and extracting audio episodes from the server. This may take a few moments.", size=12, color=ft.Colors.GREY_500, text_align=ft.TextAlign.CENTER),
                    ft.Container(height=8),
                ]
            )
        )
        back_top_btn = self._build_back_button(
            "Back",
            lambda e: self._navigate_back(),
        )
        self.content_area.controls = [
            back_top_btn,
            ft.Container(
                alignment=ft.Alignment.CENTER,
                padding=ft.Padding.only(top=30),
                content=loading_card
            )
        ]
        safe_update(self)
        self._begin_feed_refresh(show, request_id, had_cached_data=False)

    def _begin_feed_refresh(
        self,
        show: PodcastShow,
        request_id: int,
        had_cached_data: bool,
    ) -> None:
        self._feed_refreshing = True
        self._feed_refresh_status = "Checking for new episodes..."
        if had_cached_data:
            self._render_show_episodes(self.selected_show or show)
        else:
            safe_update(self)
        threading.Thread(
            target=self._feed_refresh_worker,
            args=(show, request_id, had_cached_data),
            daemon=True,
        ).start()

    def _feed_refresh_worker(
        self,
        show: PodcastShow,
        request_id: int,
        had_cached_data: bool,
    ) -> None:
        try:
            detailed_show = self.provider.parse_feed(show.feed_url)
            if not detailed_show or not detailed_show.episodes:
                raise ValueError("The feed contains no playable episodes.")
            cached = self.cache.get_feed(show.feed_url)
            if cached is not None:
                cached_episodes = {
                    episode.id: episode for episode in cached[0].episodes
                }
                for episode in detailed_show.episodes:
                    cached_episode = cached_episodes.get(episode.id)
                    if (
                        cached_episode
                        and cached_episode.audio_url == episode.audio_url
                        and cached_episode.download_path
                        and os.path.isfile(cached_episode.download_path)
                    ):
                        episode.is_downloaded = True
                        episode.download_path = cached_episode.download_path
            self.cache.store_feed(detailed_show)
            error = None
        except Exception as exc:
            logger.warning("Podcast feed refresh failed for %r: %s", show.feed_url, exc)
            detailed_show = None
            error = str(exc)

        async def apply_feed() -> None:
            self._apply_feed_refresh(
                show,
                request_id,
                detailed_show,
                error,
                had_cached_data,
            )

        self.app_page.run_task(apply_feed)

    def _apply_feed_refresh(
        self,
        requested_show: PodcastShow,
        request_id: int,
        detailed_show: Optional[PodcastShow],
        error: Optional[str],
        had_cached_data: bool,
    ) -> None:
        if request_id != self._active_load_id:
            return
        self._feed_refreshing = False
        self._feed_refresh_status = None
        if detailed_show is not None:
            self._feed_refresh_error = None
            self.selected_show = detailed_show
            self._render_show_episodes(detailed_show)
        elif had_cached_data and self.selected_show:
            self._feed_refresh_error = "Could not check for updates; showing saved episodes."
            self._render_show_episodes(self.selected_show)
        else:
            logger.error("Unable to load podcast feed %r: %s", requested_show.feed_url, error)
            self._feed_refresh_error = None
            self._render_load_error(requested_show)

    def _render_load_error(self, show: PodcastShow) -> None:
        """Renders an error screen when the podcast feed could not be loaded."""
        self._current_screen = "error"
        self.content_area.scroll = ft.ScrollMode.AUTO

        error_card = ft.Container(
            bgcolor=self._mt.surface_color,
            border=ft.Border.all(1, ft.Colors.RED_900),
            border_radius=8,
            padding=32,
            width=520,
            content=ft.Column(
                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                spacing=14,
                controls=[
                    ft.Icon(ft.Icons.ERROR_OUTLINE, size=52, color=ft.Colors.RED_400),
                    ft.Text("Could Not Load Podcast", size=18, weight=ft.FontWeight.BOLD, color=self._mt.text_primary),
                    ft.Text(show.title, size=15, weight=ft.FontWeight.W_600, color=self._mt.text_secondary, max_lines=1, overflow=ft.TextOverflow.ELLIPSIS),
                    ft.Text(
                        "We couldn't retrieve or parse episodes from this feed URL. "
                        "The server might be unreachable or the feed format may be invalid.",
                        size=12,
                        color=ft.Colors.GREY_400,
                        text_align=ft.TextAlign.CENTER
                    ),
                    ft.Container(height=8),
                    ft.FilledButton(
                        "Try Again",
                        icon=ft.Icons.REFRESH,
                        on_click=lambda e, s=show: self._open_show_details(s)
                    )
                ]
            )
        )

        back_top_btn = self._build_back_button(
            "Back",
            lambda e: self._navigate_back(),
        )

        self.content_area.controls = [
            back_top_btn,
            ft.Container(
                alignment=ft.Alignment.CENTER,
                padding=ft.Padding.only(top=30),
                content=error_card
            )
        ]
        safe_update(self)

    def _render_show_episodes(self, show: PodcastShow) -> None:
        self._current_screen = "details"
        self.selected_show = show
        self._episode_render_id += 1
        render_id = self._episode_render_id
        self.content_area.scroll = None
        back_btn = self._build_back_button(
            "Back",
            lambda e: self._navigate_back(),
        )

        is_sub = self._is_subscribed(show.feed_url)
        sub_btn = ft.FilledButton(
            content="Subscribed" if is_sub else "Subscribe",
            icon=ft.Icons.CHECK if is_sub else ft.Icons.ADD,
        )
        sub_btn.on_click = lambda e: self._toggle_subscription(show, sub_btn)
        refresh_btn = ft.IconButton(
            icon=ft.Icons.REFRESH,
            tooltip="Refresh podcast episodes",
            disabled=self._feed_refreshing,
            on_click=lambda e, s=show: self._open_show_details(s, force_refresh=True),
        )
        episode_sort = ft.Dropdown(
            value=self._episode_sort_order,
            options=[
                ft.dropdown.Option("date_desc", "Newest first"),
                ft.dropdown.Option("date_asc", "Oldest first"),
            ],
            width=145,
            height=36,
            content_padding=ft.Padding.symmetric(horizontal=8, vertical=4),
            text_size=12,
            border_color=self._mt.border_color,
            focused_border_color=self._mt.current_accent,
            on_select=lambda e, selected_show=show: self._on_episode_sort_change(
                e, selected_show
            ),
        )

        header = ft.Row(
            spacing=16,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
            controls=[
                ft.Image(src=show.artwork_url or "", width=110, height=110, fit=ft.BoxFit.COVER),
                ft.Column(
                    spacing=4,
                    expand=True,
                    controls=[
                        ft.Text(show.title, size=20, weight=ft.FontWeight.BOLD),
                        ft.Text(show.author, size=13, color=self._mt.text_secondary),
                        ft.Text(f"{len(show.episodes)} episodes available", size=12, color=ft.Colors.GREY_400),
                        ft.Row(
                            spacing=4,
                            controls=[sub_btn, refresh_btn, episode_sort],
                        ),
                        ft.Text(
                            self._feed_refresh_status or self._feed_refresh_error or "",
                            size=11,
                            color=self._mt.text_secondary,
                            visible=bool(self._feed_refresh_status or self._feed_refresh_error),
                        ),
                    ]
                )
            ]
        )

        episodes_list = ft.ListView(spacing=8, expand=True)
        show_description = self._clean_html_text(show.description)
        show_description_card = (
            ft.Container(
                bgcolor=self._mt.surface_color,
                border=ft.Border.all(1, self._mt.border_color),
                padding=16,
                content=ft.Column(
                    spacing=8,
                    controls=[
                        ft.Text(
                            "ABOUT THIS PODCAST",
                            size=12,
                            weight=ft.FontWeight.BOLD,
                            color=self._mt.current_accent,
                        ),
                        ft.Text(
                            show_description,
                            size=13,
                            color=self._mt.text_secondary,
                            selectable=True,
                        ),
                    ],
                ),
            )
            if show_description
            else None
        )
        episodes_list.controls.extend([back_btn, header])
        if show_description_card is not None:
            episodes_list.controls.append(show_description_card)
        episodes_list.controls.append(ft.Divider(height=1))
        dated_episodes = [
            episode for episode in show.episodes if episode.published_at is not None
        ]
        undated_episodes = [
            episode for episode in show.episodes if episode.published_at is None
        ]
        dated_episodes.sort(
            key=lambda episode: episode.published_at or 0,
            reverse=self._episode_sort_order == "date_desc",
        )
        ordered_episodes = [*dated_episodes, *undated_episodes]
        initial_episodes = ordered_episodes[:INITIAL_EPISODE_BATCH_SIZE]
        episodes_list.controls.extend(
            self._build_episode_row(episode, show)
            for episode in initial_episodes
        )
        self._episode_render_episodes = ordered_episodes
        self._episode_render_offset = len(initial_episodes)
        self._episode_batch_loading = False
        if len(initial_episodes) < len(ordered_episodes):
            episodes_list.on_scroll = lambda event: self._on_episode_list_scroll(
                event, show, render_id, episodes_list
            )

        self.content_area.controls = [episodes_list]
        safe_update(self)

    def _on_episode_sort_change(self, event, show: PodcastShow) -> None:
        selected_order = getattr(event, "control", None)
        value = getattr(selected_order, "value", None)
        if value not in ("date_desc", "date_asc"):
            return
        if value == self._episode_sort_order:
            return
        self._episode_sort_order = value
        self._render_show_episodes(show)

    def _build_episode_row(self, episode: Episode, show: PodcastShow) -> ft.Container:
        description = self._clean_html_text(episode.description)
        if len(description) > 130:
            description = description[:130] + "..."

        duration_label = ""
        if episode.duration > 0:
            hours = int(episode.duration // 3600)
            minutes = int((episode.duration % 3600) // 60)
            seconds = int(episode.duration % 60)
            duration_label = (
                f"{hours}h {minutes}m" if hours > 0 else f"{minutes}:{seconds:02d}"
            )

        episode_menu = self._build_episode_menu(episode, show)

        return ft.Container(
            bgcolor=self._mt.surface_color,
            border=ft.Border.all(1, self._mt.border_color),
            padding=12,
            border_radius=4,
            ink=True,
            tooltip="Click to view episode details",
            on_click=lambda e, ep=episode, selected_show=show: self._open_episode_details(
                ep, selected_show
            ),
            content=ft.Row(
                spacing=12,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
                controls=[
                    ft.IconButton(
                        icon=ft.Icons.PLAY_CIRCLE_FILL,
                        icon_color=self._mt.current_accent,
                        icon_size=34,
                        tooltip="Play Episode",
                        on_click=lambda e, ep=episode, selected_show=show: self.on_play_episode(
                            ep, selected_show
                        ),
                    ),
                    ft.Column(
                        spacing=3,
                        expand=True,
                        controls=[
                            ft.Text(
                                episode.title,
                                size=14,
                                weight=ft.FontWeight.W_600,
                                no_wrap=True,
                                max_lines=1,
                                overflow=ft.TextOverflow.ELLIPSIS,
                            ),
                            ft.Text(
                                description,
                                size=12,
                                color=self._mt.text_secondary,
                                max_lines=2,
                            ),
                        ],
                    ),
                    ft.Column(
                        horizontal_alignment=ft.CrossAxisAlignment.END,
                        spacing=4,
                        controls=[
                            ft.Text(
                                duration_label,
                                size=11,
                                color=ft.Colors.GREY_400,
                            ) if duration_label else ft.Container(),
                            ft.Icon(
                                ft.Icons.CHEVRON_RIGHT,
                                size=18,
                                color=self._mt.text_secondary,
                            ),
                        ],
                    ),
                    episode_menu,
                ],
            ),
        )

    def _build_episode_menu(
        self, episode: Episode, show: PodcastShow
    ) -> ft.PopupMenuButton:
        is_downloaded = bool(
            episode.download_path and os.path.isfile(episode.download_path)
        )
        episode.is_downloaded = is_downloaded
        if not is_downloaded:
            episode.download_path = None

        menu_items: list[ft.PopupMenuItem] = []
        if self.on_play_next:
            menu_items.append(
                ft.PopupMenuItem(
                    content="Play Next",
                    icon=ft.Icons.PLAY_ARROW,
                    on_click=lambda e, ep=episode, selected_show=show: self.on_play_next(
                        self._episode_as_track(ep, selected_show)
                    ),
                )
            )
        if self.on_add_queue:
            menu_items.append(
                ft.PopupMenuItem(
                    content="Add to Queue",
                    icon=ft.Icons.QUEUE_MUSIC,
                    on_click=lambda e, ep=episode, selected_show=show: self.on_add_queue(
                        self._episode_as_track(ep, selected_show)
                    ),
                )
            )
        download_item = ft.PopupMenuItem(
            content="Delete Download" if is_downloaded else "Download Episode",
            icon=ft.Icons.DELETE_OUTLINE if is_downloaded else ft.Icons.DOWNLOAD,
        )
        download_item.on_click = lambda e, ep=episode, selected_show=show, item=download_item: (
            self._delete_episode_download(ep, selected_show, item)
            if ep.is_downloaded
            else self._start_episode_download(ep, selected_show, item)
        )
        menu_items.append(download_item)
        episode_menu = ft.PopupMenuButton(
            icon=ft.Icons.MORE_VERT,
            tooltip="Episode options",
            items=menu_items,
        )
        return episode_menu

    @staticmethod
    def _episode_as_track(episode: Episode, show: PodcastShow) -> Track:
        local_path = (
            episode.download_path
            if episode.download_path and os.path.isfile(episode.download_path)
            else None
        )
        return Track(
            id=f"pod_{episode.id}",
            title=episode.title,
            artist=show.author or show.title,
            album=show.title,
            duration=episode.duration,
            file_path=local_path or episode.audio_url,
            source="local" if local_path else "stream",
            artwork_url=show.artwork_url,
        )

    @staticmethod
    def _download_episode_id(episode: Episode) -> str:
        identity = episode.id or episode.audio_url
        return hashlib.sha256(identity.encode("utf-8")).hexdigest()[:24]

    def _start_episode_download(
        self,
        episode: Episode,
        show: PodcastShow,
        menu_item: ft.PopupMenuItem,
    ) -> None:
        if episode.id in self._downloading_episode_ids:
            return
        if not episode.audio_url:
            show_snackbar(self.app_page, "This episode has no downloadable audio URL.")
            return

        self._downloading_episode_ids.add(episode.id)
        menu_item.content = "Downloading..."
        menu_item.disabled = True
        safe_update(self)
        threading.Thread(
            target=self._download_episode_worker,
            args=(episode, show, menu_item),
            daemon=True,
        ).start()

    def _download_episode_worker(
        self,
        episode: Episode,
        show: PodcastShow,
        menu_item: ft.PopupMenuItem,
    ) -> None:
        try:
            if self._audio_cache is None:
                self._audio_cache = CacheManager()
            download_path = self._audio_cache.download_for_offline(
                episode.audio_url,
                self._download_episode_id(episode),
                episode.title,
            )
            error = None if download_path else "The episode could not be downloaded."
        except Exception as exc:
            logger.exception("Podcast episode download failed for %r", episode.audio_url)
            download_path = None
            error = str(exc)

        async def apply_download() -> None:
            self._downloading_episode_ids.discard(episode.id)
            menu_item.disabled = False
            if download_path:
                episode.download_path = download_path
                episode.is_downloaded = True
                self.cache.store_feed(show)
                menu_item.content = "Delete Download"
                menu_item.icon = ft.Icons.DELETE_OUTLINE
                show_snackbar(self.app_page, f"Downloaded '{episode.title}'")
            else:
                menu_item.content = "Download Episode"
                menu_item.icon = ft.Icons.DOWNLOAD
                logger.warning(
                    "Podcast episode download failed for %r: %s",
                    episode.audio_url,
                    error,
                )
                show_snackbar(self.app_page, error or "The episode could not be downloaded.")
            safe_update(self)

        self.app_page.run_task(apply_download)

    def _delete_episode_download(
        self,
        episode: Episode,
        show: PodcastShow,
        menu_item: ft.PopupMenuItem,
    ) -> None:
        path = episode.download_path
        if path and os.path.isfile(path):
            offline_dir = os.path.realpath(OFFLINE_DIR)
            resolved_path = os.path.realpath(path)
            safe_title = "".join(
                char for char in episode.title
                if char.isalnum() or char in (" ", "_", "-")
            ).strip()
            expected_path = os.path.realpath(
                os.path.join(
                    offline_dir,
                    f"{safe_title}_{self._download_episode_id(episode)}.mp3",
                )
            )
            try:
                is_managed_download = os.path.commonpath(
                    [offline_dir, resolved_path]
                ) == offline_dir and resolved_path == expected_path
            except ValueError:
                is_managed_download = False
            if not is_managed_download:
                logger.error("Refusing to delete podcast download outside offline directory: %s", path)
                show_snackbar(self.app_page, "Could not safely delete this episode download.")
                return
            try:
                os.remove(resolved_path)
            except OSError as exc:
                logger.exception("Could not delete podcast episode download %r", path)
                show_snackbar(self.app_page, f"Could not delete download: {exc}")
                return

        episode.download_path = None
        episode.is_downloaded = False
        self.cache.store_feed(show)
        menu_item.content = "Download Episode"
        menu_item.icon = ft.Icons.DOWNLOAD
        safe_update(self)
        show_snackbar(self.app_page, f"Deleted download for '{episode.title}'")

    def _on_episode_list_scroll(
        self,
        event: ft.OnScrollEvent,
        show: PodcastShow,
        render_id: int,
        episodes_list: ft.ListView,
    ) -> None:
        if (
            render_id != self._episode_render_id
            or self._current_screen != "details"
            or self.selected_show is None
            or self.selected_show.feed_url != show.feed_url
            or self._episode_batch_loading
            or self._episode_render_offset >= len(self._episode_render_episodes)
            or event.max_scroll_extent <= 0
            or event.pixels < event.max_scroll_extent / 2
        ):
            return

        self._episode_batch_loading = True
        try:
            self.app_page.run_task(
                self._append_next_episode_batch,
                show,
                render_id,
                episodes_list,
            )
        except Exception:
            self._episode_batch_loading = False
            raise

    async def _append_next_episode_batch(
        self,
        show: PodcastShow,
        render_id: int,
        episodes_list: ft.ListView,
    ) -> None:
        try:
            await asyncio.sleep(0)
            if (
                render_id != self._episode_render_id
                or self._current_screen != "details"
                or self.selected_show is None
                or self.selected_show.feed_url != show.feed_url
            ):
                return

            start = self._episode_render_offset
            batch = self._episode_render_episodes[start:start + EPISODE_BATCH_SIZE]
            if not batch:
                return
            episodes_list.controls.extend(
                self._build_episode_row(episode, show)
                for episode in batch
            )
            self._episode_render_offset += len(batch)
            safe_update(self)
        finally:
            if render_id == self._episode_render_id:
                self._episode_batch_loading = False

    def _clean_html_text(self, raw_html: str) -> str:
        """Strips HTML tags and unescapes entities for clean readable descriptions."""
        if not raw_html:
            return ""
        # Unescape HTML entities
        text = html.unescape(raw_html)
        # Convert <br>, <p> into newlines
        text = re.sub(r'<(br|p|/p)[^>]*>', '\n', text, flags=re.IGNORECASE)
        # Remove remaining tags
        text = re.sub(r'<[^>]+>', '', text)
        # Normalize repeated blank lines and whitespace
        text = re.sub(r'\n{3,}', '\n\n', text)
        return text.strip()

    def _open_episode_details(self, episode: Episode, show: PodcastShow) -> None:
        """Opens dedicated page with episode description, duration, thumbnail, full title, and play button."""
        self._active_load_id += 1
        self._feed_refreshing = False
        self._feed_refresh_status = None
        self.content_area.scroll = ft.ScrollMode.AUTO
        self.selected_episode = episode
        self._current_screen = "episode_detail"

        back_btn = self._build_back_button(
            "Back",
            lambda e: self._navigate_back(),
        )

        # Duration formatting
        dur_display = "Unknown"
        if episode.duration > 0:
            hrs = int(episode.duration // 3600)
            mins = int((episode.duration % 3600) // 60)
            secs = int(episode.duration % 60)
            if hrs > 0:
                dur_display = f"{hrs} hr {mins} min {secs} sec"
            else:
                dur_display = f"{mins} min {secs} sec"

        # Published date formatting
        pub_display = "Unknown"
        if episode.published_at:
            try:
                pub_display = time.strftime("%B %d, %Y", time.localtime(episode.published_at))
            except Exception:
                pub_display = "Unknown"

        # Episode thumbnail
        thumb_url = show.artwork_url or ""
        thumbnail = ft.Image(
            src=thumb_url,
            width=180,
            height=180,
            fit=ft.BoxFit.COVER,
            border_radius=8,
            error_content=ft.Container(
                bgcolor=self._mt.surface_variant,
                width=180,
                height=180,
                border_radius=8,
                alignment=ft.Alignment(0, 0),
                content=ft.Icon(ft.Icons.PODCASTS, size=64, color=ft.Colors.GREY_500)
            )
        )

        play_button = ft.FilledButton(
            "Play Episode",
            icon=ft.Icons.PLAY_ARROW,
            height=42,
            on_click=lambda e: self.on_play_episode(episode, show)
        )
        episode_menu = self._build_episode_menu(episode, show)

        # Header metadata card
        metadata_col = ft.Column(
            spacing=8,
            expand=True,
            controls=[
                ft.Text(show.title.upper(), size=12, weight=ft.FontWeight.BOLD, color=self._mt.current_accent),
                ft.Text(episode.title, size=22, weight=ft.FontWeight.W_800, color=self._mt.text_primary, selectable=True),
                ft.Row(
                    spacing=16,
                    wrap=True,
                    controls=[
                        ft.Row([
                            ft.Icon(ft.Icons.SCHEDULE, size=15, color=self._mt.text_secondary),
                            ft.Text(f"Duration: {dur_display}", size=12, color=self._mt.text_secondary)
                        ], spacing=4),
                        ft.Row([
                            ft.Icon(ft.Icons.CALENDAR_TODAY, size=15, color=self._mt.text_secondary),
                            ft.Text(f"Released: {pub_display}", size=12, color=self._mt.text_secondary)
                        ], spacing=4),
                        ft.Row([
                            ft.Icon(ft.Icons.PERSON, size=15, color=self._mt.text_secondary),
                            ft.Text(show.author or "Unknown Host", size=12, color=self._mt.text_secondary)
                        ], spacing=4)
                    ]
                ),
                ft.Container(height=6),
                ft.Row([play_button, episode_menu], spacing=8)
            ]
        )

        header_card = ft.Container(
            bgcolor=self._mt.surface_color,
            border=ft.Border.all(1, self._mt.border_color),
            border_radius=8,
            padding=20,
            content=ft.Row(
                spacing=24,
                vertical_alignment=ft.CrossAxisAlignment.START,
                controls=[thumbnail, metadata_col]
            )
        )

        # Description view
        clean_desc = self._clean_html_text(episode.description) or "No description provided for this episode."

        description_card = ft.Container(
            bgcolor=self._mt.surface_color,
            border=ft.Border.all(1, self._mt.border_color),
            border_radius=8,
            padding=24,
            expand=True,
            content=ft.Column(
                spacing=12,
                scroll=ft.ScrollMode.AUTO,
                controls=[
                    ft.Text("EPISODE DESCRIPTION", size=13, weight=ft.FontWeight.BOLD, color=self._mt.current_accent),
                    ft.Divider(height=1),
                    ft.Text(
                        clean_desc,
                        size=14,
                        color=self._mt.text_primary,
                        selectable=True
                    )
                ]
            )
        )

        self.content_area.controls = [
            back_btn,
            header_card,
            description_card
        ]
        safe_update(self)

    def _show_add_rss_dialog(self, e) -> None:
        url_input = ft.TextField(label="Podcast RSS Feed URL", hint_text="https://...")

        def parse_and_open(e):
            if url_input.value:
                show = PodcastShow(id="rss_custom", title="Custom Podcast", feed_url=url_input.value)
                close_dialog(self.app_page, self.dialog)
                self._open_show_details(show)

        self.dialog = ft.AlertDialog(
            title=ft.Text("Subscribe via RSS", weight=ft.FontWeight.BOLD),
            content=url_input,
            actions=[
                ft.TextButton("Cancel", on_click=lambda e: close_dialog(self.app_page, self.dialog)),
                ft.FilledButton("Load Podcast", on_click=parse_and_open)
            ]
        )
        open_dialog(self.app_page, self.dialog)
