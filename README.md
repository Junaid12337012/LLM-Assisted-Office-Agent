# LLM-Assisted-Office-Agent

Phase 1 MVP for a self-owned desktop automation platform.

This repository implements a deterministic automation core with:

- A command registry with typed parameters
- A workflow engine with validation, branching, retries, and recovery hooks
- Safety gates for risky actions
- SQLite-backed run logging
- Windows desktop and browser controller baselines
- A Windows desktop GUI, plus an optional console fallback

The code is designed so an LLM layer can be added later without bypassing
workflow safety, validation, or logging.

## Quick start

Launch the desktop GUI MVP:

```powershell
powershell -ExecutionPolicy Bypass -File .\run_app.ps1
```

Or double-click `start_agent.cmd`.

## GUI workflow

The desktop window now gives you three ways to use the agent:

- Type a shortcut into the GUI command bar: `start day`, `note Finish invoices`, `download report`, `end day`, `paint`
- Click a quick-action button on the left
- Select a workflow and fill its guided form fields

The GUI fills sensible defaults such as today's date and standard export paths.
It also includes a Phase 1 failure inbox, run status/search filters, evidence path viewer, and remembered desktop preferences such as safe mode and the last selected command.

## Other launch modes

Open the desktop app explicitly:

```powershell
powershell -ExecutionPolicy Bypass -File .\run_app.ps1 --desktop
```

Open the console fallback:

```powershell
powershell -ExecutionPolicy Bypass -File .\run_app.ps1 --console
```

Run one command directly:

```powershell
powershell -ExecutionPolicy Bypass -File .\run_app.ps1 run mvp.start_day run_date=2026-03-11
```

Run the automated tests:

```powershell
powershell -ExecutionPolicy Bypass -File .\run_tests.ps1
```
