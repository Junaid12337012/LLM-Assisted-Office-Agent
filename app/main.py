from __future__ import annotations

import argparse

from app.runtime import build_services



def run_cli(raw_command: str, safe_mode: bool = False) -> int:
    services = build_services()
    command, inputs = services.registry.parse_invocation(raw_command)
    outcome = services.engine.run(
        command,
        inputs,
        safe_mode=safe_mode,
        confirmation_handler=lambda _message: True,
    )
    print(f"status={outcome.status}")
    print(f"summary={outcome.summary}")
    return 0 if outcome.status in {"completed", "stopped"} else 1



def main() -> None:
    parser = argparse.ArgumentParser(description="Office automation platform")
    parser.add_argument("command", nargs="*", help="Command to run in CLI mode")
    parser.add_argument("--cli", action="store_true", help="Run without the graphical UI")
    parser.add_argument("--web", action="store_true", help="Start the local web GUI")
    parser.add_argument("--safe-mode", action="store_true", help="Require extra confirmations")
    args = parser.parse_args()

    raw_command = " ".join(args.command).strip()
    if args.cli or raw_command:
        if not raw_command:
            parser.error("Provide a command when using --cli.")
        raise SystemExit(run_cli(raw_command, safe_mode=args.safe_mode))

    if args.web:
        from app.web_gui import run_server

        run_server()
        return

    try:
        from app.ui_tk import OfficeAgentTkApp
    except ModuleNotFoundError as exc:
        if exc.name == "tkinter":
            from app.web_gui import run_server

            run_server()
            return
        raise

    OfficeAgentTkApp().run()


if __name__ == "__main__":
    main()
