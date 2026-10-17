from __future__ import annotations
import os
from typing import Optional, Tuple
from PIL import Image
import flet as ft

# Metro / Groove UI Color Palette Presets
METRO_ACCENTS = {
    "Groove Blue": "#0078D7",
    "Zune Orange": "#E95420",
    "Metro Purple": "#744DA9",
    "Lumia Cyan": "#00A4EF",
    "Xbox Green": "#107C10",
    "Crimson Red": "#E81123",
    "Neon Teal": "#00B294",
    "Hot Magenta": "#E3008C"
}

class MetroTheme:
    """Manages Metro / Groove UI styles, colors, and dynamic album art palette extraction."""

    def __init__(self, is_dark: bool = True, default_accent: str = "#0078D7"):
        self.is_dark = is_dark
        self.accent_color = default_accent
        self.dynamic_accent: Optional[str] = None

    @property
    def current_accent(self) -> str:
        return self.dynamic_accent or self.accent_color

    @property
    def bg_color(self) -> str:
        return "#121212" if self.is_dark else "#F5F5F7"

    @property
    def surface_color(self) -> str:
        return "#1E1E1E" if self.is_dark else "#FFFFFF"

    @property
    def surface_variant(self) -> str:
        return "#252525" if self.is_dark else "#EBEBEB"

    @property
    def text_primary(self) -> str:
        return "#FFFFFF" if self.is_dark else "#1A1A1A"

    @property
    def text_secondary(self) -> str:
        return "#9E9E9E" if self.is_dark else "#6E6E73"

    @property
    def border_color(self) -> str:
        return "#2D2D2D" if self.is_dark else "#E0E0E0"

    def extract_dominant_accent(self, image_path: str) -> Optional[str]:
        """
        Extracts dominant vibrant color from album artwork image using PIL.
        Converts image to thumbnail and finds vibrant saturated color.
        """
        if not image_path or not os.path.exists(image_path):
            return None

        try:
            with Image.open(image_path) as img:
                img = img.convert("RGB")
                img.thumbnail((48, 48))

                colors = img.getcolors(maxcolors=48 * 48)
                if not colors:
                    return None

                # Find color with high saturation and balanced luminance
                best_color = None
                best_score = -1.0

                for count, (r, g, b) in colors:
                    # Calculate luminance
                    lum = 0.299 * r + 0.587 * g + 0.114 * b
                    # Calculate saturation approximation
                    max_c = max(r, g, b)
                    min_c = min(r, g, b)
                    sat = (max_c - min_c) / max(max_c, 1)

                    # Favor colors with decent saturation and not pitch black or pure white
                    if 0.25 <= sat <= 0.95 and 40 <= lum <= 210:
                        score = sat * 100 + count * 0.1
                        if score > best_score:
                            best_score = score
                            best_color = (r, g, b)

                if best_color:
                    hex_color = f"#{best_color[0]:02x}{best_color[1]:02x}{best_color[2]:02x}"
                    self.dynamic_accent = hex_color
                    return hex_color
        except Exception:
            pass

        return None

    def __getstate__(self) -> dict:
        """Return a JSON‑serializable representation of the theme.
        Only primitive types are included to avoid Flet serialization errors.
        """
        return {
            "is_dark": self.is_dark,
            "accent_color": self.accent_color,
            "dynamic_accent": self.dynamic_accent,
        }

    def __setstate__(self, state: dict) -> None:
        """Restore the theme from the given state dictionary."""
        self.is_dark = state.get("is_dark", True)
        self.accent_color = state.get("accent_color", "#0078D7")
        self.dynamic_accent = state.get("dynamic_accent")
    def reset_dynamic_accent(self) -> None:
        """Reset dynamic accent to None."""
        self.dynamic_accent = None
