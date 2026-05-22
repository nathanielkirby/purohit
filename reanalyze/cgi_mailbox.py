"""CGI mailbox ingress for the static Purohit manager.

This module supports CIT-style deployments where the CGI execution host can
write only to local temporary storage, while the submit/login host cannot see
that temporary storage directly. Browser requests enqueue commands into a
mailbox on the CGI host. The manager on the submit host periodically drains the
mailbox over HTTPS and then executes the commands locally.
"""

from __future__ import annotations

import argparse
import cgi
import json
import os
from pathlib import Path
import secrets
import sys
import tempfile
import time
from typing import Any
from urllib.parse import parse_qs

VALID_ACTIONS = {"submit_event", "hold_event", "release_event", "remove_event", "refresh"}


def ensure_private_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    try:
        path.chmod(0o700)
    except OSError:
        pass


def atomic_write_text(path: Path, text: str, mode: int = 0o600) -> None:
    ensure_private_dir(path.parent)
    with tempfile.NamedTemporaryFile("w", dir=path.parent, delete=False) as handle:
        handle.write(text)
        tmp = Path(handle.name)
    os.replace(tmp, path)
    try:
        path.chmod(mode)
    except OSError:
        pass


def read_token(token_file: Path | None) -> str | None:
    if token_file is None or not token_file.is_file():
        return None
    token = token_file.read_text().strip()
    return token or None


def validate_token(data: dict[str, Any], token_file: Path | None) -> None:
    expected = read_token(token_file)
    if expected is None:
        return
    supplied = data.get("token") or os.environ.get("HTTP_X_PUROHIT_TOKEN") or ""
    if not secrets.compare_digest(str(supplied), expected):
        raise PermissionError("unauthorized")


def command_file(spool_dir: Path) -> Path:
    return spool_dir / "commands.jsonl"


def archive_dir(spool_dir: Path) -> Path:
    return spool_dir / "drained"


def append_command(spool_dir: Path, action: str, event: str | None = None, reason: str | None = None, source: str = "cgi-mailbox") -> dict[str, Any]:
    if action not in VALID_ACTIONS:
        raise ValueError(f"unsupported action {action!r}")
    if action != "refresh" and not event:
        raise ValueError(f"{action} requires an event")

    ensure_private_dir(spool_dir)
    command: dict[str, Any] = {
        "id": f"{int(time.time() * 1000)}-{secrets.token_hex(6)}",
        "action": action,
        "created_at": time.time(),
        "source": source,
    }
    if event:
        command["event"] = event
    if reason:
        command["reason"] = reason

    line = json.dumps(command, sort_keys=True) + "\n"
    path = command_file(spool_dir)
    with path.open("a") as handle:
        handle.write(line)
    try:
        path.chmod(0o600)
    except OSError:
        pass
    return command


def _parse_json_lines(text: str) -> list[dict[str, Any]]:
    commands: list[dict[str, Any]] = []
    for line in text.splitlines():
        if not line.strip():
            continue
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            item = {"id": f"invalid-{int(time.time() * 1000)}", "action": "invalid", "error": "invalid JSON line", "raw": line}
        if isinstance(item, dict):
            commands.append(item)
    return commands


def drain_commands(spool_dir: Path) -> list[dict[str, Any]]:
    ensure_private_dir(spool_dir)
    path = command_file(spool_dir)
    if not path.is_file():
        return []
    text = path.read_text()
    if not text.strip():
        atomic_write_text(path, "")
        return []

    commands = _parse_json_lines(text)
    archive = archive_dir(spool_dir)
    ensure_private_dir(archive)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    atomic_write_text(archive / f"commands-{stamp}-{secrets.token_hex(4)}.jsonl", text)
    atomic_write_text(path, "")
    return commands


def read_request_data() -> dict[str, Any]:
    data: dict[str, Any] = {}
    query = parse_qs(os.environ.get("QUERY_STRING", ""))
    for key, values in query.items():
        if values:
            data[key] = values[-1]

    method = os.environ.get("REQUEST_METHOD", "GET").upper()
    content_type = os.environ.get("CONTENT_TYPE", "")
    if method == "POST" and "application/json" in content_type:
        length = int(os.environ.get("CONTENT_LENGTH") or 0)
        raw = sys.stdin.read(length) if length else "{}"
        body = json.loads(raw or "{}")
        if isinstance(body, dict):
            data.update(body)
        return data

    if method == "POST":
        form = cgi.FieldStorage()
        for key in form.keys():
            data[key] = form.getfirst(key)
    return data


def json_response(payload: dict[str, Any], status: str = "200 OK") -> None:
    print(f"Status: {status}")
    print("Content-Type: application/json")
    print("Access-Control-Allow-Origin: *")
    print("Access-Control-Allow-Headers: Content-Type, X-Purohit-Token")
    print("Access-Control-Allow-Methods: GET, POST, OPTIONS")
    print()
    print(json.dumps(payload, indent=2, sort_keys=True))


def run_cgi(spool_dir: Path, token_file: Path | None = None) -> None:
    if os.environ.get("REQUEST_METHOD", "GET").upper() == "OPTIONS":
        json_response({"ok": True})
        return

    try:
        data = read_request_data()
        validate_token(data, token_file)
        mode = str(data.get("mode") or "enqueue")
        if mode == "drain":
            commands = drain_commands(spool_dir.expanduser().resolve())
            json_response({"ok": True, "mode": "drain", "count": len(commands), "commands": commands})
            return
        if mode == "status":
            path = command_file(spool_dir.expanduser().resolve())
            count = len(_parse_json_lines(path.read_text())) if path.is_file() else 0
            json_response({"ok": True, "mode": "status", "count": count})
            return

        action = str(data.get("action") or "")
        event = data.get("event")
        reason = data.get("reason")
        command = append_command(
            spool_dir.expanduser().resolve(),
            action,
            event=str(event) if event else None,
            reason=str(reason) if reason else None,
        )
        json_response({"ok": True, "queued": command})
    except PermissionError as exc:
        json_response({"ok": False, "error": str(exc)}, status="401 Unauthorized")
    except Exception as exc:  # noqa: BLE001 - CGI must return browser-readable errors
        json_response({"ok": False, "error": str(exc)}, status="400 Bad Request")


def cgi_script_text(spool_dir: Path, token_file: Path | None = None, python_executable: str = "python3", repo_root: Path | None = None) -> str:
    repo_line = ""
    if repo_root is not None:
        repo_line = f"\nimport sys\nsys.path.insert(0, {str(repo_root.expanduser().resolve())!r})\n"
    token_expr = "None" if token_file is None else f"Path({str(token_file.expanduser().resolve())!r})"
    return f'''#!/usr/bin/env {python_executable}
from pathlib import Path
{repo_line}
from reanalyze.cgi_mailbox import run_cgi

run_cgi(
    spool_dir=Path({str(spool_dir.expanduser().resolve())!r}),
    token_file={token_expr},
)
'''


def install_cgi(cgi_path: Path, spool_dir: Path, token_file: Path | None = None, python_executable: str = "python3", repo_root: Path | None = None) -> Path:
    cgi_path = cgi_path.expanduser().resolve()
    cgi_path.parent.mkdir(parents=True, exist_ok=True)
    cgi_path.write_text(cgi_script_text(spool_dir, token_file=token_file, python_executable=python_executable, repo_root=repo_root))
    cgi_path.chmod(0o755)
    return cgi_path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Install or run a Purohit CGI mailbox ingress.")
    parser.add_argument("--spool-dir", required=True, type=Path, help="Writable directory local to the CGI host, e.g. /var/tmp/purohit-vaishak-rean5")
    parser.add_argument("--cgi-path", type=Path, help="CGI script path to install")
    parser.add_argument("--token-file", type=Path, default=None)
    parser.add_argument("--python-executable", default="python3")
    parser.add_argument("--repo-root", type=Path, default=None, help="Repository root to add to sys.path in generated CGI script")
    parser.add_argument("--run-cgi", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.run_cgi:
        run_cgi(args.spool_dir, token_file=args.token_file)
        return
    if args.cgi_path is None:
        raise SystemExit("--cgi-path is required unless --run-cgi is used")
    installed = install_cgi(
        args.cgi_path,
        args.spool_dir,
        token_file=args.token_file,
        python_executable=args.python_executable,
        repo_root=args.repo_root,
    )
    print(f"Installed CGI mailbox ingress at {installed}")


if __name__ == "__main__":
    main()
