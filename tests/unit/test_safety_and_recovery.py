from __future__ import annotations

import unittest
from pathlib import Path

from core.command_registry import CommandRegistry
from core.models import SafetyViolation
from core.recovery import ErrorSignatureRegistry
from core.safety import SafetyGate


class SafetyAndRecoveryTests(unittest.TestCase):
    def setUp(self) -> None:
        root = Path(__file__).resolve().parents[2]
        self.registry = CommandRegistry.from_file(root / "registry" / "commands.json")
        self.safety_gate = SafetyGate.from_file(root / "registry" / "policies.json")
        self.signatures = ErrorSignatureRegistry.from_file(root / "registry" / "error_signatures.json")

    def test_high_risk_command_requires_confirmation(self) -> None:
        command = self.registry.get("portal.upload_latest_file")
        with self.assertRaises(SafetyViolation):
            self.safety_gate.authorize_command(command, safe_mode=False, confirmation_handler=None)

    def test_recovery_signature_match(self) -> None:
        snapshot = {
            "browser": {"current_url": "https://upload.example.local/portal"},
            "desktop": {"active_window": "Entry Manager"},
        }
        match = self.signatures.match("Temporary upload error while submitting", snapshot)
        self.assertIsNotNone(match)
        self.assertEqual(match["id"], "temporary_upload_error")


if __name__ == "__main__":
    unittest.main()
