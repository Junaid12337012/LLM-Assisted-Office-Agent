from __future__ import annotations

import unittest
from pathlib import Path

from core.command_registry import CommandRegistry
from core.models import ConfigurationError


class CommandRegistryTests(unittest.TestCase):
    def setUp(self) -> None:
        root = Path(__file__).resolve().parents[2]
        self.registry = CommandRegistry.from_file(root / "registry" / "commands.json")

    def test_parse_download_command(self) -> None:
        command, inputs = self.registry.parse_invocation(
            "run browser.download_daily_report download_dir=C:/tmp export_dir=C:/out run_date=2026-03-11"
        )
        self.assertEqual(command.name, "browser.download_daily_report")
        self.assertEqual(inputs["download_dir"], "C:/tmp")
        self.assertEqual(inputs["export_dir"], "C:/out")
        self.assertEqual(inputs["run_date"], "2026-03-11")

    def test_parse_windows_style_path(self) -> None:
        command, inputs = self.registry.parse_invocation(
            'run browser.download_daily_report download_dir="D:\\Temp\\downloads" export_dir="D:\\Temp\\exports" run_date=2026-03-11'
        )
        self.assertEqual(command.name, "browser.download_daily_report")
        self.assertEqual(inputs["download_dir"], "D:\\Temp\\downloads")
        self.assertEqual(inputs["export_dir"], "D:\\Temp\\exports")

    def test_parse_quick_note_with_quoted_text(self) -> None:
        command, inputs = self.registry.parse_invocation(
            'run mvp.note run_date=2026-03-11 note_text="Call the vendor before lunch" note_title="Priority Note"'
        )
        self.assertEqual(command.name, "mvp.note")
        self.assertEqual(inputs["run_date"], "2026-03-11")
        self.assertEqual(inputs["note_text"], "Call the vendor before lunch")
        self.assertEqual(inputs["note_title"], "Priority Note")

    def test_missing_required_parameter_raises(self) -> None:
        with self.assertRaises(ConfigurationError):
            self.registry.parse_invocation(
                "run browser.download_daily_report download_dir=C:/tmp export_dir=C:/out"
            )


if __name__ == "__main__":
    unittest.main()
