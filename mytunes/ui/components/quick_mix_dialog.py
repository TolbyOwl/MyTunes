import flet as ft
from typing import List, Callable, Optional
from mytunes.models.track import Track
from mytunes.core.shuffle import ShuffleEngine
from mytunes.ui.dialog_utils import open_dialog, close_dialog

class QuickMixDialog:
    """Dialog to configure and launch instant smart mixes and shuffles."""

    def __init__(
        self,
        page: ft.Page,
        all_tracks: List[Track],
        on_mix_generated: Callable[[List[Track], str], None]
    ):
        self.page = page
        self.all_tracks = all_tracks
        self.on_mix_generated = on_mix_generated
        self.dialog: Optional[ft.AlertDialog] = None

    def show(self) -> None:
        count_dropdown = ft.Dropdown(
            label="Mix Length",
            value="25",
            options=[
                ft.dropdown.Option("10", "10 Songs (~35 min)"),
                ft.dropdown.Option("25", "25 Songs (~1.5 hours)"),
                ft.dropdown.Option("50", "50 Songs (~3 hours)"),
                ft.dropdown.Option("100", "100 Songs (All Day)"),
            ],
            width=220
        )

        mode_dropdown = ft.Dropdown(
            label="Shuffle Strategy",
            value="gems",
            options=[
                ft.dropdown.Option("gems", "Forgotten Gems & Deep Cuts"),
                ft.dropdown.Option("artist", "Smart Artist-Distributed"),
                ft.dropdown.Option("energy", "Tempo / BPM Energy Flow"),
                ft.dropdown.Option("random", "True Random (Unbiased)"),
            ],
            width=280
        )

        favs_switch = ft.Switch(
            label="Favorites Only",
            value=False
        )

        # Available genres
        genres = sorted(list({t.genre for t in self.all_tracks if t.genre and t.genre != "Unknown Genre"}))
        genre_options = [ft.dropdown.Option("all", "All Genres")] + [ft.dropdown.Option(g) for g in genres[:30]]
        genre_dropdown = ft.Dropdown(
            label="Genre Filter",
            value="all",
            options=genre_options,
            width=220
        )

        start_btn = ft.FilledButton(
            "Generate & Play",
            icon=ft.Icons.AUTO_AWESOME,
            on_click=lambda e: self._generate_and_play(
                count_str=count_dropdown.value,
                mode=mode_dropdown.value,
                genre=genre_dropdown.value,
                favorites_only=favs_switch.value
            )
        )

        close_btn = ft.TextButton("Cancel", on_click=lambda e: self._close())

        self.dialog = ft.AlertDialog(
            title=ft.Row([
                ft.Icon(ft.Icons.AUTO_AWESOME, color=ft.Colors.AMBER_400),
                ft.Text("Quick Music Mix", weight=ft.FontWeight.BOLD, size=20)
            ]),
            content=ft.Column(
                tight=True,
                spacing=16,
                controls=[
                    ft.Text("Instantly generate a tailored playlist from your library.", size=13, color=ft.Colors.GREY_400),
                    ft.Row([count_dropdown, genre_dropdown], spacing=12),
                    mode_dropdown,
                    favs_switch,
                ]
            ),
            actions=[close_btn, start_btn],
            actions_alignment=ft.MainAxisAlignment.END,
        )

        open_dialog(self.page, self.dialog)

    def _generate_and_play(self, count_str: str, mode: str, genre: str, favorites_only: bool) -> None:
        count = int(count_str) if count_str.isdigit() else 25
        
        # 1. Base filter
        mix_pool = ShuffleEngine.quick_mix(
            self.all_tracks,
            count=len(self.all_tracks),
            genre=genre,
            favorites_only=favorites_only
        )

        # 2. Apply chosen shuffle algorithm
        if mode == "gems":
            shuffled = ShuffleEngine.forgotten_gems(mix_pool)
            mix_name = f"Forgotten Gems Mix ({count} tracks)"
        elif mode == "artist":
            shuffled = ShuffleEngine.smart_artist_distributed(mix_pool)
            mix_name = f"Artist-Distributed Mix ({count} tracks)"
        elif mode == "energy":
            shuffled = ShuffleEngine.tempo_energy_flow(mix_pool)
            mix_name = f"Energy Flow Mix ({count} tracks)"
        else:
            shuffled = ShuffleEngine.true_random(mix_pool)
            mix_name = f"True Random Mix ({count} tracks)"

        final_mix = shuffled[:count]
        self._close()
        self.on_mix_generated(final_mix, mix_name)

    def _close(self) -> None:
        close_dialog(self.page, self.dialog)
