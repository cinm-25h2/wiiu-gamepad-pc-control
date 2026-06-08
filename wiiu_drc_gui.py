#!/usr/bin/env python3
"""Small dependency-free web control panel for a Wii U GamePad/libdrc setup."""

from __future__ import annotations

import argparse
import html
import json
import os
import re
import secrets
import signal
import subprocess
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse


BASE = Path(os.environ.get("WIIU_DRC_BASE", "/root/wiiu-drc"))
LOG_DIR = BASE / "gui-logs"
TOKEN_FILE = BASE / "gui-token"
MAX_LOG_LINES = 500


def ensure_token() -> str:
    if "WIIU_GUI_TOKEN" in os.environ:
        return os.environ["WIIU_GUI_TOKEN"]
    if TOKEN_FILE.exists():
        token = TOKEN_FILE.read_text().strip()
        if token:
            return token
    token = secrets.token_urlsafe(18)
    TOKEN_FILE.parent.mkdir(parents=True, exist_ok=True)
    TOKEN_FILE.write_text(token + "\n")
    TOKEN_FILE.chmod(0o600)
    return token


TOKEN = ensure_token()


SECRET_PATTERNS = [
    re.compile(r"(?i)(token=)[^&\s'\"<>]+"),
    re.compile(r"(?i)((?:GH_TOKEN|GITHUB_TOKEN|WIIU_GUI_TOKEN|PASSWORD|PASS|PSK|WPA_PSK|NORMAL_PSK|psk|wpa_psk)\s*[=:]\s*)[^&\s'\"<>]+"),
    re.compile(r"(?i)(Authorization:\s*Bearer\s+)[A-Za-z0-9._~+/=-]+"),
]


def mask_text(text: str) -> str:
    masked = text
    for pattern in SECRET_PATTERNS:
        masked = pattern.sub(r"\1<redacted>", masked)
    return masked


@dataclass
class Task:
    ident: str
    title: str
    command: str
    started_at: float = field(default_factory=time.time)
    finished_at: float | None = None
    returncode: int | None = None
    lines: deque[str] = field(default_factory=lambda: deque(maxlen=MAX_LOG_LINES))
    log_path: Path | None = None

    @property
    def running(self) -> bool:
        return self.finished_at is None

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.ident,
            "title": self.title,
            "command": mask_text(self.command),
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "returncode": self.returncode,
            "running": self.running,
            "lines": [mask_text(line) for line in list(self.lines)[-160:]],
            "log_path": str(self.log_path) if self.log_path else None,
        }


TASKS: dict[str, Task] = {}
TASK_LOCK = threading.Lock()


def shell(command: str, timeout: int = 5) -> tuple[int, str]:
    try:
        proc = subprocess.run(
            ["bash", "-lc", command],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=timeout,
            text=True,
        )
        return proc.returncode, proc.stdout
    except subprocess.TimeoutExpired as exc:
        return 124, (exc.stdout or "") + "\nTIMEOUT\n"


def script(name: str) -> str:
    return str(BASE / name)


def start_task(title: str, command: str, env: dict[str, str] | None = None) -> Task:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    ident = f"{int(time.time())}-{secrets.token_hex(3)}"
    task = Task(ident=ident, title=title, command=command)
    task.log_path = LOG_DIR / f"{ident}.log"

    with TASK_LOCK:
        TASKS[ident] = task

    def runner() -> None:
        merged_env = os.environ.copy()
        if env:
            merged_env.update(env)
        with task.log_path.open("w", encoding="utf-8", errors="replace") as log:
            log.write(f"$ {mask_text(command)}\n\n")
            log.flush()
            proc = subprocess.Popen(
                ["bash", "-lc", command],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                env=merged_env,
                bufsize=1,
            )
            assert proc.stdout is not None
            for line in proc.stdout:
                line = mask_text(line.rstrip("\n"))
                task.lines.append(line)
                log.write(line + "\n")
                log.flush()
            task.returncode = proc.wait()
            task.finished_at = time.time()
            done = f"\n[exit {task.returncode}]"
            task.lines.append(done)
            log.write(done + "\n")

    threading.Thread(target=runner, daemon=True).start()
    return task


def exact_watchdog_pids() -> list[str]:
    code, out = shell(
        "ps -eo pid=,args= | awk '$2 == \"bash\" && $3 == \"/root/wiiu-drc/watch_drcvnc_success.sh\" { print $1 }'",
        timeout=3,
    )
    if code != 0:
        return []
    return [line.strip() for line in out.splitlines() if line.strip()]


def read_status() -> dict[str, Any]:
    _, status_text = shell(f"{script('wiiu_gamepad_status.sh')} | sed -n '1,140p'", timeout=7)
    _, hostapd = shell("pgrep -a hostapd || true", timeout=3)
    _, stream = shell("pgrep -a drcvncclient || true", timeout=3)
    _, vnc = shell("pgrep -a Xtigervnc || true", timeout=3)
    _, station = shell(
        "iw dev ap0 station dump 2>/dev/null | awk '/^Station / { print $2; exit }'",
        timeout=3,
    )
    _, last_offset = shell(f"cat {BASE}/last_tsf_offset.conf 2>/dev/null || true", timeout=3)
    pids = exact_watchdog_pids()
    return {
        "ap": bool(hostapd.strip()),
        "stream": bool(stream.strip()),
        "vnc": bool(vnc.strip()),
        "watchdog": bool(pids),
        "watchdog_pids": pids,
        "station": station.strip(),
        "last_tsf_offset": last_offset.strip(),
        "hostapd": hostapd.strip(),
        "stream_process": stream.strip(),
        "status_text": mask_text(status_text),
        "time": time.time(),
    }


def action_command(action: str, payload: dict[str, Any]) -> tuple[str, str, dict[str, str] | None]:
    if action == "ap_on":
        return "AP ON", f"CHANNEL=${{CHANNEL:-48}} {script('restart_wiiu_ap_keepalive.sh')}", None
    if action == "ap_off":
        cmd = (
            "killall -9 drcvncclient pad_probe hostapd dnsmasq 2>/dev/null || true; "
            "vncserver -kill :1 >/dev/null 2>&1 || true; "
            "ip link set ap0 down 2>/dev/null || true; "
            "echo AP_AND_STREAM_OFF"
        )
        return "AP OFF", cmd, None
    if action == "desktop_on":
        return (
            "Desktop Stream ON",
            f"START_DESKTOP=1 START_XEV=0 OPEN_FILE_MANAGER=0 {script('start_drcvnc_success.sh')}",
            None,
        )
    if action == "touch_debug_on":
        return (
            "Desktop Stream ON with Touch Debug",
            f"DRC_TOUCH_DEBUG=1 START_DESKTOP=1 START_XEV=0 OPEN_FILE_MANAGER=0 {script('start_drcvnc_success.sh')}",
            None,
        )
    if action == "screen_test":
        return "libdrc Screen Test", f"{script('run_wiiu_gamepad_screen_success.sh')}", None
    if action == "stream_off":
        cmd = (
            "killall -9 drcvncclient pad_probe 2>/dev/null || true; "
            "vncserver -kill :1 >/dev/null 2>&1 || true; "
            "echo STREAM_OFF"
        )
        return "Stream OFF", cmd, None
    if action == "pair_switch":
        return "Pair/Switch Already-Paired GamePad", f"{script('pair_or_switch_wiiu_gamepad.sh')}", None
    if action == "direct_pair":
        wps4 = str(payload.get("wps4", "0000")).strip()
        if len(wps4) != 4 or any(ch not in "0123" for ch in wps4):
            raise ValueError("wps4 must be four digits using only 0,1,2,3")
        return (
            "Experimental PC Direct Pair",
            f"WPS4={wps4} {script('pair_gamepad_pc_wps_experimental.sh')}",
            None,
        )
    if action == "watchdog_on":
        return "Watchdog ON", f"{script('normalize_watchdog.sh')}", None
    if action == "watchdog_off":
        cmd = (
            "if [ -s /root/wiiu-drc/watch_drcvnc.pid ]; then "
            "kill $(cat /root/wiiu-drc/watch_drcvnc.pid) 2>/dev/null || true; fi; "
            "ps -eo pid=,args= | awk '$2 == \"bash\" && $3 == \"/root/wiiu-drc/watch_drcvnc_success.sh\" { print $1 }' "
            "| xargs -r kill 2>/dev/null || true; "
            "rm -f /root/wiiu-drc/watch_drcvnc.pid; echo WATCHDOG_OFF"
        )
        return "Watchdog OFF", cmd, None
    raise ValueError(f"unknown action: {action}")


INDEX_HTML = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Wii U GamePad PC Control</title>
<style>
:root {
  color-scheme: dark;
  --bg: #101418;
  --panel: #171d22;
  --panel2: #20272d;
  --text: #e8eef2;
  --muted: #9daab3;
  --line: #34404a;
  --ok: #43c476;
  --bad: #e45f5f;
  --warn: #e6b84c;
  --accent: #58a6ff;
}
* { box-sizing: border-box; }
body {
  margin: 0;
  min-height: 100vh;
  background: var(--bg);
  color: var(--text);
  font: 14px/1.45 system-ui, -apple-system, Segoe UI, sans-serif;
}
header {
  height: 54px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 18px;
  border-bottom: 1px solid var(--line);
  background: #111820;
}
h1 { margin: 0; font-size: 17px; font-weight: 650; letter-spacing: 0; }
main {
  display: grid;
  grid-template-columns: minmax(260px, 380px) minmax(360px, 1fr);
  gap: 14px;
  padding: 14px;
}
section {
  background: var(--panel);
  border: 1px solid var(--line);
  border-radius: 8px;
}
.section-head {
  height: 42px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 12px;
  border-bottom: 1px solid var(--line);
  color: var(--muted);
  font-weight: 600;
}
.body { padding: 12px; }
.pills {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 8px;
}
.pill {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  min-height: 40px;
  padding: 8px 10px;
  border: 1px solid var(--line);
  border-radius: 6px;
  background: var(--panel2);
}
.dot {
  width: 9px;
  height: 9px;
  border-radius: 50%;
  background: var(--bad);
  flex: 0 0 auto;
}
.dot.on { background: var(--ok); }
.muted { color: var(--muted); }
.station { margin-top: 10px; word-break: break-all; color: var(--muted); }
.grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 8px; }
button, input {
  min-height: 38px;
  border: 1px solid var(--line);
  border-radius: 6px;
  background: var(--panel2);
  color: var(--text);
  font: inherit;
}
button {
  cursor: pointer;
  padding: 0 10px;
  text-align: left;
}
button:hover { border-color: var(--accent); }
button.primary { background: #16395d; border-color: #266aa6; }
button.danger { background: #4a2020; border-color: #794040; }
button.warn { background: #473718; border-color: #80642b; }
input { width: 100%; padding: 0 10px; }
.pair-row { display: grid; grid-template-columns: 88px 1fr; gap: 8px; margin-top: 8px; }
.symbols { margin-top: 8px; color: var(--muted); min-height: 20px; }
pre {
  margin: 0;
  min-height: 240px;
  max-height: calc(100vh - 200px);
  overflow: auto;
  white-space: pre-wrap;
  word-break: break-word;
  padding: 12px;
  color: #d8e3ea;
  background: #0b0f13;
  border-radius: 0 0 8px 8px;
}
.task {
  border-top: 1px solid var(--line);
  padding: 10px 12px;
}
.task:first-child { border-top: 0; }
.task-title { display: flex; justify-content: space-between; gap: 10px; }
.task code { color: var(--muted); font-size: 12px; word-break: break-all; }
@media (max-width: 820px) {
  main { grid-template-columns: 1fr; }
}
</style>
</head>
<body>
<header>
  <h1>Wii U GamePad PC Control</h1>
  <div class="muted" id="clock"></div>
</header>
<main>
  <div>
    <section>
      <div class="section-head">Status <button onclick="refresh()">Refresh</button></div>
      <div class="body">
        <div class="pills">
          <div class="pill"><span>AP</span><span><i id="apdot" class="dot"></i></span></div>
          <div class="pill"><span>Stream</span><span><i id="streamdot" class="dot"></i></span></div>
          <div class="pill"><span>VNC</span><span><i id="vncdot" class="dot"></i></span></div>
          <div class="pill"><span>Watchdog</span><span><i id="watchdogdot" class="dot"></i></span></div>
        </div>
        <div class="station" id="station"></div>
      </div>
    </section>

    <section style="margin-top:14px">
      <div class="section-head">Controls</div>
      <div class="body">
        <div class="grid">
          <button class="primary" onclick="act('desktop_on')">Stream Desktop ON</button>
          <button onclick="act('screen_test')">Run Screen Test</button>
          <button onclick="act('ap_on')">AP ON</button>
          <button class="danger" onclick="act('stream_off')">Stream OFF</button>
          <button onclick="act('pair_switch')">Switch GamePad</button>
          <button onclick="act('watchdog_on')">Watchdog ON</button>
          <button onclick="act('touch_debug_on')">Touch Debug ON</button>
          <button class="danger" onclick="act('watchdog_off')">Watchdog OFF</button>
          <button class="danger" onclick="act('ap_off')">All OFF</button>
        </div>
        <div class="pair-row">
          <input id="wps4" value="0000" maxlength="4" pattern="[0-3]{4}">
          <button class="warn" onclick="directPair()">Experimental Direct Pair</button>
        </div>
        <div class="symbols" id="symbols"></div>
      </div>
    </section>

    <section style="margin-top:14px">
      <div class="section-head">Recent Tasks</div>
      <div id="tasks"></div>
    </section>
  </div>

  <section>
    <div class="section-head">Live Status Log</div>
    <pre id="log"></pre>
  </section>
</main>
<script>
const TOKEN = "__TOKEN__";
const symbols = {0: "&spades;", 1: "&hearts;", 2: "&diams;", 3: "&clubs;"};

function dot(id, on) {
  document.getElementById(id).className = on ? "dot on" : "dot";
}

function showSymbols() {
  const wps = document.getElementById("wps4").value || "";
  const ok = /^[0-3]{4}$/.test(wps);
  document.getElementById("symbols").innerHTML = ok
    ? "Enter on GamePad: " + wps.split("").map(x => symbols[x]).join(" ") + " &nbsp; PIN: " + wps + "5678"
    : "Use four digits from 0 to 3.";
}

async function refresh() {
  const res = await fetch("/api/status?token=" + encodeURIComponent(TOKEN));
  const data = await res.json();
  dot("apdot", data.ap);
  dot("streamdot", data.stream);
  dot("vncdot", data.vnc);
  dot("watchdogdot", data.watchdog);
  document.getElementById("station").textContent =
    "GamePad: " + (data.station || "not associated") +
    (data.last_tsf_offset ? " | TSF offset: " + data.last_tsf_offset : "");
  document.getElementById("log").textContent = data.status_text || "";
  document.getElementById("clock").textContent = new Date().toLocaleTimeString();
  renderTasks();
}

async function act(action, payload = {}) {
  const res = await fetch("/api/action?token=" + encodeURIComponent(TOKEN), {
    method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify({action, ...payload})
  });
  const data = await res.json();
  if (!res.ok) alert(data.error || "Action failed");
  await refresh();
}

function directPair() {
  const wps4 = document.getElementById("wps4").value;
  act("direct_pair", {wps4});
}

async function renderTasks() {
  const res = await fetch("/api/tasks?token=" + encodeURIComponent(TOKEN));
  const data = await res.json();
  const root = document.getElementById("tasks");
  root.innerHTML = "";
  for (const task of data.tasks.slice(-6).reverse()) {
    const el = document.createElement("div");
    el.className = "task";
    el.innerHTML =
      `<div class="task-title"><strong>${task.title}</strong><span class="muted">${task.running ? "running" : "exit " + task.returncode}</span></div>` +
      `<code>${task.command}</code>` +
      `<pre style="min-height:0;max-height:160px;margin-top:8px;border-radius:6px">${task.lines.join("\\n")}</pre>`;
    root.appendChild(el);
  }
}

document.getElementById("wps4").addEventListener("input", showSymbols);
showSymbols();
refresh();
setInterval(refresh, 3000);
</script>
</body>
</html>
"""


class Handler(BaseHTTPRequestHandler):
    server_version = "WiiUDRCGui/0.1"

    def log_message(self, fmt: str, *args: Any) -> None:
        print(f"{self.address_string()} - {mask_text(fmt % args)}")

    def authorized(self) -> bool:
        query = parse_qs(urlparse(self.path).query)
        token = query.get("token", [""])[0]
        return token == TOKEN

    def send_json(self, data: Any, status: HTTPStatus = HTTPStatus.OK) -> None:
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def require_auth(self) -> bool:
        if self.authorized():
            return True
        self.send_json({"error": "bad token"}, HTTPStatus.FORBIDDEN)
        return False

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/":
            if not self.authorized():
                body = (
                    "<!doctype html><meta charset='utf-8'>"
                    "<title>Wii U GamePad PC Control</title>"
                    "<body style='font-family:system-ui;background:#101418;color:#e8eef2'>"
                    "<h1>Token Required</h1>"
                    "<p>Open this page with the token stored on the Ubuntu host.</p>"
                    "<p>The token value is intentionally not printed by the service.</p>"
                    "</body>"
                ).encode("utf-8")
                self.send_response(HTTPStatus.FORBIDDEN)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            query = parse_qs(urlparse(self.path).query)
            request_token = query.get("token", [""])[0]
            body = INDEX_HTML.replace("__TOKEN__", html.escape(request_token)).encode("utf-8")
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if parsed.path == "/api/status":
            if not self.require_auth():
                return
            self.send_json(read_status())
            return
        if parsed.path == "/api/tasks":
            if not self.require_auth():
                return
            with TASK_LOCK:
                tasks = [task.as_dict() for task in TASKS.values()]
            self.send_json({"tasks": tasks})
            return
        self.send_error(HTTPStatus.NOT_FOUND)

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path != "/api/action":
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        if not self.require_auth():
            return
        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length) if length else b"{}"
        try:
            payload = json.loads(raw.decode("utf-8"))
            action = str(payload.get("action", ""))
            title, command, env = action_command(action, payload)
            task = start_task(title, command, env)
            self.send_json({"ok": True, "task": task.as_dict()})
        except Exception as exc:
            self.send_json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default=os.environ.get("WIIU_GUI_HOST", "0.0.0.0"))
    parser.add_argument("--port", type=int, default=int(os.environ.get("WIIU_GUI_PORT", "8765")))
    args = parser.parse_args()

    httpd = ThreadingHTTPServer((args.host, args.port), Handler)

    def stop(_signum: int, _frame: Any) -> None:
        threading.Thread(target=httpd.shutdown, daemon=True).start()

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    print(f"Listening on http://{args.host}:{args.port}/", flush=True)
    print(f"Token file: {TOKEN_FILE} (value not printed)", flush=True)
    httpd.serve_forever()


if __name__ == "__main__":
    main()
