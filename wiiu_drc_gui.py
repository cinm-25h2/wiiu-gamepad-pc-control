#!/usr/bin/env python3
"""Small dependency-free web control panel for a Wii U GamePad/libdrc setup."""

from __future__ import annotations

import argparse
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
from http import cookies
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
COOKIE_NAME = "wiiu_drc_gui"


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
        "timeout 3 iw dev ap0 station dump 2>/dev/null | awk '/^Station / { print $2; exit }'",
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
            (
                f"PAD_DETECT_TIMEOUT=${{PAD_DETECT_TIMEOUT:-120}} {script('run_wiiu_gamepad_screen_success.sh')} && "
                f"START_DESKTOP=1 START_XEV=0 OPEN_FILE_MANAGER=0 {script('start_drcvnc_success.sh')}"
            ),
            None,
        )
    if action == "touch_debug_on":
        return (
            "Desktop Stream ON with Touch Debug",
            (
                f"PAD_DETECT_TIMEOUT=${{PAD_DETECT_TIMEOUT:-120}} {script('run_wiiu_gamepad_screen_success.sh')} && "
                f"DRC_TOUCH_DEBUG=1 START_DESKTOP=1 START_XEV=0 OPEN_FILE_MANAGER=0 {script('start_drcvnc_success.sh')}"
            ),
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
  --bg: #0f1317;
  --panel: #171d22;
  --panel2: #20272d;
  --panel3: #12181d;
  --text: #e8eef2;
  --muted: #9daab3;
  --line: #34404a;
  --ok: #43c476;
  --bad: #e45f5f;
  --warn: #e6b84c;
  --accent: #58a6ff;
  --accent2: #8ec5ff;
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
  min-height: 60px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 14px;
  padding: 10px 18px;
  border-bottom: 1px solid var(--line);
  background: #111820;
}
h1 { margin: 0; font-size: 18px; font-weight: 700; letter-spacing: 0; }
.subtitle { margin-top: 2px; color: var(--muted); font-size: 12px; }
main {
  display: grid;
  grid-template-columns: minmax(320px, 440px) minmax(420px, 1fr);
  gap: 14px;
  padding: 14px;
}
section {
  background: var(--panel);
  border: 1px solid var(--line);
  border-radius: 8px;
}
.section-head {
  min-height: 42px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  padding: 0 12px;
  border-bottom: 1px solid var(--line);
  color: var(--muted);
  font-weight: 600;
}
.body { padding: 12px; }
.hero-state {
  display: grid;
  grid-template-columns: 1fr auto;
  gap: 10px;
  align-items: center;
  min-height: 78px;
  padding: 14px;
  border: 1px solid var(--line);
  border-radius: 8px;
  background: var(--panel3);
}
.hero-title { font-size: 20px; font-weight: 760; }
.hero-detail { margin-top: 4px; color: var(--muted); word-break: break-all; }
.status-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 8px;
  margin-top: 10px;
}
.status-card {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  min-height: 58px;
  padding: 10px;
  border: 1px solid var(--line);
  border-radius: 6px;
  background: var(--panel2);
}
.status-name { color: var(--muted); font-size: 12px; }
.status-value { margin-top: 2px; font-weight: 700; }
.dot {
  width: 11px;
  height: 11px;
  border-radius: 50%;
  background: var(--bad);
  flex: 0 0 auto;
}
.dot.on { background: var(--ok); box-shadow: 0 0 0 3px rgba(67,196,118,.12); }
.dot.warn { background: var(--warn); box-shadow: 0 0 0 3px rgba(230,184,76,.12); }
.muted { color: var(--muted); }
.action-group { margin-top: 12px; }
.action-group:first-child { margin-top: 0; }
.group-title {
  margin: 0 0 8px;
  color: var(--muted);
  font-size: 12px;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: .06em;
}
.actions { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 8px; }
button, input {
  min-height: 40px;
  border: 1px solid var(--line);
  border-radius: 6px;
  background: var(--panel2);
  color: var(--text);
  font: inherit;
}
button {
  cursor: pointer;
  padding: 9px 10px;
  text-align: left;
  display: flex;
  flex-direction: column;
  justify-content: center;
  gap: 2px;
}
button:hover { border-color: var(--accent); }
button.primary { background: #16395d; border-color: #266aa6; }
button.danger { background: #4a2020; border-color: #794040; }
button.warn { background: #473718; border-color: #80642b; }
button.ghost {
  min-height: 32px;
  padding: 5px 9px;
  display: inline-flex;
  flex-direction: row;
  align-items: center;
}
.button-title { font-weight: 700; }
.button-detail { color: var(--muted); font-size: 12px; }
input { width: 100%; padding: 0 10px; }
.pair-row { display: grid; grid-template-columns: 90px 1fr; gap: 8px; margin-top: 8px; }
.symbols { margin-top: 8px; color: var(--accent2); min-height: 20px; font-weight: 700; }
details {
  border: 1px solid var(--line);
  border-radius: 6px;
  background: var(--panel2);
  padding: 8px 10px;
}
summary { cursor: pointer; font-weight: 700; color: var(--warn); }
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
  font: 12px/1.45 ui-monospace, SFMono-Regular, Consolas, monospace;
}
.task {
  border-top: 1px solid var(--line);
  padding: 10px 12px;
}
.task:first-child { border-top: 0; }
.task-title { display: flex; justify-content: space-between; gap: 10px; }
.task code { color: var(--muted); font-size: 12px; word-break: break-all; }
.task pre {
  min-height: 0;
  max-height: 150px;
  margin-top: 8px;
  border: 1px solid var(--line);
  border-radius: 6px;
}
.empty {
  color: var(--muted);
  padding: 12px;
}
@media (max-width: 820px) {
  main { grid-template-columns: 1fr; }
  .actions { grid-template-columns: 1fr; }
}
</style>
</head>
<body>
<header>
  <div>
    <h1>Wii U GamePad PC Control</h1>
    <div class="subtitle" id="subtitle">Checking...</div>
  </div>
  <button class="ghost" onclick="refresh()">Refresh</button>
</header>
<main>
  <div>
    <section>
      <div class="section-head">Overview <span id="clock"></span></div>
      <div class="body">
        <div class="hero-state">
          <div>
            <div class="hero-title" id="overall">Checking</div>
            <div class="hero-detail" id="station">GamePad: checking</div>
          </div>
          <i id="overalldot" class="dot"></i>
        </div>
        <div class="status-grid">
          <div class="status-card"><div><div class="status-name">AP</div><div class="status-value" id="aptext">Unknown</div></div><i id="apdot" class="dot"></i></div>
          <div class="status-card"><div><div class="status-name">Desktop Stream</div><div class="status-value" id="streamtext">Unknown</div></div><i id="streamdot" class="dot"></i></div>
          <div class="status-card"><div><div class="status-name">VNC Server</div><div class="status-value" id="vnctext">Unknown</div></div><i id="vncdot" class="dot"></i></div>
          <div class="status-card"><div><div class="status-name">Watchdog</div><div class="status-value" id="watchdogtext">Unknown</div></div><i id="watchdogdot" class="dot"></i></div>
        </div>
      </div>
    </section>

    <section style="margin-top:14px">
      <div class="section-head">Actions</div>
      <div class="body">
        <div class="action-group">
          <h2 class="group-title">Daily</h2>
          <div class="actions">
            <button class="primary" onclick="act('desktop_on')"><span class="button-title">Start Desktop</span><span class="button-detail">Reconnect + display</span></button>
            <button class="danger" onclick="act('stream_off')"><span class="button-title">Stop Stream</span><span class="button-detail">Keep AP running</span></button>
            <button onclick="act('ap_on')"><span class="button-title">Restart AP</span><span class="button-detail">Reconnect GamePad</span></button>
            <button class="danger" onclick="confirmAct('ap_off')"><span class="button-title">Power Off</span><span class="button-detail">Stop AP and stream</span></button>
          </div>
        </div>

        <div class="action-group">
          <h2 class="group-title">Keep Alive</h2>
          <div class="actions">
            <button onclick="act('watchdog_on')"><span class="button-title">Watchdog On</span><span class="button-detail">Auto-restart stream</span></button>
            <button class="danger" onclick="act('watchdog_off')"><span class="button-title">Watchdog Off</span><span class="button-detail">Manual control</span></button>
          </div>
        </div>

        <div class="action-group">
          <h2 class="group-title">Diagnostics</h2>
          <div class="actions">
            <button onclick="act('screen_test')"><span class="button-title">Screen Test</span><span class="button-detail">libdrc pad_probe</span></button>
            <button onclick="act('touch_debug_on')"><span class="button-title">Touch Debug</span><span class="button-detail">Coordinate logs</span></button>
          </div>
        </div>

        <div class="action-group">
          <h2 class="group-title">Pairing</h2>
          <div class="actions">
            <button onclick="act('pair_switch')"><span class="button-title">Switch GamePad</span><span class="button-detail">Already paired</span></button>
          </div>
          <details style="margin-top:8px">
            <summary>Experimental Direct Pair</summary>
            <div class="pair-row">
              <input id="wps4" value="0000" maxlength="4" pattern="[0-3]{4}">
              <button class="warn" onclick="confirmDirectPair()"><span class="button-title">Start Pairing AP</span><span class="button-detail">Interrupts current AP</span></button>
            </div>
            <div class="symbols" id="symbols"></div>
          </details>
        </div>
      </div>
    </section>

    <section style="margin-top:14px">
      <div class="section-head">Recent Tasks</div>
      <div id="tasks"></div>
    </section>
  </div>

  <section>
    <div class="section-head">Status Log <span class="muted">read only</span></div>
    <pre id="log"></pre>
  </section>
</main>
<script>
const symbols = {0: "&spades;", 1: "&hearts;", 2: "&diams;", 3: "&clubs;"};

function setDot(id, state) {
  const el = document.getElementById(id);
  el.className = state === "on" ? "dot on" : state === "warn" ? "dot warn" : "dot";
}

function setStatus(id, on) {
  document.getElementById(id + "text").textContent = on ? "On" : "Off";
  setDot(id + "dot", on ? "on" : "off");
}

function showSymbols() {
  const wps = document.getElementById("wps4").value || "";
  const ok = /^[0-3]{4}$/.test(wps);
  document.getElementById("symbols").innerHTML = ok
    ? "Enter on GamePad: " + wps.split("").map(x => symbols[x]).join(" ") + " &nbsp; PIN: " + wps + "5678"
    : "Use four digits from 0 to 3.";
}

async function refresh() {
  const res = await fetch("/api/status");
  if (!res.ok) {
    document.getElementById("overall").textContent = "Locked";
    document.getElementById("subtitle").textContent = "Token required";
    setDot("overalldot", "off");
    return;
  }
  const data = await res.json();
  setStatus("ap", data.ap);
  setStatus("stream", data.stream);
  setStatus("vnc", data.vnc);
  setStatus("watchdog", data.watchdog);
  const ready = data.ap && data.stream && data.vnc && data.station;
  const partial = data.ap || data.stream || data.vnc;
  document.getElementById("overall").textContent = ready ? "Ready" : partial ? "Partial" : "Offline";
  setDot("overalldot", ready ? "on" : partial ? "warn" : "off");
  document.getElementById("station").textContent =
    "GamePad: " + (data.station || "not associated") +
    (data.last_tsf_offset ? " | TSF offset: " + data.last_tsf_offset : "");
  document.getElementById("log").textContent = data.status_text || "";
  document.getElementById("clock").textContent = new Date().toLocaleTimeString();
  document.getElementById("subtitle").textContent = data.station ? "GamePad associated" : "Waiting for GamePad";
  renderTasks();
}

async function act(action, payload = {}) {
  const res = await fetch("/api/action", {
    method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify({action, ...payload})
  });
  const data = await res.json();
  if (!res.ok) alert(data.error || "Action failed");
  await refresh();
}

function confirmAct(action) {
  if (confirm("Stop the current AP and stream?")) act(action);
}

function confirmDirectPair() {
  if (!confirm("Start experimental pairing? This stops the current AP and stream.")) return;
  const wps4 = document.getElementById("wps4").value;
  act("direct_pair", {wps4});
}

async function renderTasks() {
  const res = await fetch("/api/tasks");
  if (!res.ok) return;
  const data = await res.json();
  const root = document.getElementById("tasks");
  root.innerHTML = "";
  if (!data.tasks.length) {
    root.innerHTML = '<div class="empty">No recent tasks</div>';
    return;
  }
  for (const task of data.tasks.slice(-6).reverse()) {
    const el = document.createElement("div");
    el.className = "task";
    el.innerHTML =
      `<div class="task-title"><strong>${task.title}</strong><span class="muted">${task.running ? "running" : "exit " + task.returncode}</span></div>` +
      `<code>${task.command}</code>` +
      `<pre>${task.lines.join("\\n")}</pre>`;
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

    def request_token(self) -> str:
        query = parse_qs(urlparse(self.path).query)
        return query.get("token", [""])[0]

    def cookie_token(self) -> str:
        raw = self.headers.get("Cookie", "")
        if not raw:
            return ""
        jar = cookies.SimpleCookie()
        try:
            jar.load(raw)
        except cookies.CookieError:
            return ""
        morsel = jar.get(COOKIE_NAME)
        return morsel.value if morsel else ""

    @staticmethod
    def token_matches(value: str) -> bool:
        return bool(value) and secrets.compare_digest(value, TOKEN)

    def authorized(self) -> bool:
        return self.token_matches(self.request_token()) or self.token_matches(self.cookie_token())

    def send_json(self, data: Any, status: HTTPStatus = HTTPStatus.OK) -> None:
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
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
            if self.token_matches(self.request_token()):
                self.send_response(HTTPStatus.SEE_OTHER)
                self.send_header("Location", "/")
                self.send_header("Set-Cookie", f"{COOKIE_NAME}={TOKEN}; HttpOnly; SameSite=Strict; Path=/")
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                return
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
                self.send_header("Cache-Control", "no-store")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            body = INDEX_HTML.encode("utf-8")
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
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
