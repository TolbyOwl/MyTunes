import threading
import flet as ft
import time
import sqlite3
import re
import html
from typing import List, Callable, Optional
from mytunes.models.podcast import PodcastShow, Episode
from mytunes.providers.podcasts import PodcastProvider
from mytunes.ui.theme import MetroTheme
from mytunes.ui.dialog_utils import safe_update, show_snackbar, open_dialog, close_dialog

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
        on_play_episode: Callable[[Episode, PodcastShow], None]
    ):
        super().__init__()
        self.app_page = page
        self.conn = db_conn
        self._mt = theme
        self.provider = PodcastProvider()
        self.on_play_episode = on_play_episode

        self.subscribed_shows: List[PodcastShow] = []
        self.search_results: List[PodcastShow] = []
        self.selected_show: Optional[PodcastShow] = None
        self.selected_episode: Optional[Episode] = None
        self._current_screen: str = "subscriptions"  # "subscriptions", "search", "loading", "details", "episode_detail", "error"
        self._active_load_id: int = 0

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

        self.content_area.controls = [
            ft.Container(alignment=ft.Alignment.CENTER, padding=40, content=ft.ProgressRing())
        ]
        safe_update(self)

        self.search_results = self.provider.search_itunes(query, limit=20)
        self._render_search_results()

    def _on_search_submit(self, e) -> None:
        self._do_search()

    def _render_search_results(self) -> None:
        self._current_screen = "search"
        self.content_area.controls.clear()

        back_to_subs_btn = ft.TextButton("← My Subscriptions", on_click=lambda e: self.load_subscriptions())
        header = ft.Row([
            ft.Text(f"Search Results ({len(self.search_results)} podcasts)", size=16, weight=ft.FontWeight.BOLD),
            back_to_subs_btn
        ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN)

        if not self.search_results:
            self.content_area.controls.extend([
                header,
                ft.Container(alignment=ft.Alignment.CENTER, content=ft.Text("No podcasts found.", color=self._mt.text_secondary))
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

        self.content_area.controls.extend([header, results_grid])
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
        if self._current_screen == "episode_detail" and self.selected_show:
            self._render_show_episodes(self.selected_show)
            return

        if self.search_results and self.search_input.value and self.search_input.value.strip():
            self._render_search_results()
        else:
            self.load_subscriptions()

    def _open_show_details(self, show: PodcastShow) -> None:
        """Parses the podcast RSS feed in a background thread and renders episode list with loading & error screens."""
        self._active_load_id += 1
        current_load_id = self._active_load_id
        self._current_screen = "loading"

        # Dedicated loading view with podcast metadata & Back/Cancel action
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
                    ft.OutlinedButton(
                        "Cancel / Back",
                        icon=ft.Icons.ARROW_BACK,
                        on_click=lambda e: self._navigate_back()
                    )
                ]
            )
        )

        back_top_btn = ft.Row([
            ft.TextButton("Back", icon=ft.Icons.ARROW_BACK, on_click=lambda e: self._navigate_back())
        ])

        self.content_area.controls = [
            back_top_btn,
            ft.Container(
                alignment=ft.Alignment.CENTER,
                padding=ft.Padding.only(top=30),
                content=loading_card
            )
        ]
        safe_update(self)

        def on_fetch_completed(res_show):
            if self._active_load_id != current_load_id:
                return
            if not res_show or not res_show.episodes:
                self._render_load_error(show)
            else:
                self.selected_show = res_show
                self._render_show_episodes(res_show)

        def fetch_worker():
            try:
                detailed_show = self.provider.parse_feed(show.feed_url)
            except Exception:
                detailed_show = None

            # Ignore result if the user navigated away/canceled
            if self._active_load_id != current_load_id:
                return

            if hasattr(self.app_page, "run_task") and callable(self.app_page.run_task):
                async def _apply():
                    on_fetch_completed(detailed_show)
                self.app_page.run_task(_apply)
            else:
                on_fetch_completed(detailed_show)

        thread = threading.Thread(target=fetch_worker, daemon=True)
        thread.start()

    def _render_load_error(self, show: PodcastShow) -> None:
        """Renders an error screen when the podcast feed could not be loaded."""
        self._current_screen = "error"

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
                    ft.Row(
                        alignment=ft.MainAxisAlignment.CENTER,
                        spacing=12,
                        controls=[
                            ft.OutlinedButton(
                                "Back to Podcasts",
                                icon=ft.Icons.ARROW_BACK,
                                on_click=lambda e: self._navigate_back()
                            ),
                            ft.FilledButton(
                                "Try Again",
                                icon=ft.Icons.REFRESH,
                                on_click=lambda e, s=show: self._open_show_details(s)
                            )
                        ]
                    )
                ]
            )
        )

        back_top_btn = ft.Row([
            ft.TextButton("Back", icon=ft.Icons.ARROW_BACK, on_click=lambda e: self._navigate_back())
        ])

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
        back_btn = ft.TextButton("Back", icon=ft.Icons.ARROW_BACK, on_click=lambda e: self._navigate_back())

        is_sub = self._is_subscribed(show.feed_url)
        sub_btn = ft.FilledButton(
            content="Subscribed" if is_sub else "Subscribe",
            icon=ft.Icons.CHECK if is_sub else ft.Icons.ADD,
        )
        sub_btn.on_click = lambda e: self._toggle_subscription(show, sub_btn)

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
                        ft.Container(content=sub_btn, padding=ft.Padding.only(top=6))
                    ]
                )
            ]
        )

        episodes_list = ft.ListView(spacing=8, expand=True)
        for ep in show.episodes:
            # Format duration display for the list item
            dur_str = ""
            if ep.duration > 0:
                hours = int(ep.duration // 3600)
                mins = int((ep.duration % 3600) // 60)
                secs = int(ep.duration % 60)
                dur_str = f"{hours}h {mins}m" if hours > 0 else f"{mins}:{secs:02d}"

            ep_row = ft.Container(
                bgcolor=self._mt.surface_color,
                border=ft.Border.all(1, self._mt.border_color),
                padding=12,
                border_radius=4,
                ink=True,
                tooltip="Click to view episode details",
                on_click=lambda e, ep_obj=ep, s=show: self._open_episode_details(ep_obj, s),
                content=ft.Row(
                    spacing=12,
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    controls=[
                        ft.IconButton(
                            icon=ft.Icons.PLAY_CIRCLE_FILL,
                            icon_color=self._mt.current_accent,
                            icon_size=34,
                            tooltip="Play Episode",
                            on_click=lambda e, ep_obj=ep: self.on_play_episode(ep_obj, show)
                        ),
                        ft.Column(
                            spacing=3,
                            expand=True,
                            controls=[
                                ft.Text(ep.title, size=14, weight=ft.FontWeight.W_600, no_wrap=True, max_lines=1, overflow=ft.TextOverflow.ELLIPSIS),
                                ft.Text(self._clean_html_text(ep.description)[:130] + "..." if len(self._clean_html_text(ep.description)) > 130 else self._clean_html_text(ep.description), size=12, color=self._mt.text_secondary, max_lines=2),
                            ]
                        ),
                        ft.Column(
                            horizontal_alignment=ft.CrossAxisAlignment.END,
                            spacing=4,
                            controls=[
                                ft.Text(dur_str, size=11, color=ft.Colors.GREY_400) if dur_str else ft.Container(),
                                ft.Icon(ft.Icons.CHEVRON_RIGHT, size=18, color=self._mt.text_secondary)
                            ]
                        )
                    ]
                )
            )
            episodes_list.controls.append(ep_row)

        self.content_area.controls = [back_btn, header, ft.Divider(height=1), episodes_list]
        safe_update(self)

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
        self.selected_episode = episode
        self._current_screen = "episode_detail"

        back_btn = ft.TextButton(
            "Back",
            icon=ft.Icons.ARROW_BACK,
            on_click=lambda e: self._navigate_back()
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
                ft.Row([play_button])
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
