"""Fail-closed personal connector orchestration for Sophyane Option 1."""
from __future__ import annotations

import html
import json
import re
import shutil
import socket
import subprocess
import sys
import time
import urllib.parse
from pathlib import Path
from typing import Any, Callable

Progress = Callable[[str], None]
REPORT_NAME = ".sophyane-personal-connector-report.json"
DASHBOARD_NAME = "connector-report.html"

_EMAIL_PATTERNS = (
    # General inbox and email requests.
    r"\b(?:read|show|check|open|summari[sz]e|find|search)\s+"
    r"(?:my\s+)?"
    r"(?:last|latest|newest|recent|unread|sent|outgoing)?\s*"
    r"(?:email|mail|inbox|message)s?\b",

    # Direct ownership phrases.
    r"\bmy\s+(?:email|mail|inbox|messages?)\b",

    # Latest incoming or outgoing message.
    r"\b(?:last|latest|newest|recent|unread)\s+"
    r"(?:sent|outgoing\s+)?"
    r"(?:email|mail|message)\b",

    # Natural-language sent-mail variants.
    r"\b(?:what\s+(?:was|is)\s+)?"
    r"(?:my\s+)?"
    r"(?:last|latest|newest|recent)\s+"
    r"(?:outgoing|sent)\s+"
    r"(?:email|mail|message)\b",

    r"\b(?:last|latest|newest|recent)\s+"
    r"(?:email|mail|message)\s+i\s+sent\b",

    r"\bwhat\s+(?:was|is)\s+"
    r"(?:the\s+)?"
    r"(?:last|latest)\s+"
    r"(?:email|mail|message)\s+i\s+sent\b",

    # Folder-oriented requests.
    r"\b(?:show|check|read|open)\s+"
    r"(?:my\s+)?sent\s+(?:mail|email|messages?|folder)\b",
)


def is_personal_connector_request(message: str) -> bool:
    text = " ".join(str(message or "").casefold().split())
    return any(re.search(pattern, text) for pattern in _EMAIL_PATTERNS)


_MESSAGE_SOURCES = (
    ("email", "Email / Gmail"),
    ("whatsapp", "WhatsApp"),
    ("sms", "SMS / phone messages"),
    ("snapchat", "Snapchat"),
    ("wechat", "WeChat"),
)


def _explicit_message_source(message: str) -> str:
    """Return the explicitly named private-message source, if any."""
    text = " ".join(str(message or "").casefold().split())

    if any(term in text for term in ("email", "e-mail", "mail", "inbox")):
        return "email"
    if "whatsapp" in text or "whats app" in text:
        return "whatsapp"
    if any(term in text for term in ("sms", "text message", "phone message")):
        return "sms"
    if "snapchat" in text or "snap chat" in text:
        return "snapchat"
    if "wechat" in text or "we chat" in text:
        return "wechat"

    return ""


def _is_generic_message_request(message: str) -> bool:
    """True when the user asks for a message without naming its source."""
    text = " ".join(str(message or "").casefold().split())

    if _explicit_message_source(text):
        return False

    return bool(
        re.search(
            r"\b(?:last|latest|newest|recent|unread|sent|outgoing)?\s*"
            r"(?:message|messages)\b",
            text,
        )
    )


def _choose_message_source() -> str:
    """Ask which private messaging source the user means."""
    if not sys.stdin.isatty():
        return ""

    print()
    print("Which type of message do you mean?")
    print()

    for number, (_source, label) in enumerate(
        _MESSAGE_SOURCES,
        start=1,
    ):
        availability = (
            "connected"
            if _source == "email"
            else "connector not installed"
        )
        print(f"  {number}. {label} — {availability}")

    print("  0. Cancel")
    print()

    try:
        answer = input(
            "Select message source [0-5]: "
        ).strip()
    except (EOFError, KeyboardInterrupt):
        print()
        return ""

    try:
        index = int(answer)
    except ValueError:
        return ""

    if index == 0:
        return ""

    if 1 <= index <= len(_MESSAGE_SOURCES):
        return _MESSAGE_SOURCES[index - 1][0]

    return ""


def _unsupported_source_report(
    source: str,
    request: str,
) -> str:
    labels = {
        "whatsapp": "WhatsApp",
        "sms": "SMS / phone messages",
        "snapchat": "Snapchat",
        "wechat": "WeChat",
    }

    label = labels.get(source, source or "that source")

    return "\n".join(
        [
            "Sophyane private connector",
            f"Request: {request}",
            f"Selected source: {label}",
            "Connector available: False",
            (
                f"{label} access is not connected yet. "
                "Sophyane will not substitute email or invent a result."
            ),
            "Internet fallback: blocked",
            "Memory promotion: blocked",
            "Success: False",
        ]
    )


def _operation(message: str) -> tuple[str, dict[str, Any]]:
    text = " ".join(str(message or "").casefold().split())

    sent_request = any(
        term in text
        for term in (
            "sent email",
            "sent mail",
            "sent message",
            "outgoing email",
            "outgoing mail",
            "outgoing message",
            "last email i sent",
            "latest email i sent",
            "newest email i sent",
            "recent email i sent",
            "last mail i sent",
            "latest mail i sent",
            "last message i sent",
            "latest message i sent",
            "newest message i sent",
            "recent message i sent",
            "sent folder",
        )
    )

    if sent_request:
        return "latest_sent", {}
    if any(term in text for term in ("search", "find", "about", "from ")) and not any(
        term in text for term in ("last email", "latest email", "newest email", "recent email")
    ):
        return "search", {"query": message}
    return "latest", {}


def _preview_from_formatted(value: str) -> str:
    lines = []
    capture = False
    for raw in str(value or "").splitlines():
        if "Preview" in raw:
            capture = True
            continue
        if capture:
            clean = raw.lstrip("│ ").strip()
            if clean and clean != "└─":
                lines.append(clean)
    return "\n".join(lines)[:1600]


def _safe_payload(result: dict[str, Any], request: str, operation: str) -> dict[str, Any]:
    return {
        "request": request,
        "capability": f"email.{operation}",
        "connector": "gmail_imap",
        "ok": bool(result.get("ok")),
        "error": str(result.get("error") or ""),
        "message": str(result.get("message") or ""),
        "from": str(result.get("from") or ""),
        "to": str(result.get("to") or ""),
        "subject": str(result.get("subject") or ""),
        "word_count": int(result.get("word_count") or 0),
        "matches": int(result.get("matches") or 0),
        "empty": bool(result.get("empty")),
        "preview": _preview_from_formatted(str(result.get("formatted") or "")),
        "verified_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "internet_fallback": "blocked",
        "memory_promotion": "blocked",
    }


def _render(payload: dict[str, Any]) -> str:
    """Render a privacy-safe connector report without Python f-string braces."""

    title = (
        "Email verified"
        if payload.get("ok")
        else "Email unavailable"
    )

    data = json.dumps(
        payload,
        ensure_ascii=False,
    ).replace("</", "<\\/")

    document = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>__TITLE__ — Sophyane</title>
<style>
:root {
  --bg: #080b12;
  --panel: #121725;
  --text: #f4f7fb;
  --muted: #9ca8ba;
  --line: rgba(255,255,255,.11);
  --accent: #78a7ff;
  --good: #3bd58b;
  --bad: #ff687f;
}
* { box-sizing: border-box; }
body {
  margin: 0;
  min-height: 100vh;
  color: var(--text);
  background:
    radial-gradient(circle at 85% 0%, rgba(120,167,255,.18), transparent 34%),
    var(--bg);
  font-family: system-ui, sans-serif;
}
main {
  width: min(960px, calc(100% - 28px));
  margin: auto;
  padding: 28px 0 70px;
}
nav {
  display: flex;
  justify-content: space-between;
  gap: 14px;
  padding: 14px 17px;
  border: 1px solid var(--line);
  border-radius: 18px;
  background: rgba(8,11,18,.82);
}
.badge {
  color: var(--good);
  font-weight: 700;
}
.badge.fail { color: var(--bad); }
header { padding: 72px 0 38px; }
.eyebrow {
  color: var(--accent);
  font-size: .75rem;
  font-weight: 800;
  letter-spacing: .14em;
  text-transform: uppercase;
}
h1 {
  margin: 16px 0;
  font: clamp(3rem, 8vw, 6rem)/.95 Georgia, serif;
  letter-spacing: -.055em;
}
.request {
  color: var(--muted);
  font-size: 1.1rem;
  line-height: 1.7;
}
.metrics {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 12px;
  margin: 20px 0 55px;
}
.metric,
.card {
  border: 1px solid var(--line);
  border-radius: 19px;
  background: var(--panel);
}
.metric { padding: 18px; }
.metric span {
  display: block;
  color: var(--muted);
  font-size: .72rem;
  letter-spacing: .09em;
  text-transform: uppercase;
}
.metric strong {
  display: block;
  margin-top: 9px;
  font: 1.45rem Georgia, serif;
}
.flow {
  display: grid;
  grid-template-columns: repeat(5, 1fr);
  gap: 10px;
  margin-bottom: 55px;
}
.node {
  padding: 17px;
  border: 1px solid var(--line);
  border-radius: 16px;
  background: var(--panel);
  opacity: .25;
  transform: translateY(12px);
  transition: .45s ease;
}
.node.visible {
  opacity: 1;
  transform: none;
  border-color: rgba(120,167,255,.5);
}
.node b { display: block; margin-bottom: 7px; }
.node small { color: var(--muted); }
.card {
  padding: clamp(22px, 4vw, 40px);
  margin-bottom: 18px;
}
.label {
  color: var(--muted);
  font-size: .72rem;
  letter-spacing: .1em;
  text-transform: uppercase;
}
.value {
  margin: 8px 0 22px;
  overflow-wrap: anywhere;
}
.preview {
  max-height: 360px;
  overflow: auto;
  padding: 18px;
  border: 1px solid var(--line);
  border-radius: 14px;
  background: #090d15;
  color: #d7dfeb;
  line-height: 1.7;
  white-space: pre-wrap;
}
.privacy {
  display: flex;
  flex-wrap: wrap;
  gap: 9px;
}
.chip {
  padding: 9px 12px;
  border-radius: 999px;
  background: rgba(255,255,255,.06);
  color: var(--muted);
}
footer {
  margin-top: 50px;
  padding-top: 22px;
  border-top: 1px solid var(--line);
  color: var(--muted);
}
@media (max-width: 720px) {
  .metrics { grid-template-columns: 1fr 1fr; }
  .flow { grid-template-columns: 1fr; }
}
@media (prefers-reduced-motion: reduce) {
  * { transition: none !important; }
}
</style>
</head>
<body>
<main>
<nav>
  <strong>Sophyane Private Connector</strong>
  <span id="badge" class="badge"></span>
</nav>

<header>
  <div class="eyebrow">Private-data boundary</div>
  <h1 id="title"></h1>
  <p id="request" class="request"></p>
</header>

<section id="metrics" class="metrics"></section>
<section id="flow" class="flow"></section>
<section id="message" class="card"></section>

<section class="card">
  <div class="label">Privacy controls</div>
  <div class="privacy">
    <span class="chip">Public internet blocked</span>
    <span class="chip">SLI promotion blocked</span>
    <span class="chip">Credentials excluded</span>
    <span class="chip">Local report only</span>
  </div>
</section>

<footer id="footer"></footer>
</main>

<script id="report-data" type="application/json">__DATA__</script>
<script>
"use strict";

const report = JSON.parse(
  document.getElementById("report-data").textContent
);

function escapeHtml(value) {
  return String(value ?? "").replace(
    /[&<>"']/g,
    function(character) {
      return {
        "&": "&amp;",
        "<": "&lt;",
        ">": "&gt;",
        '"': "&quot;",
        "'": "&#39;"
      }[character];
    }
  );
}

const badge = document.getElementById("badge");
badge.textContent = report.ok
  ? "✓ Connector verified"
  : "✕ Connector unavailable";

if (!report.ok) {
  badge.classList.add("fail");
}

document.getElementById("title").textContent = report.ok
  ? "Latest email retrieved."
  : "Email access is not configured.";

document.getElementById("request").textContent = report.request;

const metrics = [
  ["Connector", report.connector],
  ["Capability", report.capability],
  ["Words", report.word_count || 0],
  ["Status", report.ok ? "Verified" : "Blocked"]
];

document.getElementById("metrics").innerHTML = metrics.map(
  function(item) {
    return (
      '<article class="metric">' +
      "<span>" + escapeHtml(item[0]) + "</span>" +
      "<strong>" + escapeHtml(item[1]) + "</strong>" +
      "</article>"
    );
  }
).join("");

const steps = [
  ["Intent", "Private email request"],
  ["Boundary", "Public acquisition blocked"],
  ["Connector", "Gmail IMAP selected"],
  [
    "Verification",
    report.ok ? "Response verified" : "Configuration missing"
  ],
  ["Privacy", "Memory promotion blocked"]
];

const flow = document.getElementById("flow");

flow.innerHTML = steps.map(
  function(step) {
    return (
      '<article class="node">' +
      "<b>" + escapeHtml(step[0]) + "</b>" +
      "<small>" + escapeHtml(step[1]) + "</small>" +
      "</article>"
    );
  }
).join("");

Array.from(flow.children).forEach(
  function(node, index) {
    setTimeout(
      function() {
        node.classList.add("visible");
      },
      index * 200
    );
  }
);

let messageHtml = "";

if (report.ok) {
  messageHtml =
    '<div class="label">From</div>' +
    '<div class="value">' +
    escapeHtml(report.from || "(unknown)") +
    "</div>" +
    '<div class="label">Subject</div>' +
    '<div class="value">' +
    escapeHtml(report.subject || "(no subject)") +
    "</div>" +
    '<div class="label">Message preview</div>' +
    '<div class="preview">' +
    escapeHtml(report.preview || "(no plain-text preview)") +
    "</div>";
} else {
  messageHtml =
    '<div class="label">Connector status</div>' +
    '<div class="value">' +
    escapeHtml(
      report.message ||
      report.error ||
      "IMAP credentials missing."
    ) +
    "</div>" +
    '<div class="preview">' +
    "Configure SOPHYANE_IMAP_USER and " +
    "SOPHYANE_IMAP_APP_PASSWORD. " +
    "No public internet search was attempted." +
    "</div>";
}

document.getElementById("message").innerHTML = messageHtml;

document.getElementById("footer").textContent =
  "Verified locally at " + report.verified_at +
  " · internet fallback " + report.internet_fallback +
  " · memory promotion " + report.memory_promotion;
</script>
</body>
</html>
"""

    return (
        document
        .replace("__TITLE__", html.escape(title))
        .replace("__DATA__", data)
    )


def _open_dashboard(workspace: Path, payload: dict[str, Any]) -> str:
    output = workspace / DASHBOARD_NAME
    output.write_text(_render(payload), encoding="utf-8")
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        port = int(sock.getsockname()[1])
    subprocess.Popen([sys.executable, "-m", "http.server", str(port), "--bind", "127.0.0.1", "--directory", str(workspace)], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
    time.sleep(.35)
    url = f"http://127.0.0.1:{port}/{urllib.parse.quote(output.name)}"
    commands = []
    if shutil.which("termux-open-url"):
        commands.append(["termux-open-url", url])
    if shutil.which("am"):
        commands.append(["am", "start", "-a", "android.intent.action.VIEW", "-d", url])
    for command in commands:
        try:
            subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
            break
        except OSError:
            continue
    return url


def run_personal_connector(request: str, workspace: Path | str, *, progress: Progress | None = None, profile: str = "default") -> str:
    progress = progress or (lambda _message: None)
    root = Path(workspace).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    source = _explicit_message_source(request)

    if not source and _is_generic_message_request(request):
        source = _choose_message_source()

        if not source:
            return "\n".join(
                [
                    "Sophyane private connector",
                    "Message source was not selected.",
                    "No connector was queried.",
                    "Internet fallback: blocked",
                    "Memory promotion: blocked",
                    "Success: False",
                ]
            )

    # Existing private email phrases that do not contain the literal word
    # "email" still remain email operations when already classified as such.
    if not source:
        source = "email"

    if source != "email":
        return _unsupported_source_report(
            source,
            request,
        )

    operation, args = _operation(request)
    progress(f"SLI private connector: email operation={operation}")
    try:
        from sophyane.connectors.email_imap.handler import execute

        result = execute(
            op=operation,
            args=args,
            profile=profile,
            manifest={},
        )

        # A private connector request should complete the setup workflow
        # instead of merely reporting that credentials are missing.
        if (
            not result.get("ok")
            and result.get("error") == "not_configured"
        ):
            from sophyane.gmail_setup_wizard import (
                configure_gmail_interactively,
            )

            setup = configure_gmail_interactively(
                profile=profile,
                progress=progress,
            )

            if setup.get("ok"):
                # Retry the original email request immediately after
                # successful verification and vault storage.
                result = execute(
                    op=operation,
                    args=args,
                    profile=profile,
                    manifest={},
                )
            else:
                result = {
                    "ok": False,
                    "error": str(
                        setup.get("error")
                        or "not_configured"
                    ),
                    "message": str(
                        setup.get("message")
                        or "Gmail setup was not completed."
                    ),
                }

    except Exception as error:
        result = {
            "ok": False,
            "error": "connector_error",
            "message": str(error),
        }

    payload = _safe_payload(
        result,
        request,
        operation,
    )
    (root / REPORT_NAME).write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    try:
        dashboard = _open_dashboard(root, payload)
    except Exception as error:
        progress(f"SLI private connector dashboard unavailable: {error}")
        dashboard = ""
    if payload["ok"]:
        lines = [
            "Sophyane private connector",
            f"Capability: {payload['capability']}",
            "Connector: gmail_imap",
            "Connector verified: True",
            f"From: {payload['from'] or '(unknown)'}",
        ]

        if payload.get("to"):
            lines.append(
                f"To: {payload['to']}"
            )

        lines.extend(
            [
                f"Subject: {payload['subject'] or '(no subject)'}",
                f"Words: {payload['word_count']}",
                "",
                "Message:",
                payload.get("preview") or "(no plain-text message preview)",
                "",
                "Internet fallback: blocked",
                "Memory promotion: blocked",
                f"Private report: {REPORT_NAME}",
            ]
        )
        if dashboard:
            lines.append(f"Visual dashboard: {dashboard}")
        lines.append("Success: True")
        return "\n".join(lines)
    lines = [
        "Sophyane private connector",
        f"Capability: {payload['capability']}",
        "Connector: gmail_imap",
        "Connector available: False",
        f"Reason: {payload['message'] or payload['error'] or 'not configured'}",
        "Internet fallback: blocked",
        "Memory promotion: blocked",
        f"Private report: {REPORT_NAME}",
    ]
    if dashboard:
        lines.append(f"Visual dashboard: {dashboard}")
    lines.append("Success: False")
    return "\n".join(lines)


__all__ = ["is_personal_connector_request", "run_personal_connector"]
