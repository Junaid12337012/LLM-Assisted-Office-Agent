from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from training.screen_model import ScreenModel
from training.template_store import ScreenTemplateStore


class TrainingFoundationTests(unittest.TestCase):
    def test_template_store_saves_and_loads_templates(self) -> None:
        with TemporaryDirectory() as temp_dir:
            store = ScreenTemplateStore(Path(temp_dir) / "training")
            capture_path = store.captures_dir / "voucher_screen.png"
            capture_path.write_bytes(b"fake-png")

            saved = store.save_template(
                app_name="voucher_app",
                screen_name="voucher_print_page",
                window_title="Voucher Print",
                capture_path=str(capture_path),
                regions=[
                    {
                        "label": "print_button",
                        "role": "button",
                        "left": 420,
                        "top": 180,
                        "width": 132,
                        "height": 34,
                        "notes": "Main print action",
                    }
                ],
                expected_controls=["PrintButton", "DateField"],
                expected_texts=["Print Voucher"],
                notes="Primary voucher print layout",
            )

            self.assertEqual("voucher_app", saved["app_name"])
            self.assertTrue(Path(saved["capture_path"]).exists())

            listed = store.list_templates(app_name="voucher_app")
            self.assertEqual(1, len(listed))
            loaded = store.get_template(saved["template_id"])
            self.assertIsNotNone(loaded)
            assert loaded is not None
            self.assertEqual("voucher_print_page", loaded["screen_name"])
            self.assertEqual("PrintButton", loaded["expected_controls"][0])

    def test_screen_model_matches_saved_template(self) -> None:
        model = ScreenModel()
        templates = [
            {
                "template_id": "voucher_print_page",
                "app_name": "voucher_app",
                "screen_name": "voucher_print_page",
                "window_title": "Voucher Print",
                "expected_controls": ["PrintButton", "DateField"],
                "expected_texts": ["Print Voucher", "Today"],
                "regions": [{"label": "print_button"}],
                "capture_path": "data/training/captures/voucher_print.png",
            },
            {
                "template_id": "dashboard_home",
                "app_name": "voucher_app",
                "screen_name": "dashboard_home",
                "window_title": "Dashboard",
                "expected_controls": ["SearchBox"],
                "expected_texts": ["Welcome"],
                "regions": [],
                "capture_path": "",
            },
        ]
        snapshot = {
            "active_window": "Voucher Print - ERP",
            "controls": ["PrintButton", "DateField", "CloseButton"],
            "texts": ["Print Voucher", "Today", "Preview"],
        }

        analysis = model.analyze(snapshot, templates, app_name="voucher_app")

        self.assertEqual("matched", analysis["status"])
        self.assertIsNotNone(analysis["best_match"])
        assert analysis["best_match"] is not None
        self.assertEqual("voucher_print_page", analysis["best_match"]["template_id"])
        self.assertGreaterEqual(analysis["best_match"]["confidence"], 0.45)


if __name__ == "__main__":
    unittest.main()
