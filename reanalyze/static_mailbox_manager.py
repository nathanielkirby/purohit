"""Static manager variant that drains a CGI-host-local mailbox.

This supports deployments where the CGI host can write to its local /tmp or
/var/tmp, but that directory is not mounted on the submit/login host. The
manager pulls commands by HTTP(S) from the CGI endpoint and executes them on the
submit/login host.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import tempfile
import time
from typing import Any
from urllib import request
from urllib.error import HTTPError, URLError

from reanalyze.static_manager import append_audit, process_command
from reanalyze.static_monitor import publish_once

CONTROL_HTML = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Purohit command controls</title>
  <style>
    :root { color-scheme: light dark; }
    body { font-family: system-ui, -apple-system, BlinkMacSystemFont, sans-serif; margin: 2rem; line-height: 1.35; }
    .card { border: 1px solid rgba(128,128,128,0.25); border-radius: 12px; padding: 1rem; margin: 1rem 0; }
    table { width: 100%; border-collapse: collapse; margin-top: 0.5rem; }
    th, td { text-align: left; border-bottom: 1px solid rgba(128,128,128,0.25); padding: 0.55rem; font-size: 0.9rem; vertical-align: top; }
    code, input { padding: 0.1rem 0.25rem; border-radius: 4px; background: rgba(128,128,128,0.15); }
    button { margin: 0.08rem; border: 1px solid rgba(128,128,128,0.35); border-radius: 5px; padding: 0.25rem 0.45rem; cursor: pointer; }
    .muted { opacity: 0.72; }
    .small { font-size: 0.82rem; }
  </style>
</head>
<body>
  <h1>Purohit command controls</h1>
  <p class="muted">This page POSTs commands to the CGI mailbox endpoint. The static manager on the submit host drains the mailbox and executes commands on its next polling pass.</p>
  <div class="card">
    <div><strong>Mailbox URL:</strong> <code id="mailbox-url">loading...</code></div>
    <div><strong>Command token:</strong> <input id="token" type="password" placeholder="optional token"><button onclick="saveToken()">Save in this browser</button></div>
    <div id="result" class="small muted"></div>
  </div>
  <div class="card">
    <table><thead><tr><th>Event</th><th>Status</th><th>Cluster ID</th><th>Controls</th></tr></thead><tbody id="jobs"></tbody></table>
  </div>
<script>
let mailboxUrl = null;
function fmt(x) { return x === null || x === undefined || x === "" ? "—" : x; }
function saveToken() { localStorage.setItem("purohit_mailbox_token", document.getElementById("token").value || ""); }
function controls(event) {
  return `<button onclick="sendCommand('submit_event','${event}')">Submit</button><button onclick="sendCommand('hold_event','${event}')">Hold</button><button onclick="sendCommand('release_event','${event}')">Release</button><button onclick="sendCommand('remove_event','${event}')">Remove</button>`;
}
async function sendCommand(action, event) {
  if (!mailboxUrl) return;
  if (action === "remove_event" && !confirm(`Remove ${event}?`)) return;
  const token = localStorage.getItem("purohit_mailbox_token") || document.getElementById("token").value || "";
  const result = document.getElementById("result");
  result.textContent = `Queueing ${action} for ${event}...`;
  try {
    const response = await fetch(mailboxUrl, {method: "POST", headers: {"Content-Type": "application/json", "X-Purohit-Token": token}, body: JSON.stringify({action, event, token})});
    const data = await response.json();
    if (!response.ok || !data.ok) throw new Error(data.error || `HTTP ${response.status}`);
    result.textContent = `Queued ${action} for ${event}. The manager will execute it on the next polling pass.`;
  } catch (err) {
    result.textContent = `Command failed: ${err}`;
  }
}
async function refresh() {
  const response = await fetch(`mailbox_status.json?ts=${Date.now()}`, {cache: "no-store"});
  const config = await response.json();
  mailboxUrl = config.mailbox_url;
  document.getElementById("mailbox-url").textContent = mailboxUrl || "not configured";
  if (!document.getElementById("token").value) document.getElementById("token").value = localStorage.getItem("purohit_mailbox_token") || "";
  const statusResponse = await fetch(`status.json?ts=${Date.now()}`, {cache: "no-store"});
  const status = await statusResponse.json();
  const rows = (status.jobs || []).map(job => `<tr><td>${fmt(job.event)}</td><td>${fmt(job.status)}</td><td>${fmt(job.jobid)}</td><td>${controls(job.event)}</td></tr>`).join("");
  document.getElementById("jobs").innerHTML = rows || `<tr><td colspan="4">No jobs found.</td></tr>`;
}
refresh().catch(err => { document.getElementById("result").textContent = `error: ${err}`; });
setInterval(() => refresh().catch(console.error), 30000);
</script>
</body>
</html>
"""


def atomic_write_text(path: Path, text: str, mode: int = 0o644) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", dir=path.parent, delete=False) as handle:
        handle.write(text)
        tmp = Path(handle.name)
    tmp.replace(path)
    try:
        path.chmod(mode)
    except OSError:
        pass


def atomic_write_json(path: Path, data: Any, mode: int = 0o644) -> None:
    atomic_write_text(path, json.dumps(data, indent=2, sort_keys=True) + "\n", mode=mode)


def drain_mailbox(mailbox_url: str, token: str | None = None, timeout: int = 30) -> list[dict[str, Any]]:
    payload: dict[str, Any] = {"mode": "drain"}
    if token:
        payload["token"] = token
    body = json.dumps(payload).encode("utf-8")
    req = request.Request(mailbox_url, data=body, method="POST", headers={"Content-Type": "application/json"})
    if token:
        req.add_header("X-Purohit-Token", token)
    try:
        with request.urlopen(req, timeout=timeout) as response:
            data = json.loads(response.read().decode("utf-8"))
    except (HTTPError, URLError, TimeoutError, json.JSONDecodeError) as exc:
        return [{"action": "invalid", "error": f"mailbox drain failed: {exc}"}]
    if not isinstance(data, dict) or not data.get("ok"):
        return [{"action": "invalid", "error": f"mailbox drain failed: {data}"}]
    commands = data.get("commands", [])
    return [item for item in commands if isinstance(item, dict)] if isinstance(commands, list) else []


def process_remote_commands(project_dir: Path, mailbox_url: str, token: str | None = None) -> list[dict[str, Any]]:
    commands = drain_mailbox(mailbox_url, token=token)
    results: list[dict[str, Any]] = []
    for command in commands:
        result = process_command(project_dir, command) if command.get("action") != "invalid" else {"ok": False, "command": command, "message": command.get("error")}
        append_audit(project_dir, result)
        results.append(result)
    return results


def publish_control_page(webdir: Path, mailbox_url: str) -> None:
    webdir = webdir.expanduser().resolve()
    atomic_write_text(webdir / "commands.html", CONTROL_HTML)
    atomic_write_json(webdir / "mailbox_status.json", {"mailbox_url": mailbox_url, "generated_at": time.time()})


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run static Purohit manager with CGI mailbox draining.")
    parser.add_argument("--project-dir", required=True, type=Path)
    parser.add_argument("--webdir", required=True, type=Path)
    parser.add_argument("--mailbox-url", required=True, help="CGI mailbox endpoint URL, e.g. https://.../purohit_mailbox.cgi")
    parser.add_argument("--token-file", type=Path, default=None, help="Optional local token file also accepted by CGI.")
    parser.add_argument("--interval", type=int, default=60)
    parser.add_argument("--plot-interval", type=int, default=300)
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--no-history", action="store_true")
    parser.add_argument("--heartbeat-filename", default="heartbeat.json")
    parser.add_argument("--max-artifacts-per-event", type=int, default=40)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    project_dir = args.project_dir.expanduser().resolve()
    webdir = args.webdir.expanduser().resolve()
    token = args.token_file.expanduser().read_text().strip() if args.token_file and args.token_file.is_file() else None
    last_plot_publish = 0.0
    while True:
        results = process_remote_commands(project_dir, args.mailbox_url, token=token)
        now = time.time()
        copy_outputs = now - last_plot_publish >= args.plot_interval
        payload = publish_once(
            project_dir,
            webdir,
            include_history=not args.no_history,
            heartbeat_filename=args.heartbeat_filename,
            copy_outputs=copy_outputs,
            command_file=None,
            max_artifacts_per_event=args.max_artifacts_per_event,
        )
        publish_control_page(webdir, args.mailbox_url)
        if copy_outputs:
            last_plot_publish = now
        print(f"Drained {len(results)} command(s); published {len(payload['jobs'])} jobs to {webdir} at {time.strftime('%Y-%m-%d %H:%M:%S')}")
        if args.once:
            return
        time.sleep(args.interval)


if __name__ == "__main__":
    main()
