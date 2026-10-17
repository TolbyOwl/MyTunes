import sys
import os

# Ensure package directory is in sys.path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import flet as ft
from mytunes.main import main

if __name__ == "__main__":
    if hasattr(ft, "run"):
        ft.run(main)
    else:
        ft.app(target=main)
