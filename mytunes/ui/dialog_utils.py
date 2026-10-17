from __future__ import annotations
import flet as ft
from typing import Optional

def safe_update(control: ft.Control) -> None:
    """Safely updates a control only if it is already mounted to the page."""
    try:
        if getattr(control, "page", None) is not None:
            control.update()
    except Exception:
        pass

def show_snackbar(page: ft.Page, message: str) -> None:
    """Displays a snackbar message compatible with both Flet 1.0+ and 0.x."""
    snack = ft.SnackBar(ft.Text(message))
    if hasattr(page, "show_dialog"):
        page.show_dialog(snack)
    else:
        page.snack_bar = snack
        snack.open = True
        page.update()

def open_dialog(page: ft.Page, dialog: ft.AlertDialog) -> None:
    """Opens a modal dialog compatible with both Flet 1.0+ and 0.x."""
    if hasattr(page, "show_dialog"):
        page.show_dialog(dialog)
    else:
        page.dialog = dialog
        dialog.open = True
        page.update()

def close_dialog(page: ft.Page, dialog: Optional[ft.AlertDialog] = None) -> None:
    """Closes a modal dialog compatible with both Flet 1.0+ and 0.x."""
    if hasattr(page, "pop_dialog"):
        page.pop_dialog()
    elif dialog:
        dialog.open = False
        page.update()
