from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from core.state_contracts import ScreenContractRegistry
from core.state_detector import StateDetector


class StateDetectorTests(unittest.TestCase):
    def test_detector_matches_voucher_list_screen_contract(self) -> None:
        with TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            registry = ScreenContractRegistry.from_file(
                Path(__file__).resolve().parents[2] / "registry" / "screen_contracts.json"
            )
            detector = StateDetector(registry)

            snapshot = {
                "active_window": "Voucher List",
                "controls": ["From Date", "To Date", "LoadButton", "PrintButton"],
                "texts": ["Voucher", "Print", "From Date", "To Date"],
            }

            detected = detector.detect(snapshot, app_name="voucher_app")

            self.assertEqual("matched", detected["status"])
            self.assertEqual("voucher_list", detected["current_screen_id"])
            self.assertGreaterEqual(detected["current_screen_confidence"], 0.45)


if __name__ == "__main__":
    unittest.main()
