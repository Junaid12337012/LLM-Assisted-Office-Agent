from __future__ import annotations

from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import threading
from typing import Any
from urllib.parse import urlparse

from app.runtime import build_services


HTML = """<!doctype html>
<html lang=\"en\">
<head>
  <meta charset=\"utf-8\" />
  <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\" />
  <title>Office Automation Platform</title>
  <style>
    :root {
      --bg: #f4efe7;
      --panel: #fffaf2;
      --ink: #1d1d1b;
      --muted: #6e665b;
      --line: #d8ccb9;
      --accent: #235347;
      --accent-2: #d17b0f;
      --danger: #a1271d;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      font-family: Georgia, 'Times New Roman', serif;
      color: var(--ink);
      background: radial-gradient(circle at top, #fff7ea 0%, var(--bg) 52%, #eadfce 100%);
    }
    .shell {
      display: grid;
      grid-template-columns: 300px 1fr;
      min-height: 100vh;
    }
    .sidebar, .main {
      padding: 24px;
    }
    .sidebar {
      border-right: 1px solid var(--line);
      background: rgba(255, 250, 242, 0.88);
      backdrop-filter: blur(12px);
    }
    .brand {
      margin-bottom: 24px;
    }
    .brand h1 {
      margin: 0 0 8px;
      font-size: 28px;
      line-height: 1;
    }
    .brand p {
      margin: 0;
      color: var(--muted);
      font-size: 14px;
    }
    .command-list {
      display: grid;
      gap: 10px;
    }
    .command-button, .run-button, .history-item button {
      width: 100%;
      border: 1px solid var(--line);
      background: white;
      color: var(--ink);
      padding: 12px 14px;
      border-radius: 14px;
      cursor: pointer;
      text-align: left;
      transition: transform 0.15s ease, border-color 0.15s ease, box-shadow 0.15s ease;
    }
    .command-button:hover, .run-button:hover, .history-item button:hover {
      transform: translateY(-1px);
      border-color: var(--accent);
      box-shadow: 0 10px 20px rgba(35, 83, 71, 0.08);
    }
    .command-button strong {
      display: block;
      margin-bottom: 4px;
      font-size: 14px;
    }
    .command-button span {
      color: var(--muted);
      font-size: 12px;
    }
    .panel {
      background: rgba(255, 250, 242, 0.9);
      border: 1px solid var(--line);
      border-radius: 24px;
      padding: 20px;
      margin-bottom: 18px;
      box-shadow: 0 16px 34px rgba(82, 62, 31, 0.08);
    }
    .panel h2 {
      margin: 0 0 14px;
      font-size: 20px;
    }
    .hero {
      display: grid;
      gap: 14px;
    }
    .hero textarea {
      width: 100%;
      min-height: 84px;
      resize: vertical;
      border: 1px solid var(--line);
      border-radius: 18px;
      padding: 14px;
      font: inherit;
      background: white;
      color: var(--ink);
    }
    .toolbar {
      display: flex;
      gap: 12px;
      align-items: center;
      flex-wrap: wrap;
    }
    .run-button {
      width: auto;
      background: var(--accent);
      color: white;
      border-color: var(--accent);
      font-weight: bold;
      padding: 12px 20px;
    }
    .check {
      display: inline-flex;
      align-items: center;
      gap: 8px;
      color: var(--muted);
      font-size: 13px;
    }
    .status-card {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
      gap: 12px;
      margin-top: 12px;
    }
    .metric {
      background: white;
      border: 1px solid var(--line);
      border-radius: 16px;
      padding: 12px;
    }
    .metric strong {
      display: block;
      font-size: 12px;
      color: var(--muted);
      margin-bottom: 6px;
      text-transform: uppercase;
      letter-spacing: 0.08em;
    }
    .metric span {
      font-size: 16px;
      font-weight: bold;
    }
    .history-grid {
      display: grid;
      gap: 10px;
    }
    .history-item button {
      background: #fff;
    }
    .history-meta {
      display: flex;
      gap: 10px;
      flex-wrap: wrap;
      margin-top: 8px;
      color: var(--muted);
      font-size: 12px;
    }
    .pill {
      display: inline-flex;
      align-items: center;
      padding: 4px 8px;
      border-radius: 999px;
      border: 1px solid var(--line);
      background: #fff;
      font-size: 12px;
    }
    .pill.completed { border-color: var(--accent); color: var(--accent); }
    .pill.failed { border-color: var(--danger); color: var(--danger); }
    .pill.running { border-color: var(--accent-2); color: var(--accent-2); }
    .logs {
      display: grid;
      gap: 10px;
    }
    .log-item {
      border-left: 3px solid var(--accent);
      padding: 12px 12px 12px 14px;
      background: white;
      border-radius: 12px;
      border: 1px solid var(--line);
    }
    .log-item.failed, .log-item.validation_failed { border-left-color: var(--danger); }
    .empty {
      color: var(--muted);
      font-style: italic;
    }
    @media (max-width: 920px) {
      .shell { grid-template-columns: 1fr; }
      .sidebar { border-right: 0; border-bottom: 1px solid var(--line); }
    }
  </style>
</head>
<body>
  <div class=\"shell\">
    <aside class=\"sidebar\">
      <div class=\"brand\">
        <h1>Phase 1</h1>
        <p>Command runner, workflow engine, logs, and a usable local GUI.</p>
      </div>
      <div id=\"commandList\" class=\"command-list\"></div>
    </aside>
    <main class=\"main\">
      <section class=\"panel hero\">
        <h2>Run Command</h2>
        <textarea id=\"commandInput\">run workspace.open_all</textarea>
        <div class=\"toolbar\">
          <button id=\"runButton\" class=\"run-button\">Run</button>
          <label class=\"check\"><input id=\"safeMode\" type=\"checkbox\" checked /> Safe mode</label>
          <label class=\"check\"><input id=\"confirmRisk\" type=\"checkbox\" /> Approve risky actions</label>
        </div>
        <div class=\"status-card\">
          <div class=\"metric\"><strong>Status</strong><span id=\"statusValue\">Idle</span></div>
          <div class=\"metric\"><strong>Last Run ID</strong><span id=\"runIdValue\">-</span></div>
          <div class=\"metric\"><strong>Last Command</strong><span id=\"commandValue\">-</span></div>
        </div>
      </section>
      <section class=\"panel\">
        <h2>Recent Runs</h2>
        <div id=\"historyList\" class=\"history-grid\"></div>
      </section>
      <section class=\"panel\">
        <h2>Step Logs</h2>
        <div id=\"logList\" class=\"logs\"></div>
      </section>
    </main>
  </div>
  <script>
    const commandInput = document.getElementById('commandInput');
    const safeMode = document.getElementById('safeMode');
    const confirmRisk = document.getElementById('confirmRisk');
    const statusValue = document.getElementById('statusValue');
    const runIdValue = document.getElementById('runIdValue');
    const commandValue = document.getElementById('commandValue');
    const historyList = document.getElementById('historyList');
    const logList = document.getElementById('logList');
    const commandList = document.getElementById('commandList');
    const runButton = document.getElementById('runButton');

    async function loadCommands() {
      const response = await fetch('/api/commands');
      const commands = await response.json();
      commandList.innerHTML = '';
      commands.forEach((command) => {
        const button = document.createElement('button');
        button.className = 'command-button';
        button.innerHTML = `<strong>${command.name}</strong><span>${command.description}</span>`;
        button.addEventListener('click', () => {
          commandInput.value = `run ${command.name}`;
        });
        commandList.appendChild(button);
      });
    }

    async function loadRuns(selectRunId = null) {
      const response = await fetch('/api/runs');
      const runs = await response.json();
      historyList.innerHTML = '';
      if (!runs.length) {
        historyList.innerHTML = '<div class="empty">No runs yet.</div>';
        return;
      }
      runs.forEach((run) => {
        const item = document.createElement('div');
        item.className = 'history-item';
        const button = document.createElement('button');
        const statusClass = `pill ${run.status}`;
        button.innerHTML = `
          <strong>${run.command_name}</strong>
          <div class="history-meta">
            <span class="${statusClass}">${run.status}</span>
            <span>#${run.id}</span>
            <span>${run.started_at}</span>
          </div>
        `;
        button.addEventListener('click', () => loadRunDetails(run.id));
        item.appendChild(button);
        historyList.appendChild(item);
      });
      if (selectRunId) {
        loadRunDetails(selectRunId);
      }
    }

    async function loadRunDetails(runId) {
      const response = await fetch(`/api/runs/${runId}`);
      const payload = await response.json();
      const run = payload.run;
      const steps = payload.steps;
      runIdValue.textContent = run.id;
      statusValue.textContent = run.status;
      commandValue.textContent = run.command_name;
      logList.innerHTML = '';
      if (!steps.length) {
        logList.innerHTML = '<div class="empty">No step logs for this run yet.</div>';
        return;
      }
      steps.forEach((step) => {
        const item = document.createElement('div');
        item.className = `log-item ${step.status}`;
        item.innerHTML = `
          <strong>${step.step_id}</strong>
          <div>${step.message || ''}</div>
          <div class="history-meta">
            <span>${step.status}</span>
            <span>${step.created_at}</span>
          </div>
        `;
        logList.appendChild(item);
      });
    }

    async function runCommand() {
      const rawCommand = commandInput.value.trim();
      if (!rawCommand) {
        alert('Enter a command first.');
        return;
      }
      runButton.disabled = true;
      statusValue.textContent = 'Running';
      commandValue.textContent = rawCommand;
      try {
        const response = await fetch('/api/run', {
          method: 'POST',
          headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({
            raw_command: rawCommand,
            safe_mode: safeMode.checked,
            confirm_risky: confirmRisk.checked
          })
        });
        const payload = await response.json();
        if (!response.ok) {
          throw new Error(payload.error || 'Run failed');
        }
        statusValue.textContent = payload.outcome.status;
        runIdValue.textContent = payload.outcome.run_id || '-';
        await loadRuns(payload.outcome.run_id);
      } catch (error) {
        statusValue.textContent = 'failed';
        logList.innerHTML = `<div class="log-item failed"><strong>Run failed</strong><div>${error.message}</div></div>`;
      } finally {
        runButton.disabled = false;
      }
    }

    runButton.addEventListener('click', runCommand);
    loadCommands();
    loadRuns();
  </script>
</body>
</html>
"""


class WebGuiServer(ThreadingHTTPServer):
    def __init__(self, server_address: tuple[str, int], handler_class: type[BaseHTTPRequestHandler]) -> None:
        super().__init__(server_address, handler_class)
        self.services = build_services()
        self.run_lock = threading.Lock()


class WebGuiHandler(BaseHTTPRequestHandler):
    server: WebGuiServer

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        if parsed.path in {"/", "/index.html"}:
            self._html_response(HTML)
            return
        if parsed.path == "/api/commands":
            commands = [
                {
                    "name": command.name,
                    "description": command.description,
                    "workflow_id": command.workflow_id,
                    "risk": command.risk,
                }
                for command in self.server.services.registry.list_commands()
            ]
            self._json_response(commands)
            return
        if parsed.path == "/api/runs":
            self._json_response(self.server.services.memory_store.list_runs())
            return
        if parsed.path.startswith("/api/runs/"):
            run_id_text = parsed.path.rsplit("/", 1)[-1]
            if not run_id_text.isdigit():
                self._json_response({"error": "Invalid run id."}, status=HTTPStatus.BAD_REQUEST)
                return
            run_id = int(run_id_text)
            run = self.server.services.memory_store.get_run(run_id)
            if run is None:
                self._json_response({"error": "Run not found."}, status=HTTPStatus.NOT_FOUND)
                return
            payload = {
                "run": run,
                "steps": self.server.services.memory_store.list_step_logs(run_id),
            }
            self._json_response(payload)
            return
        self._json_response({"error": "Not found."}, status=HTTPStatus.NOT_FOUND)

    def do_POST(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        if parsed.path != "/api/run":
            self._json_response({"error": "Not found."}, status=HTTPStatus.NOT_FOUND)
            return

        body = self._read_json()
        raw_command = str(body.get("raw_command") or "").strip()
        safe_mode = bool(body.get("safe_mode", True))
        confirm_risky = bool(body.get("confirm_risky", False))
        if not raw_command:
            self._json_response({"error": "raw_command is required."}, status=HTTPStatus.BAD_REQUEST)
            return

        if not self.server.run_lock.acquire(blocking=False):
            self._json_response(
                {"error": "Another run is already in progress. Wait for it to finish first."},
                status=HTTPStatus.CONFLICT,
            )
            return

        try:
            command, inputs = self.server.services.registry.parse_invocation(raw_command)
            outcome = self.server.services.engine.run(
                command,
                inputs,
                safe_mode=safe_mode,
                confirmation_handler=lambda _message: confirm_risky,
            )
            payload = {
                "outcome": {
                    "run_id": outcome.run_id,
                    "status": outcome.status,
                    "completed_steps": outcome.completed_steps,
                    "summary": outcome.summary,
                    "last_error": outcome.last_error,
                },
                "run": self.server.services.memory_store.get_run(outcome.run_id) if outcome.run_id else None,
                "steps": self.server.services.memory_store.list_step_logs(outcome.run_id) if outcome.run_id else [],
            }
            self._json_response(payload)
        except Exception as exc:
            self._json_response({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
        finally:
            self.server.run_lock.release()

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A003
        return

    def _read_json(self) -> dict[str, Any]:
        content_length = int(self.headers.get("Content-Length", "0"))
        raw_body = self.rfile.read(content_length) if content_length else b"{}"
        return json.loads(raw_body.decode("utf-8") or "{}")

    def _html_response(self, content: str, status: HTTPStatus = HTTPStatus.OK) -> None:
        payload = content.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def _json_response(self, payload: Any, status: HTTPStatus = HTTPStatus.OK) -> None:
        raw = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)



def run_server(host: str = "127.0.0.1", port: int = 8765) -> None:
    server = WebGuiServer((host, port), WebGuiHandler)
    print(f"Office Automation GUI running at http://{host}:{port}")
    server.serve_forever()


if __name__ == "__main__":
    run_server()
