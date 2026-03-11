# LLM-Assisted-Office-Agent

Phase 1 MVP for a self-owned desktop automation platform.

This repository implements a deterministic automation core with:

- A command registry with typed parameters
- A workflow engine with validation, branching, retries, and recovery hooks
- Safety gates for risky actions
- SQLite-backed run logging
- Review queue storage for difficult cases
- Evidence/artifact extraction for review and debugging
- Windows desktop and browser controller baselines
- A Windows desktop GUI, plus an optional console fallback
- A Phase 3 assistant layer that turns natural requests into approved workflow plans

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
It also includes a Phase 1 failure inbox, run status/search filters, evidence path viewer, remembered desktop preferences, and an assistant plan preview for natural-language requests such as `start today's office work` or `note call the vendor before lunch`.

## Phase 2 MVP additions

The current build now includes a narrow Phase 2 document workflow:

- `phase2.read_invoice_id` crops a known document region, prepares it for OCR, validates the extracted ID, and writes a result file
- low-confidence or invalid OCR cases are sent to the review queue instead of failing silently
- failure evidence is captured into `data/evidence/screenshots`
- the desktop GUI includes a review queue dialog for approving or correcting queued items

## Phase 3 MVP additions

The current build now includes a controlled orchestration layer:

- the command bar can interpret natural-language requests and map them to approved workflows
- multi-step bundles such as `start today's office work` expand into a safe workflow sequence
- risky instructions such as upload requests are downgraded to review/confirmation instead of auto-running
- repeat-style requests can reuse the latest successful run from history
- plan preview and execution stay inside the desktop app and backend bridge, so validation, logging, and review rules still apply

## Phase 4 foundation

The current build now includes the first operator-mode foundation:

- SQLite-backed operator sessions, queued tasks, checkpoints, and operator exceptions
- a session manager that can create a work session from a natural request
- queue controls for run next, run full queue, pause, and resume from saved progress
- operator exceptions that block only the affected task instead of the full platform
- a desktop Operator Dashboard for creating and supervising sessions

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

Run a natural-language instruction directly:

```powershell
powershell -ExecutionPolicy Bypass -File .\run_app.ps1 run "start today's office work"
```

Create an operator session from the backend bridge:

```powershell
.\.tools\python311\runtime\python.exe .\desktop_backend.py operator-create-session --instruction "start today's office work"
.\.tools\python311\runtime\python.exe .\desktop_backend.py operator-run-session --session-id 1
```

Run the automated tests:

```powershell
powershell -ExecutionPolicy Bypass -File .\run_tests.ps1
```
