"""Central multi-cluster command and status manager for Purohit.

The central manager does not submit jobs directly. Each cluster still runs its
own local Purohit tunnel/static manager, which submits and monitors jobs on that
cluster. The central manager pulls static status snapshots from those cluster
managers and routes commands by appending to each cluster's local tunnel command
queue over SSH.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import secrets
import shlex
import socket
import subprocess
import tempfile
import threading
import time
from typing import Any
from urllib.parse import parse_qs, urlparse

import yaml

QUEUE_FILENAME = "tunnel_commands.jsonl"
CENTRAL_STATUS_FILENAME = "central_status.json"
CENTRAL_HTML_FILENAME = "central.html"
CENTRAL_CONFIG_FILENAME = "central_config.json"

CENTRAL_HTML = r"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Purohit central command center</title>
  <style>
    :root { color-scheme: light dark; }
    body { font-family: system-ui, -apple-system, BlinkMacSystemFont, sans-serif; margin: 2rem; line-height: 1.35; }
    nav a { margin-right: 1rem; }
    .card { border: 1px solid rgba(128,128,128,0.25); border-radius: 12px; padding: 1rem; margin: 1rem 0; }
    table { width: 100%; border-collapse: collapse; margin-top: 0.5rem; }
    th, td { text-align: left; border-bottom: 1px solid rgba(128,128,128,0.25); padding: 0.52rem; font-size: 0.9rem; vertical-align: top; }
    code, input { padding: 0.15rem 0.35rem; border-radius: 4px; background: rgba(128,128,128,0.15); }
    input { min-width: 24rem; border: 1px solid rgba(128,128,128,0.35); }
    .btn { margin: 0.08rem; border: 1px solid rgba(128,128,128,0.35); border-radius: 6px; padding: 0.32rem 0.55rem; cursor: pointer; }
    .btn-primary { background: rgba(37,99,235,0.14); border-color: rgba(37,99,235,0.35); }
    .btn-danger { background: rgba(185,28,28,0.12); border-color: rgba(185,28,28,0.35); }
    .ok { color: #047857; font-weight: 700; }
    .bad { color: #b91c1c; font-weight: 700; }
    .muted { opacity: 0.72; }
    .small { font-size: 0.82rem; }
  </style>
</head>
<body>
  <h1>Purohit central command center</h1>
  <p class="muted">One browser endpoint that aggregates multiple cluster-local Purohit managers and routes commands to the appropriate cluster queue.</p>
  <div class="card">
    <div><strong>Central endpoint:</strong> <input id="endpoint" value="http://127.0.0.1:8770"><button class="btn" onclick="saveEndpoint()">Save endpoint</button></div>
    <div><strong>Token:</strong> <input id="token" type="password"><button class="btn" onclick="saveToken()">Save token</button><button class="btn" onclick="clearToken()">Clear token</button></div>
    <div id="message" class="small muted">Loading...</div>
  </div>
  <h2>Clusters</h2>
  <div class="card"><table><thead><tr><th>Cluster</th><th>Status</th><th>Jobs</th><th>Project</th><th>Webdir</th><th>Error</th></tr></thead><tbody id="clusters"></tbody></table></div>
  <h2>Jobs</h2>
  <div class="card"><table><thead><tr><th>Cluster</th><th>Event</th><th>Status</th><th>Cluster ID</th><th>Runtime</th><th>Remote host</th><th>Controls</th></tr></thead><tbody id="jobs"></tbody></table></div>
<script>
const DEFAULT_ENDPOINT = "http://127.0.0.1:8770";
function endpoint() { return (document.getElementById("endpoint").value || DEFAULT_ENDPOINT).replace(/\/$/, ""); }
function token() { return document.getElementById("token").value || localStorage.getItem("purohit_central_token") || ""; }
function saveEndpoint() { localStorage.setItem("purohit_central_endpoint", endpoint()); }
function saveToken() { localStorage.setItem("purohit_central_token", document.getElementById("token").value || ""); }
function clearToken() { localStorage.removeItem("purohit_central_token"); document.getElementById("token").value = ""; }
function fmt(x) { return x === null || x === undefined || x === "" ? "—" : x; }
function esc(x) { return String(x ?? "").replace(/[&<>]/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;"}[c])); }
async function readJson(response) { const text = await response.text(); try { return JSON.parse(text); } catch { return {ok:false, error:text.slice(0,300)}; } }
async function api(path, opts={}) {
  const headers = opts.headers || {}; headers["X-Purohit-Token"] = token();
  const response = await fetch(`${endpoint()}${path}`, {...opts, headers});
  const data = await readJson(response);
  if (!response.ok || data.ok === false) throw new Error(data.error || `HTTP ${response.status}`);
  return data;
}
function controls(cluster, event) {
  const encodedCluster = esc(cluster); const encodedEvent = esc(event);
  return `<button class="btn btn-primary" onclick="sendCommand('${encodedCluster}','submit_event','${encodedEvent}')">Submit</button><button class="btn" onclick="sendCommand('${encodedCluster}','hold_event','${encodedEvent}')">Hold</button><button class="btn" onclick="sendCommand('${encodedCluster}','release_event','${encodedEvent}')">Release</button><button class="btn btn-danger" onclick="sendCommand('${encodedCluster}','remove_event','${encodedEvent}')">Remove</button>`;
}
async function sendCommand(cluster, action, event) {
  if (action === "remove_event" && !confirm(`Remove ${event} on ${cluster}?`)) return;
  try {
    const data = await api("/api/command", {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify({cluster, action, event})});
    document.getElementById("message").textContent = `Queued ${action} for ${cluster}:${event} (${data.command.id}).`;
  } catch (err) { document.getElementById("message").textContent = `Command failed: ${err}`; }
}
async function refresh() {
  const savedEndpoint = localStorage.getItem("purohit_central_endpoint"); if (savedEndpoint) document.getElementById("endpoint").value = savedEndpoint;
  const savedToken = localStorage.getItem("purohit_central_token"); if (savedToken && !document.getElementById("token").value) document.getElementById("token").value = savedToken;
  const data = await api("/api/status");
  document.getElementById("message").textContent = `Generated ${new Date(data.generated_at * 1000).toLocaleString()}; ${data.jobs.length} jobs across ${data.clusters.length} clusters.`;
  document.getElementById("clusters").innerHTML = data.clusters.map(c => `<tr><td>${esc(c.name)}</td><td class="${c.ok ? "ok" : "bad"}">${c.ok ? "ok" : "error"}</td><td>${fmt(c.job_count)}</td><td><code>${esc(fmt(c.project_dir))}</code></td><td><code>${esc(fmt(c.webdir))}</code></td><td class="small">${esc(fmt(c.error))}</td></tr>`).join("") || `<tr><td colspan="6">No clusters configured.</td></tr>`;
  document.getElementById("jobs").innerHTML = data.jobs.map(j => `<tr><td>${esc(j.cluster)}</td><td>${esc(j.event)}</td><td>${esc(fmt(j.status))}</td><td>${esc(fmt(j.jobid))}</td><td>${esc(fmt(j.runtime))}</td><td>${esc(fmt(j.remote_host))}</td><td>${controls(j.cluster, j.event)}</td></tr>`).join("") || `<tr><td colspan="7">No jobs found.</td></tr>`;
}
refresh().catch(err => document.getElementById("message").textContent = `refresh error: ${err}`);
setInterval(() => refresh().catch(console.error), 30000);
</script>
</body>
</html>
"""


@dataclass(frozen=True)
class ClusterConfig:
    name: str
    project_dir: Path
    webdir: Path
    ssh: str | None = None
    queue_path: Path | None = None
    label: str | None = None

    @classmethod
    def from_mapping(cls, name: str, data: dict[str, Any]) -> "ClusterConfig":
        project_dir = Path(data["project_dir"]).expanduser()
        webdir = Path(data["webdir"]).expanduser()
        queue = data.get("queue_path")
        return cls(
            name=name,
            project_dir=project_dir,
            webdir=webdir,
            ssh=data.get("ssh"),
            queue_path=Path(queue).expanduser() if queue else project_dir / "control" / QUEUE_FILENAME,
            label=data.get("label"),
        )


def load_clusters(path: Path) -> list[ClusterConfig]:
    data = yaml.safe_load(path.expanduser().read_text()) or {}
    raw = data.get("clusters", data)
    if not isinstance(raw, dict):
        raise ValueError(f"central config must contain a clusters mapping: {path}")
    clusters = []
    for name, item in raw.items():
        if not isinstance(item, dict):
            raise ValueError(f"cluster {name!r} must be a mapping")
        clusters.append(ClusterConfig.from_mapping(str(name), item))
    return clusters


def run_checked(command: list[str], *, input_text: str | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, input=input_text, check=True, capture_output=True, text=True)


def remote_cat(cluster: ClusterConfig, path: Path) -> str:
    if cluster.ssh:
        return run_checked(["ssh", cluster.ssh, f"cat {shlex.quote(str(path))}"]).stdout
    return path.read_text()


def remote_append_jsonl(cluster: ClusterConfig, path: Path, payload: dict[str, Any]) -> None:
    line = json.dumps(payload, sort_keys=True) + "\n"
    if cluster.ssh:
        parent = shlex.quote(str(path.parent))
        target = shlex.quote(str(path))
        command = f"mkdir -p {parent} && cat >> {target} && chmod 600 {target}"
        run_checked(["ssh", cluster.ssh, command], input_text=line)
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a") as handle:
            handle.write(line)
        try:
            path.chmod(0o600)
        except OSError:
            pass


def load_remote_json(cluster: ClusterConfig, path: Path) -> Any:
    return json.loads(remote_cat(cluster, path))


def fetch_cluster_snapshot(cluster: ClusterConfig) -> dict[str, Any]:
    snapshot: dict[str, Any] = {"name": cluster.name, "label": cluster.label or cluster.name, "project_dir": str(cluster.project_dir), "webdir": str(cluster.webdir), "ok": False, "error": None, "status": None, "health": None, "command_results": None}
    try:
        snapshot["status"] = load_remote_json(cluster, cluster.webdir / "status.json")
        for filename, key in (("health.json", "health"), ("command_results.json", "command_results"), ("dag_details.json", "dag_details")):
            try:
                snapshot[key] = load_remote_json(cluster, cluster.webdir / filename)
            except Exception:
                snapshot[key] = None
        snapshot["ok"] = True
    except Exception as exc:  # noqa: BLE001 - per-cluster failure should not break aggregation
        snapshot["error"] = str(exc)
    return snapshot


def aggregate_snapshots(clusters: list[ClusterConfig], snapshots: list[dict[str, Any]]) -> dict[str, Any]:
    jobs: list[dict[str, Any]] = []
    cluster_rows: list[dict[str, Any]] = []
    for cluster, snapshot in zip(clusters, snapshots):
        status = snapshot.get("status") or {}
        raw_jobs = status.get("jobs", []) if isinstance(status, dict) else []
        for job in raw_jobs if isinstance(raw_jobs, list) else []:
            if not isinstance(job, dict):
                continue
            row = dict(job)
            row["cluster"] = cluster.name
            row["cluster_label"] = cluster.label or cluster.name
            row["cluster_event_id"] = f"{cluster.name}:{row.get('event')}"
            jobs.append(row)
        cluster_rows.append({"name": cluster.name, "label": cluster.label or cluster.name, "ok": bool(snapshot.get("ok")), "error": snapshot.get("error"), "project_dir": str(cluster.project_dir), "webdir": str(cluster.webdir), "job_count": len(raw_jobs) if isinstance(raw_jobs, list) else 0, "generated_at": status.get("generated_at") if isinstance(status, dict) else None})
    return {"generated_at": time.time(), "hostname": socket.gethostname(), "clusters": cluster_rows, "jobs": jobs, "snapshots": snapshots}


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
    atomic_write_text(path, json.dumps(data, indent=2, sort_keys=True, allow_nan=False) + "\n", mode=mode)


def read_token(token_file: Path | None) -> str | None:
    if token_file is None or not token_file.is_file():
        return None
    token = token_file.read_text().strip()
    return token or None


def token_valid(supplied: str | None, expected: str | None) -> bool:
    if expected is None:
        return True
    return secrets.compare_digest(str(supplied or ""), expected)


class CentralState:
    def __init__(self, clusters: list[ClusterConfig], webdir: Path, token_file: Path | None) -> None:
        self.clusters = clusters
        self.webdir = webdir.expanduser().resolve()
        self.token_file = token_file
        self.lock = threading.Lock()
        self.started_at = time.time()
        self.last_payload: dict[str, Any] = {"generated_at": time.time(), "clusters": [], "jobs": [], "snapshots": []}
        self.last_error: str | None = None

    @property
    def token(self) -> str | None:
        return read_token(self.token_file)

    def cluster_by_name(self, name: str) -> ClusterConfig:
        for cluster in self.clusters:
            if cluster.name == name:
                return cluster
        raise KeyError(f"unknown cluster {name!r}; available: {[cluster.name for cluster in self.clusters]}")


class Handler(BaseHTTPRequestHandler):
    server_version = "PurohitCentral/0.1"

    @property
    def state(self) -> CentralState:
        return self.server.state  # type: ignore[attr-defined]

    def _cors(self) -> None:
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, X-Purohit-Token")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")

    def _send_json(self, payload: dict[str, Any], status: HTTPStatus = HTTPStatus.OK) -> None:
        body = json.dumps(payload, indent=2, sort_keys=True, allow_nan=False).encode("utf-8")
        self.send_response(status)
        self._cors()
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _auth_ok(self, query: dict[str, list[str]]) -> bool:
        supplied = self.headers.get("X-Purohit-Token") or query.get("token", [None])[-1]
        return token_valid(supplied, self.state.token)

    def do_OPTIONS(self) -> None:  # noqa: N802
        self.send_response(HTTPStatus.NO_CONTENT)
        self._cors()
        self.end_headers()

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        query = parse_qs(parsed.query)
        if not self._auth_ok(query):
            self._send_json({"ok": False, "error": "unauthorized"}, HTTPStatus.UNAUTHORIZED)
            return
        if parsed.path == "/api/status":
            with self.state.lock:
                payload = dict(self.state.last_payload)
            payload["ok"] = True
            self._send_json(payload)
        elif parsed.path == "/api/health":
            self._send_json({"ok": True, "started_at": self.state.started_at, "cluster_count": len(self.state.clusters), "last_error": self.state.last_error})
        else:
            self._send_json({"ok": False, "error": "unknown endpoint"}, HTTPStatus.NOT_FOUND)

    def do_POST(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        query = parse_qs(parsed.query)
        if not self._auth_ok(query):
            self._send_json({"ok": False, "error": "unauthorized"}, HTTPStatus.UNAUTHORIZED)
            return
        try:
            length = int(self.headers.get("Content-Length") or 0)
            payload = json.loads(self.rfile.read(length).decode("utf-8") or "{}")
            if parsed.path != "/api/command":
                self._send_json({"ok": False, "error": "unknown endpoint"}, HTTPStatus.NOT_FOUND)
                return
            if not isinstance(payload, dict):
                raise ValueError("command payload must be an object")
            cluster = self.state.cluster_by_name(str(payload.get("cluster") or ""))
            action = str(payload.get("action") or "")
            event = str(payload.get("event") or "")
            if action not in {"submit_event", "hold_event", "release_event", "remove_event", "reset_event", "refresh"}:
                raise ValueError(f"unsupported action {action!r}")
            if action != "refresh" and not event:
                raise ValueError("event is required")
            command = {"id": f"central-{int(time.time() * 1000)}-{secrets.token_hex(6)}", "action": action, "event": event, "created_at": time.time(), "source": "central-manager", "cluster": cluster.name}
            remote_append_jsonl(cluster, cluster.queue_path or cluster.project_dir / "control" / QUEUE_FILENAME, command)
            self._send_json({"ok": True, "cluster": cluster.name, "command": command})
        except Exception as exc:  # noqa: BLE001
            self._send_json({"ok": False, "error": str(exc)}, HTTPStatus.BAD_REQUEST)


def publish_central_pages(webdir: Path, payload: dict[str, Any], endpoint_url: str, config_path: Path) -> None:
    webdir = webdir.expanduser().resolve()
    webdir.mkdir(parents=True, exist_ok=True)
    atomic_write_json(webdir / CENTRAL_STATUS_FILENAME, payload)
    atomic_write_json(webdir / CENTRAL_CONFIG_FILENAME, {"endpoint_url": endpoint_url, "config_path": str(config_path), "generated_at": time.time()})
    atomic_write_text(webdir / CENTRAL_HTML_FILENAME, CENTRAL_HTML)
    # Convenience index for a central-only webdir.
    atomic_write_text(webdir / "index.html", CENTRAL_HTML)


def refresh_once(state: CentralState, config_path: Path, endpoint_url: str) -> dict[str, Any]:
    snapshots = [fetch_cluster_snapshot(cluster) for cluster in state.clusters]
    payload = aggregate_snapshots(state.clusters, snapshots)
    publish_central_pages(state.webdir, payload, endpoint_url, config_path)
    with state.lock:
        state.last_payload = payload
        state.last_error = None
    return payload


def manager_loop(state: CentralState, args: argparse.Namespace, config_path: Path) -> None:
    endpoint_url = f"http://{args.host}:{args.port}"
    while True:
        try:
            payload = refresh_once(state, config_path, endpoint_url)
            print(f"Published central status for {len(payload['clusters'])} clusters / {len(payload['jobs'])} jobs to {state.webdir} at {time.strftime('%Y-%m-%d %H:%M:%S')}")
        except Exception as exc:  # noqa: BLE001
            state.last_error = str(exc)
            print(f"Central manager cycle failed: {exc}")
        if args.once:
            return
        time.sleep(args.interval)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the Purohit central multi-cluster command center.")
    parser.add_argument("--config", required=True, type=Path, help="Central cluster config YAML.")
    parser.add_argument("--webdir", required=True, type=Path, help="Central webdir to publish central.html/status JSON.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8770)
    parser.add_argument("--token-file", type=Path, default=None)
    parser.add_argument("--interval", type=int, default=30)
    parser.add_argument("--once", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.host not in {"127.0.0.1", "localhost"} and args.token_file is None:
        raise RuntimeError("Refusing to bind central manager to a non-local host without --token-file")
    clusters = load_clusters(args.config)
    state = CentralState(clusters, args.webdir, args.token_file)
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    server.state = state  # type: ignore[attr-defined]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    print(f"Central API listening on http://{args.host}:{args.port}")
    try:
        manager_loop(state, args, args.config.expanduser().resolve())
    finally:
        server.shutdown()
        thread.join(timeout=5)


if __name__ == "__main__":
    main()
