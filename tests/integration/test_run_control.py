from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from core.models import RunControl
from tests.helpers import build_runtime


class RunControlIntegrationTests(unittest.TestCase):
    def test_stop_before_run_returns_stopped(self) -> None:
        with TemporaryDirectory() as temp_dir:
            runtime = build_runtime(Path(temp_dir))
            command = runtime.registry.get("workspace.open_all")
            control = RunControl()
            control.request_stop()
            outcome = runtime.engine.run(
                command,
                {},
                safe_mode=False,
                confirmation_handler=lambda _message: True,
                control=control,
            )
            self.assertEqual(outcome.status, "stopped")


if __name__ == "__main__":
    unittest.main()
