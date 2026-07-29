"""
rbxbcd – UNC Bridge and Script Queue HTTP server.

Provides the bridge between the injected Luau runtime and the Python host:
  - File I/O (readfile, writefile, listfiles, delfile, etc.)
  - Script execution queue (GET /send?c=gs  ↔  POST /execute)
  - System identity (clt, hw)

All paths are confined to the workspace/ directory with Path Traversal protection.
"""

from flask import Flask, request, jsonify
import os
import shutil
import threading
from pathlib import Path

app = Flask(__name__)

# ─────────────────────────────────────────────────────────────
# Configuration
# ─────────────────────────────────────────────────────────────
BASE_DIR: str = os.path.dirname(os.path.abspath(__file__))
WORKSPACE_DIR: str = os.path.join(BASE_DIR, "workspace")

_ensure = Path(WORKSPACE_DIR)
_ensure.mkdir(parents=True, exist_ok=True)

# Thread-safe script queue
_queue_lock = threading.Lock()
script_queue: list[str] = []

# ─────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────
def _safe_path(relative: str) -> str:
    """Resolve a workspace-relative path, blocking traversal escapes."""
    resolved = os.path.normpath(os.path.join(WORKSPACE_DIR, relative))
    norm_workspace = os.path.normpath(WORKSPACE_DIR)
    if not os.path.commonpath([resolved, norm_workspace]) == norm_workspace:
        raise ValueError("Path traversal attempt")
    return resolved


def _queue_push(script: str) -> int:
    with _queue_lock:
        script_queue.append(script)
        return len(script_queue)


def _queue_pop() -> str:
    with _queue_lock:
        return script_queue.pop(0) if script_queue else ""


# ─────────────────────────────────────────────────────────────
# Bridge endpoints
# ─────────────────────────────────────────────────────────────
@app.route("/send", methods=["POST"])
def handle_bridge():
    """Main bridge endpoint consumed by the Luau runtime."""
    data = request.get_json(force=True, silent=True) or {}
    command: str = data.get("c", "").strip().lower()

    # ── System identity ──
    if command == "clt":
        return "SYNTAX-v1", 200

    if command == "hw":
        return "SN-SYNTAX-PY", 200

    # ── File read ──
    if command == "rf":
        try:
            path = _safe_path(data.get("p", ""))
            file = Path(path)
            if file.is_file():
                return file.read_text(encoding="utf-8"), 200
            return "File not found", 404
        except ValueError:
            return "Forbidden", 403

    # ── File write (string body) ──
    if command == "wf":
        try:
            path = _safe_path(data.get("p", ""))
            content = data.get("v", "")
            Path(path).write_text(content, encoding="utf-8")
            return "Success", 200
        except ValueError:
            return "Forbidden", 403
        except OSError:
            return "Write failed", 500

    # ── Directory listing ──
    if command == "lf":
        try:
            path = _safe_path(data.get("p", ""))
            p = Path(path)
            if p.is_dir():
                entries = [
                    {"name": e.name, "type": "dir" if e.is_dir() else "file"}
                    for e in p.iterdir()
                ]
                return jsonify(entries), 200
            return jsonify([]), 200
        except ValueError:
            return "Forbidden", 403

    # ── Delete file / folder ──
    if command == "df":
        try:
            path = _safe_path(data.get("p", ""))
            p = Path(path)
            if p.is_dir():
                shutil.rmtree(p)
            elif p.is_file():
                p.unlink()
            return "Success", 200
        except ValueError:
            return "Forbidden", 403
        except OSError:
            return "Not found", 404

    # ── Append to file ──
    if command == "af":
        try:
            path = _safe_path(data.get("p", ""))
            content = data.get("v", "")
            with Path(path).open("a", encoding="utf-8") as f:
                f.write(content)
            return "Success", 200
        except ValueError:
            return "Forbidden", 403

    # ── Get script from queue ──
    if command == "gs":
        script = _queue_pop()
        if script:
            return script, 200
        return "", 204

    # ── Check if file exists ──
    if command == "fe":
        try:
            path = _safe_path(data.get("p", ""))
            return jsonify(Path(path).exists()), 200
        except ValueError:
            return "Forbidden", 403

    return "OK", 200


@app.route("/writefile", methods=["POST"])
def handle_writefile():
    """Binary write endpoint. Path via query param `p`, body is raw content."""
    file_name = request.args.get("p", "")
    if not file_name:
        return "Invalid path", 400
    try:
        safe_path = _safe_path(file_name)
    except ValueError:
        return "Forbidden", 403

    content = request.data
    Path(safe_path).write_bytes(content)
    return "Success", 200


@app.route("/execute", methods=["POST"])
def handle_execute():
    """Enqueue a Lua script for the injected runtime to pick up."""
    script_source = request.data.decode("utf-8", errors="replace").strip()
    if not script_source:
        return "Empty script", 400
    size = _queue_push(script_source)
    print(f"[QUEUE] Script enqueued (queue size: {size})")
    return "Queued", 200


@app.route("/queue/count", methods=["GET"])
def handle_queue_count():
    """Return the current queue length."""
    with _queue_lock:
        return jsonify({"count": len(script_queue)}), 200


@app.route("/queue/clear", methods=["POST"])
def handle_queue_clear():
    """Clear all pending scripts from the queue."""
    with _queue_lock:
        cleared = len(script_queue)
        script_queue.clear()
    print(f"[QUEUE] Cleared {cleared} pending scripts")
    return f"Cleared {cleared}", 200


# ─────────────────────────────────────────────────────────────
# Entry point
# ─────────────────────────────────────────────────────────────
if __name__ == "__main__":
    print(f"[*] Syntax Bridge active – workspace: {WORKSPACE_DIR}")
    app.run(host="127.0.0.1", port=19283, threaded=True)
