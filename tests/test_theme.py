import tempfile
import unittest
from pathlib import Path

from PIL import Image

from mytunes.ui.theme import MetroTheme


class TestMetroTheme(unittest.TestCase):
    def test_find_dominant_accent_does_not_mutate_theme(self):
        theme = MetroTheme()
        with tempfile.TemporaryDirectory() as directory:
            image_path = Path(directory) / "cover.png"
            Image.new("RGB", (8, 8), (220, 50, 60)).save(image_path)

            color = theme.find_dominant_accent(str(image_path))

            self.assertEqual(color, "#dc323c")
            self.assertIsNone(theme.dynamic_accent)
            self.assertEqual(theme.extract_dominant_accent(str(image_path)), color)
            self.assertEqual(theme.dynamic_accent, color)


if __name__ == "__main__":
    unittest.main()
