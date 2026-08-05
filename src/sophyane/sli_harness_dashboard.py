"""Animated browser dashboard for evidence-gated Sophyane harness runs."""
from __future__ import annotations

import html
import json
import mimetypes
import shutil
import socket
import subprocess
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

DASHBOARD_NAME = "harness-report.html"
SERVER_STATE_NAME = ".sophyane-dashboard-server.json"

_TEXT_SUFFIXES = {
    ".py", ".js", ".ts", ".tsx", ".jsx", ".html", ".css",
    ".json", ".yaml", ".yml", ".toml", ".md", ".txt", ".sh",
    ".cpp", ".cc", ".c", ".h", ".hpp", ".ini", ".cfg",
}


def _safe_json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
    ).replace("</", "<\\/")


def _clip(value: Any, limit: int = 12_000) -> str:
    text = str(value or "")
    if len(text) <= limit:
        return text
    return text[:limit] + "\n… output clipped …"


def _workspace_files(workspace: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []

    for path in sorted(workspace.rglob("*")):
        if not path.is_file():
            continue

        try:
            relative = path.relative_to(workspace).as_posix()
            stat = path.stat()
        except OSError:
            continue

        if relative in {
            DASHBOARD_NAME,
            SERVER_STATE_NAME,
            ".sophyane-harness-report.json",
        }:
            continue

        preview = ""
        previewable = path.suffix.lower() in _TEXT_SUFFIXES

        if previewable and stat.st_size <= 250_000:
            try:
                preview = path.read_text(
                    encoding="utf-8",
                    errors="replace",
                )
            except OSError:
                preview = ""

        rows.append(
            {
                "name": path.name,
                "path": relative,
                "size": stat.st_size,
                "type": (
                    mimetypes.guess_type(path.name)[0]
                    or "application/octet-stream"
                ),
                "preview": _clip(preview, 100_000),
                "previewable": bool(preview),
            }
        )

    return rows


def _normalise_commands(payload: dict[str, Any]) -> list[dict[str, Any]]:
    rows = payload.get("command_evidence")
    if not isinstance(rows, list):
        return []

    output = []

    for index, row in enumerate(rows, start=1):
        if not isinstance(row, dict):
            continue

        command = row.get("command")
        if isinstance(command, list):
            command_text = " ".join(str(part) for part in command)
        else:
            command_text = str(command or "")

        exit_code = row.get("exit_code")
        timed_out = bool(row.get("timed_out"))

        output.append(
            {
                "number": index,
                "command": command_text,
                "cwd": str(row.get("cwd") or ""),
                "exit_code": exit_code,
                "stdout": _clip(row.get("stdout")),
                "stderr": _clip(row.get("stderr")),
                "duration_ms": row.get("duration_ms") or 0,
                "timed_out": timed_out,
                "ok": (
                    not timed_out
                    and isinstance(exit_code, int)
                    and exit_code == 0
                ),
            }
        )

    return output


def _timeline(
    payload: dict[str, Any],
    command_count: int,
) -> list[dict[str, Any]]:
    promoted = bool(payload.get("promoted", True))
    ok = bool(payload.get("ok"))

    return [
        {
            "id": "intent",
            "label": "Intent",
            "description": "Request classified as an executable software task.",
            "status": "passed",
        },
        {
            "id": "policy",
            "label": "Policy",
            "description": "Workspace and evidence requirements were applied.",
            "status": "passed",
        },
        {
            "id": "capability",
            "label": "Capability",
            "description": str(
                payload.get("capability")
                or "Deterministic capability selected"
            ),
            "status": "passed" if payload.get("handled") else "failed",
        },
        {
            "id": "execution",
            "label": "Execution",
            "description": (
                f"{command_count} guarded command"
                + ("" if command_count == 1 else "s")
                + " executed."
            ),
            "status": "passed" if payload.get("kernel_ok") else "failed",
        },
        {
            "id": "verification",
            "label": "Verification",
            "description": "Exit codes, timeouts and outputs were inspected.",
            "status": "passed" if ok else "failed",
        },
        {
            "id": "evidence",
            "label": "Evidence",
            "description": "Machine-readable execution evidence was persisted.",
            "status": "passed",
        },
        {
            "id": "promotion",
            "label": "Learning",
            "description": (
                "Validated result eligible for SLI memory promotion."
                if promoted
                else "Promotion was not recorded in this report."
            ),
            "status": "passed" if ok else "blocked",
        },
    ]


def _render(
    workspace: Path,
    payload: dict[str, Any],
) -> str:
    commands = _normalise_commands(payload)
    files = _workspace_files(workspace)
    timeline = _timeline(payload, len(commands))

    duration_ms = float(payload.get("duration_ms") or 0)
    passed_commands = sum(1 for row in commands if row["ok"])
    failed_commands = len(commands) - passed_commands
    success = bool(payload.get("ok"))

    data = {
        "request": str(payload.get("request") or ""),
        "workspace": str(payload.get("workspace") or workspace),
        "capability": str(payload.get("capability") or "Unknown"),
        "success": success,
        "handled": bool(payload.get("handled")),
        "kernel_ok": bool(payload.get("kernel_ok")),
        "duration_ms": duration_ms,
        "commands": commands,
        "files": files,
        "timeline": timeline,
        "policy": payload.get("policy") or {},
        "passed_commands": passed_commands,
        "failed_commands": failed_commands,
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
    }

    embedded = _safe_json(data)
    page_title = html.escape(
        f"Sophyane Harness — {'Success' if success else 'Failed'}"
    )

    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="color-scheme" content="dark light">
<title>{page_title}</title>
<style>
:root {{
  --bg: #080b12;
  --panel: #111622;
  --panel-2: #171e2d;
  --text: #f3f6fb;
  --muted: #98a3b5;
  --line: rgba(255,255,255,.1);
  --good: #39d98a;
  --bad: #ff647c;
  --warn: #ffbd59;
  --accent: #79a8ff;
  --accent-2: #b680ff;
  --max: 1280px;
}}
* {{ box-sizing: border-box; }}
html {{ scroll-behavior: smooth; }}
body {{
  margin: 0;
  min-height: 100vh;
  color: var(--text);
  background:
    radial-gradient(circle at 82% 0%, rgba(121,168,255,.16), transparent 34%),
    radial-gradient(circle at 10% 22%, rgba(182,128,255,.12), transparent 30%),
    var(--bg);
  font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont,
    "Segoe UI", sans-serif;
}}
button {{ font: inherit; }}
.progress {{
  position: fixed;
  inset: 0 auto auto 0;
  z-index: 100;
  height: 3px;
  width: 0;
  background: linear-gradient(90deg, var(--accent), var(--accent-2));
}}
.shell {{
  width: min(var(--max), calc(100% - 28px));
  margin: auto;
  padding: 26px 0 70px;
}}
.topbar {{
  position: sticky;
  top: 12px;
  z-index: 40;
  display: flex;
  gap: 15px;
  align-items: center;
  justify-content: space-between;
  padding: 13px 16px;
  border: 1px solid var(--line);
  border-radius: 18px;
  background: rgba(8,11,18,.78);
  backdrop-filter: blur(18px);
}}
.brand {{
  display: flex;
  gap: 11px;
  align-items: center;
  font-weight: 800;
  letter-spacing: .04em;
}}
.brand-mark {{
  width: 32px;
  aspect-ratio: 1;
  border-radius: 10px;
  display: grid;
  place-items: center;
  background: linear-gradient(145deg, var(--accent), var(--accent-2));
  color: #08101f;
}}
.status-badge {{
  padding: 8px 12px;
  border: 1px solid color-mix(in srgb, var(--good) 45%, transparent);
  border-radius: 999px;
  color: var(--good);
  background: color-mix(in srgb, var(--good) 9%, transparent);
  font-weight: 750;
  font-size: .84rem;
}}
.status-badge.failed {{
  color: var(--bad);
  border-color: color-mix(in srgb, var(--bad) 45%, transparent);
  background: color-mix(in srgb, var(--bad) 9%, transparent);
}}
.hero {{
  padding: clamp(55px, 8vw, 105px) 0 45px;
  display: grid;
  grid-template-columns: minmax(0, 1.45fr) minmax(280px, .55fr);
  gap: 30px;
  align-items: end;
}}
.eyebrow {{
  color: var(--accent);
  text-transform: uppercase;
  letter-spacing: .18em;
  font-size: .76rem;
  font-weight: 850;
}}
h1 {{
  margin: 16px 0 20px;
  max-width: 880px;
  font-family: Georgia, serif;
  font-size: clamp(3rem, 7vw, 7.6rem);
  line-height: .91;
  letter-spacing: -.065em;
}}
.request {{
  max-width: 850px;
  color: #c3cada;
  font-size: clamp(1rem, 1.8vw, 1.25rem);
  line-height: 1.7;
}}
.hero-orbit {{
  position: relative;
  min-height: 290px;
  display: grid;
  place-items: center;
}}
.orbit-ring {{
  position: absolute;
  width: 240px;
  aspect-ratio: 1;
  border-radius: 50%;
  border: 1px solid rgba(121,168,255,.25);
  animation: spin 16s linear infinite;
}}
.orbit-ring:before,
.orbit-ring:after {{
  content: "";
  position: absolute;
  width: 13px;
  aspect-ratio: 1;
  border-radius: 50%;
  background: var(--accent);
  box-shadow: 0 0 28px var(--accent);
}}
.orbit-ring:before {{ top: 16px; left: 40px; }}
.orbit-ring:after {{ right: 12px; bottom: 64px; background: var(--accent-2); }}
.orbit-core {{
  width: 155px;
  aspect-ratio: 1;
  border-radius: 50%;
  display: grid;
  place-items: center;
  text-align: center;
  background: linear-gradient(145deg, var(--panel-2), #090d16);
  border: 1px solid var(--line);
  box-shadow: 0 20px 80px rgba(0,0,0,.35);
}}
.orbit-core strong {{
  display: block;
  font-family: Georgia, serif;
  font-size: 2.1rem;
}}
.orbit-core span {{
  color: var(--muted);
  font-size: .72rem;
  letter-spacing: .13em;
  text-transform: uppercase;
}}
@keyframes spin {{ to {{ transform: rotate(360deg); }} }}
.metrics {{
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 14px;
  margin-bottom: 70px;
}}
.metric {{
  padding: 21px;
  border: 1px solid var(--line);
  border-radius: 20px;
  background: linear-gradient(145deg, var(--panel), rgba(17,22,34,.68));
}}
.metric span {{
  display: block;
  color: var(--muted);
  font-size: .76rem;
  text-transform: uppercase;
  letter-spacing: .1em;
}}
.metric strong {{
  display: block;
  margin-top: 10px;
  font-family: Georgia, serif;
  font-size: clamp(1.8rem, 4vw, 3rem);
}}
.section {{
  margin: 82px 0;
}}
.section-head {{
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 22px;
  align-items: end;
  margin-bottom: 28px;
}}
.section-head h2 {{
  margin: 0;
  font-family: Georgia, serif;
  font-size: clamp(2.3rem, 5vw, 4.8rem);
  line-height: 1;
  letter-spacing: -.045em;
}}
.section-head p {{
  margin: 0;
  color: var(--muted);
  line-height: 1.7;
}}
.pipeline {{
  display: grid;
  grid-template-columns: repeat(7, minmax(120px, 1fr));
  gap: 10px;
  overflow-x: auto;
  padding: 8px 2px 20px;
}}
.node {{
  position: relative;
  min-height: 165px;
  padding: 18px;
  border: 1px solid var(--line);
  border-radius: 20px;
  background: var(--panel);
  opacity: .35;
  transform: translateY(13px);
  transition: opacity .5s ease, transform .5s ease, border-color .5s ease;
}}
.node.visible {{
  opacity: 1;
  transform: translateY(0);
}}
.node.passed {{
  border-color: color-mix(in srgb, var(--good) 45%, var(--line));
}}
.node.failed {{
  border-color: color-mix(in srgb, var(--bad) 55%, var(--line));
}}
.node.blocked {{
  border-color: color-mix(in srgb, var(--warn) 50%, var(--line));
}}
.node:not(:last-child):after {{
  content: "→";
  position: absolute;
  right: -11px;
  top: 50%;
  z-index: 3;
  color: var(--accent);
  font-weight: 900;
}}
.node-index {{
  color: var(--accent);
  font-family: Georgia, serif;
  font-size: 1.65rem;
}}
.node h3 {{
  margin: 18px 0 8px;
  font-size: 1rem;
}}
.node p {{
  margin: 0;
  color: var(--muted);
  font-size: .86rem;
  line-height: 1.5;
}}
.replay-controls {{
  display: flex;
  gap: 10px;
  flex-wrap: wrap;
  margin-top: 18px;
}}
.control {{
  cursor: pointer;
  color: var(--text);
  background: var(--panel);
  border: 1px solid var(--line);
  border-radius: 12px;
  padding: 10px 15px;
}}
.control.primary {{
  color: #07101e;
  background: var(--accent);
  border-color: var(--accent);
  font-weight: 800;
}}
.command-list {{
  display: grid;
  gap: 13px;
}}
.command {{
  border: 1px solid var(--line);
  border-radius: 19px;
  background: var(--panel);
  overflow: hidden;
}}
.command summary {{
  cursor: pointer;
  list-style: none;
  display: grid;
  grid-template-columns: auto 1fr auto auto;
  gap: 14px;
  align-items: center;
  padding: 17px 19px;
}}
.command summary::-webkit-details-marker {{ display: none; }}
.command-number {{
  width: 34px;
  aspect-ratio: 1;
  border-radius: 10px;
  display: grid;
  place-items: center;
  background: var(--panel-2);
  color: var(--accent);
  font-weight: 800;
}}
.command-code {{
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
}}
.exit {{
  color: var(--good);
  font-weight: 850;
}}
.exit.failed {{ color: var(--bad); }}
.duration {{ color: var(--muted); font-size: .84rem; }}
.command-body {{
  border-top: 1px solid var(--line);
  padding: 18px;
  display: grid;
  gap: 15px;
}}
.code-panel {{
  background: #070a10;
  border: 1px solid var(--line);
  border-radius: 14px;
  overflow: hidden;
}}
.code-label {{
  padding: 9px 13px;
  border-bottom: 1px solid var(--line);
  color: var(--muted);
  font-size: .74rem;
  text-transform: uppercase;
  letter-spacing: .1em;
}}
pre {{
  margin: 0;
  padding: 15px;
  overflow: auto;
  color: #d8e1ef;
  font: .84rem/1.6 ui-monospace, SFMono-Regular, Menlo, monospace;
  white-space: pre-wrap;
}}
.workspace-grid {{
  display: grid;
  grid-template-columns: 320px minmax(0, 1fr);
  min-height: 470px;
  border: 1px solid var(--line);
  border-radius: 22px;
  background: var(--panel);
  overflow: hidden;
}}
.file-list {{
  border-right: 1px solid var(--line);
  padding: 12px;
  overflow: auto;
}}
.file-button {{
  width: 100%;
  cursor: pointer;
  text-align: left;
  color: var(--text);
  background: transparent;
  border: 0;
  border-radius: 12px;
  padding: 11px 12px;
  display: grid;
  gap: 4px;
}}
.file-button:hover,
.file-button.active {{
  background: var(--panel-2);
}}
.file-button span {{
  color: var(--muted);
  font-size: .76rem;
}}
.preview {{
  min-width: 0;
  padding: 20px;
  background: #090c13;
}}
.preview-head {{
  display: flex;
  justify-content: space-between;
  gap: 15px;
  margin-bottom: 13px;
  color: var(--muted);
}}
.preview pre {{
  max-height: 650px;
}}
.empty {{
  padding: 25px;
  color: var(--muted);
  text-align: center;
}}
footer {{
  margin-top: 85px;
  padding: 30px 0;
  border-top: 1px solid var(--line);
  color: var(--muted);
  display: flex;
  justify-content: space-between;
  gap: 20px;
  flex-wrap: wrap;
}}
.reveal {{
  opacity: 0;
  transform: translateY(15px);
  transition: .55s ease;
}}
.reveal.visible {{
  opacity: 1;
  transform: none;
}}
@media (max-width: 900px) {{
  .hero {{ grid-template-columns: 1fr; }}
  .hero-orbit {{ min-height: 230px; }}
  .metrics {{ grid-template-columns: repeat(2, 1fr); }}
  .section-head {{ grid-template-columns: 1fr; }}
  .workspace-grid {{ grid-template-columns: 1fr; }}
  .file-list {{
    border-right: 0;
    border-bottom: 1px solid var(--line);
    max-height: 230px;
  }}
}}
@media (max-width: 560px) {{
  .metrics {{ grid-template-columns: 1fr 1fr; }}
  .command summary {{
    grid-template-columns: auto minmax(0, 1fr);
  }}
  .exit, .duration {{ grid-column: 2; }}
  .topbar {{ align-items: flex-start; }}
}}
@media (prefers-reduced-motion: reduce) {{
  *, *:before, *:after {{
    animation-duration: .01ms !important;
    animation-iteration-count: 1 !important;
    scroll-behavior: auto !important;
    transition-duration: .01ms !important;
  }}
}}
</style>
</head>
<body>
<div class="progress" id="progress"></div>
<div class="shell">
  <nav class="topbar">
    <div class="brand">
      <span class="brand-mark">S</span>
      <span>Sophyane Harness Observatory</span>
    </div>
    <span id="statusBadge" class="status-badge"></span>
  </nav>

  <header class="hero">
    <div>
      <div class="eyebrow">Verified execution report</div>
      <h1 id="heroTitle">Mission complete.</h1>
      <p class="request" id="requestText"></p>
    </div>
    <div class="hero-orbit" aria-hidden="true">
      <div class="orbit-ring"></div>
      <div class="orbit-core">
        <div>
          <strong id="successScore">100%</strong>
          <span>Evidence score</span>
        </div>
      </div>
    </div>
  </header>

  <section class="metrics reveal" id="metrics"></section>

  <section class="section reveal">
    <div class="section-head">
      <h2>Execution graph</h2>
      <p>
        Replay the deterministic path from intent classification through
        guarded execution, verification, evidence and SLI learning.
      </p>
    </div>
    <div class="pipeline" id="pipeline"></div>
    <div class="replay-controls">
      <button class="control primary" id="replayButton" type="button">
        Replay mission
      </button>
      <button class="control" id="showAllButton" type="button">
        Show all steps
      </button>
    </div>
  </section>

  <section class="section reveal">
    <div class="section-head">
      <h2>Evidence explorer</h2>
      <p>
        Every command exposes its real working directory, duration, exit
        status, standard output and standard error.
      </p>
    </div>
    <div class="command-list" id="commandList"></div>
  </section>

  <section class="section reveal">
    <div class="section-head">
      <h2>Workspace</h2>
      <p>
        Inspect artifacts produced by the mission. Text-based files can be
        viewed directly without leaving the report.
      </p>
    </div>
    <div class="workspace-grid">
      <div class="file-list" id="fileList"></div>
      <div class="preview" id="filePreview"></div>
    </div>
  </section>

  <footer>
    <span id="generatedAt"></span>
    <span id="capabilityFooter"></span>
  </footer>
</div>

<script id="report-data" type="application/json">{embedded}</script>
<script>
"use strict";

const data = JSON.parse(
  document.getElementById("report-data").textContent
);

const esc = (value) => String(value ?? "")
  .replaceAll("&", "&amp;")
  .replaceAll("<", "&lt;")
  .replaceAll(">", "&gt;")
  .replaceAll('"', "&quot;")
  .replaceAll("'", "&#039;");

const formatBytes = (bytes) => {{
  const value = Number(bytes || 0);
  if (value < 1024) return `${{value}} B`;
  if (value < 1024 ** 2) return `${{(value / 1024).toFixed(1)}} KB`;
  return `${{(value / 1024 ** 2).toFixed(1)}} MB`;
}};

const statusBadge = document.getElementById("statusBadge");
statusBadge.textContent = data.success ? "✓ Verified success" : "✕ Execution failed";
if (!data.success) statusBadge.classList.add("failed");

document.getElementById("heroTitle").textContent =
  data.success ? "Mission complete." : "Mission requires attention.";

document.getElementById("requestText").textContent = data.request;
document.getElementById("generatedAt").textContent =
  `Generated ${{data.generated_at}}`;
document.getElementById("capabilityFooter").textContent =
  `Capability: ${{data.capability}}`;

const qualityParts = [
  data.handled,
  data.kernel_ok,
  data.failed_commands === 0,
  data.commands.length > 0
];
const score = Math.round(
  100 * qualityParts.filter(Boolean).length / qualityParts.length
);
document.getElementById("successScore").textContent = `${{score}}%`;

const metrics = [
  ["Result", data.success ? "Passed" : "Failed"],
  ["Commands", data.commands.length],
  ["Artifacts", data.files.length],
  ["Duration", `${{Number(data.duration_ms).toFixed(1)}} ms`]
];

document.getElementById("metrics").innerHTML = metrics.map(
  ([label, value]) => `
    <article class="metric">
      <span>${{esc(label)}}</span>
      <strong>${{esc(value)}}</strong>
    </article>
  `
).join("");

const pipeline = document.getElementById("pipeline");

pipeline.innerHTML = data.timeline.map((step, index) => `
  <article class="node ${{esc(step.status)}}" data-step="${{index}}">
    <span class="node-index">${{String(index + 1).padStart(2, "0")}}</span>
    <h3>${{esc(step.label)}}</h3>
    <p>${{esc(step.description)}}</p>
  </article>
`).join("");

let replayTimer = null;

function showPipeline(delay = 160) {{
  clearTimeout(replayTimer);
  const nodes = [...pipeline.querySelectorAll(".node")];
  nodes.forEach(node => node.classList.remove("visible"));

  nodes.forEach((node, index) => {{
    replayTimer = setTimeout(
      () => node.classList.add("visible"),
      index * delay
    );
  }});
}}

document.getElementById("replayButton").addEventListener(
  "click",
  () => showPipeline(360)
);

document.getElementById("showAllButton").addEventListener(
  "click",
  () => pipeline.querySelectorAll(".node").forEach(
    node => node.classList.add("visible")
  )
);

const commandList = document.getElementById("commandList");

if (!data.commands.length) {{
  commandList.innerHTML =
    '<div class="empty">No command-level evidence was recorded.</div>';
}} else {{
  commandList.innerHTML = data.commands.map(command => `
    <details class="command">
      <summary>
        <span class="command-number">${{command.number}}</span>
        <span class="command-code">${{esc(command.command)}}</span>
        <span class="exit ${{command.ok ? "" : "failed"}}">
          exit ${{esc(command.exit_code)}}
        </span>
        <span class="duration">
          ${{Number(command.duration_ms).toFixed(1)}} ms
        </span>
      </summary>
      <div class="command-body">
        <div class="code-panel">
          <div class="code-label">Working directory</div>
          <pre>${{esc(command.cwd)}}</pre>
        </div>
        <div class="code-panel">
          <div class="code-label">Standard output</div>
          <pre>${{esc(command.stdout || "(empty)")}}</pre>
        </div>
        <div class="code-panel">
          <div class="code-label">Standard error</div>
          <pre>${{esc(command.stderr || "(empty)")}}</pre>
        </div>
      </div>
    </details>
  `).join("");
}}

const fileList = document.getElementById("fileList");
const filePreview = document.getElementById("filePreview");

function previewFile(index) {{
  const file = data.files[index];

  fileList.querySelectorAll(".file-button").forEach(
    button => button.classList.toggle(
      "active",
      Number(button.dataset.index) === index
    )
  );

  if (!file) {{
    filePreview.innerHTML =
      '<div class="empty">No file selected.</div>';
    return;
  }}

  filePreview.innerHTML = `
    <div class="preview-head">
      <strong>${{esc(file.path)}}</strong>
      <span>${{esc(file.type)}} · ${{formatBytes(file.size)}}</span>
    </div>
    <div class="code-panel">
      <pre>${{
        file.previewable
          ? esc(file.preview)
          : "Binary or large file — preview unavailable."
      }}</pre>
    </div>
  `;
}}

if (!data.files.length) {{
  fileList.innerHTML =
    '<div class="empty">No generated artifacts found.</div>';
  filePreview.innerHTML =
    '<div class="empty">Workspace is empty.</div>';
}} else {{
  fileList.innerHTML = data.files.map((file, index) => `
    <button class="file-button" data-index="${{index}}" type="button">
      <strong>${{esc(file.path)}}</strong>
      <span>${{formatBytes(file.size)}} · ${{esc(file.type)}}</span>
    </button>
  `).join("");

  fileList.querySelectorAll(".file-button").forEach(button => {{
    button.addEventListener(
      "click",
      () => previewFile(Number(button.dataset.index))
    );
  }});

  previewFile(0);
}}

const revealObserver = new IntersectionObserver(
  entries => entries.forEach(entry => {{
    if (entry.isIntersecting) entry.target.classList.add("visible");
  }}),
  {{ threshold: 0.12 }}
);

document.querySelectorAll(".reveal").forEach(
  element => revealObserver.observe(element)
);

window.addEventListener("scroll", () => {{
  const maximum =
    document.documentElement.scrollHeight - window.innerHeight;
  const percentage = maximum > 0
    ? 100 * window.scrollY / maximum
    : 0;

  document.getElementById("progress").style.width =
    `${{percentage}}%`;
}}, {{ passive: true }});

showPipeline();
</script>
</body>
</html>
"""


def build_dashboard(
    workspace: Path | str,
    payload: dict[str, Any],
) -> Path:
    root = Path(workspace).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)

    output = root / DASHBOARD_NAME
    output.write_text(
        _render(root, payload),
        encoding="utf-8",
    )
    return output


def _port_open(port: int) -> bool:
    try:
        with socket.create_connection(
            ("127.0.0.1", port),
            timeout=0.25,
        ):
            return True
    except OSError:
        return False


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _server_url(workspace: Path, output: Path) -> str:
    state_path = workspace / SERVER_STATE_NAME

    try:
        state = json.loads(
            state_path.read_text(encoding="utf-8")
        )
        port = int(state.get("port") or 0)
        directory = str(state.get("workspace") or "")

        if (
            port > 0
            and directory == str(workspace)
            and _port_open(port)
        ):
            return (
                f"http://127.0.0.1:{port}/"
                f"{urllib.parse.quote(output.name)}"
            )
    except Exception:
        pass

    preferred = 8767
    port = preferred if not _port_open(preferred) else _free_port()

    subprocess.Popen(
        [
            sys.executable,
            "-m",
            "http.server",
            str(port),
            "--bind",
            "127.0.0.1",
            "--directory",
            str(workspace),
        ],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )

    deadline = time.time() + 3
    while time.time() < deadline:
        if _port_open(port):
            break
        time.sleep(0.08)

    state_path.write_text(
        json.dumps(
            {
                "port": port,
                "workspace": str(workspace),
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    return (
        f"http://127.0.0.1:{port}/"
        f"{urllib.parse.quote(output.name)}"
    )


def _open_url(url: str) -> bool:
    commands: list[list[str]] = []

    if shutil.which("termux-open-url"):
        commands.append(["termux-open-url", url])

    if shutil.which("am"):
        commands.append(
            [
                "am",
                "start",
                "-a",
                "android.intent.action.VIEW",
                "-d",
                url,
            ]
        )

    if shutil.which("xdg-open"):
        commands.append(["xdg-open", url])
    elif shutil.which("open"):
        commands.append(["open", url])

    for command in commands:
        try:
            subprocess.Popen(
                command,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
            return True
        except OSError:
            continue

    return False


def build_and_open_dashboard(
    workspace: Path | str,
    payload: dict[str, Any],
) -> str:
    root = Path(workspace).expanduser().resolve()
    output = build_dashboard(root, payload)
    url = _server_url(root, output)

    # Verify that Chrome will receive a valid HTTP page.
    try:
        with urllib.request.urlopen(url, timeout=2) as response:
            if response.status != 200:
                return str(output)
    except Exception:
        return str(output)

    _open_url(url)
    return url


__all__ = [
    "DASHBOARD_NAME",
    "build_and_open_dashboard",
    "build_dashboard",
]
