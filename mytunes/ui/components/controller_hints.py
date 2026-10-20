import flet as ft


_BUTTON_COLORS = {
    "A": ft.Colors.GREEN_400,
    "B": ft.Colors.RED_400,
    "X": ft.Colors.BLUE_400,
    "Y": ft.Colors.YELLOW_600,
}

_DIRECTION_ICONS = {
    "D-pad ↑/↓": ft.Icons.SWAP_VERT,
    "D-pad ←/→": ft.Icons.SWAP_HORIZ,
    "LT/RT": ft.Icons.FAST_FORWARD,
    "LB/RB": ft.Icons.SWAP_HORIZ,
    "Start": ft.Icons.QUEUE_MUSIC,
    "Back": ft.Icons.FULLSCREEN,
}


def build_controller_hints(hints: dict[str, str], text_color: str) -> list[ft.Control]:
    """Builds compact button badges paired with their controller actions."""
    controls: list[ft.Control] = []
    for label, action in hints.items():
        if label in _BUTTON_COLORS:
            badge = ft.Container(
                width=18,
                height=18,
                alignment=ft.Alignment.CENTER,
                border=ft.Border.all(1, _BUTTON_COLORS[label]),
                border_radius=9,
                content=ft.Text(
                    label,
                    size=10,
                    weight=ft.FontWeight.BOLD,
                    color=_BUTTON_COLORS[label],
                    text_align=ft.TextAlign.CENTER,
                ),
            )
        else:
            badge = ft.Icon(
                _DIRECTION_ICONS.get(label, ft.Icons.GAMEPAD),
                size=15,
                color=text_color,
            )

        controls.append(
            ft.Row(
                spacing=3,
                tight=True,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
                controls=[
                    badge,
                    ft.Text(action, size=10, color=text_color, no_wrap=True),
                ],
            )
        )
    return controls
