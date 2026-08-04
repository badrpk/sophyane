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
    r"\b(?:read|show|check|open|summari[sz]e|find|search)\s+(?:my\s+)?(?:last|latest|newest|recent|unread)?\s*(?:email|mail|inbox|message)s?\b",
    r"\bmy\s+(?:email|mail|inbox|messages?)\b",
    r"\b(?:last|latest|newest|recent|unread)\s+(?:email|mail|message)\b",
)


def is_personal_connector_request(message: str) -> bool:
    text = " ".join(str(message or "").casefold().split())
    return any(re.search(pattern, text) for pattern in _EMAIL_PATTERNS)


def _operation(message: str) -> tuple[str, dict[str, Any]]:
    text = " ".join(str(message or "").casefold().split())
    if any(term in text for term in ("sent email", "sent mail", "outgoing email", "last email i sent")):
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
    data = json.dumps(payload, ensure_ascii=False).replace("</", "<\\/")
    title = "Email verified" if payload.get("ok") else "Email unavailable"
    return f'''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{html.escape(title)} — Sophyane</title>
<style>
:root{{--bg:#080b12;--panel:#121725;--panel2:#1a2132;--text:#f4f7fb;--muted:#9ca8ba;--line:rgba(255,255,255,.1);--accent:#78a7ff;--good:#3bd58b;--bad:#ff687f}}*{{box-sizing:border-box}}body{{margin:0;min-height:100vh;background:radial-gradient(circle at 85% 0%,rgba(120,167,255,.18),transparent 32%),var(--bg);color:var(--text);font-family:Inter,system-ui,sans-serif}}.shell{{width:min(1080px,calc(100% - 28px));margin:auto;padding:28px 0 70px}}nav{{position:sticky;top:12px;z-index:3;display:flex;justify-content:space-between;align-items:center;padding:13px 16px;border:1px solid var(--line);border-radius:17px;background:rgba(8,11,18,.8);backdrop-filter:blur(18px)}}.brand{{font-weight:850}}.badge{{padding:8px 12px;border-radius:999px;color:var(--good);border:1px solid color-mix(in srgb,var(--good) 45%,transparent)}}.badge.fail{{color:var(--bad);border-color:color-mix(in srgb,var(--bad) 45%,transparent)}}header{{padding:80px 0 45px}}.eyebrow{{color:var(--accent);text-transform:uppercase;letter-spacing:.16em;font-size:.75rem;font-weight:850}}h1{{font:clamp(3.2rem,8vw,7rem)/.92 Georgia,serif;letter-spacing:-.06em;margin:18px 0}}.sub{{color:var(--muted);font-size:1.1rem;line-height:1.7;max-width:760px}}.metrics{{display:grid;grid-template-columns:repeat(4,1fr);gap:13px;margin:25px 0 70px}}.metric,.card{{border:1px solid var(--line);background:var(--panel);border-radius:20px}}.metric{{padding:20px}}.metric span{{display:block;color:var(--muted);font-size:.74rem;text-transform:uppercase;letter-spacing:.1em}}.metric strong{{display:block;margin-top:10px;font:1.7rem Georgia,serif}}.flow{{display:grid;grid-template-columns:repeat(5,1fr);gap:10px;margin:25px 0 70px}}.node{{padding:18px;border:1px solid var(--line);border-radius:17px;background:var(--panel);opacity:.25;transform:translateY(12px);transition:.45s ease}}.node.on{{opacity:1;transform:none;border-color:rgba(120,167,255,.45)}}.node:not(:last-child):after{{content:'→';float:right;color:var(--accent)}}.node b{{display:block;margin-bottom:7px}}.node small{{color:var(--muted)}}.card{{padding:clamp(22px,4vw,42px);margin-bottom:18px}}.label{{color:var(--muted);text-transform:uppercase;letter-spacing:.1em;font-size:.72rem}}.value{{font-size:1.15rem;margin:8px 0 22px;overflow-wrap:anywhere}}.preview{{white-space:pre-wrap;line-height:1.75;color:#d5dce8;background:#090d15;border:1px solid var(--line);border-radius:15px;padding:18px;max-height:360px;overflow:auto}}.privacy{{display:flex;gap:10px;flex-wrap:wrap}}.chip{{padding:9px 12px;border-radius:999px;background:var(--panel2);color:var(--muted)}}footer{{color:var(--muted);border-top:1px solid var(--line);padding-top:25px;margin-top:55px}}@media(max-width:760px){{.metrics{{grid-template-columns:1fr 1fr}}.flow{{grid-template-columns:1fr}}.node:not(:last-child):after{{content:'↓'}}}}
@media(prefers-reduced-motion:reduce){{*{{transition:none!important}}}}</style></head><body><div class="shell"><nav><span class="brand">Sophyane Private Connector</span><span id="badge" class="badge"></span></nav><header><div class="eyebrow">Private-data boundary</div><h1 id="title"></h1><p class="sub" id="request"></p></header><section class="metrics" id="metrics"></section><section class="flow" id="flow"></section><section class="card" id="message"></section><section class="card"><div class="label">Privacy controls</div><div class="privacy"><span class="chip">Public internet blocked</span><span class="chip">SLI promotion blocked</span><span class="chip">Credentials excluded</span><span class="chip">Local report only</span></div></section><footer id="footer"></footer></div><script id="data" type="application/json">{data}</script><script>
const d=JSON.parse(document.getElementById('data').textContent);const e=s=>String(s??'').replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));const badge=document.getElementById('badge');badge.textContent=d.ok?'✓ Connector verified':'✕ Connector unavailable';if(!d.ok)badge.classList.add('fail');document.getElementById('title').textContent=d.ok?'Latest email retrieved.':'Email access is not configured.';document.getElementById('request').textContent=d.request;const metrics=[['Connector',d.connector],['Capability',d.capability],['Words',d.word_count||0],['Status',d.ok?'Verified':'Blocked']];document.getElementById('metrics').innerHTML=metrics.map(x=>`<article class="metric"><span>${e(x[0])}</span><strong>${e(x[1])}</strong></article>`).join('');const steps=[['Intent','Private email request'],['Boundary','Public acquisition blocked'],['Connector','Gmail IMAP selected'],['Verification',d.ok?'Response verified':'Configuration missing'],['Privacy','Promotion blocked']];const flow=document.getElementById('flow');flow.innerHTML=steps.map(x=>`<article class="node"><b>${e(x[0])}</b><small>${e(x[1])}</small></article>`).join('');[...flow.children].forEach((n,i)=>setTimeout(()=>n.classList.add('on'),i*220));const body=d.ok?`<div class="label">From</div><div class="value">${e(d.from||'(unknown)')}</div><div class="label">Subject</div><div class="value">${e(d.subject||'(no subject)')}</div><div class="label">Message preview</div><div class="preview">${e(d.preview||'(no plain-text preview)')}</div>`:`<div class="label">Connector status</div><div class="value">${e(d.message||d.error||'IMAP credentials missing.')}</div><div class="preview">Configure SOPHYANE_IMAP_USER and SOPHYANE_IMAP_APP_PASSWORD, or save imap_user and imap_app_password in Sophyane's secret vault. No public internet search was attempted.</div>`;document.getElementById('message').innerHTML=body;document.getElementById('footer').textContent=`Verified locally at ${d.verified_at} · ${d.internet_fallback} internet fallback · ${d.memory_promotion} memory promotion`;
</script></body></html>'''


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
    operation, args = _operation(request)
    progress(f"SLI private connector: email operation={operation}")
    try:
        from sophyane.connectors.email_imap.handler import execute
        result = execute(op=operation, args=args, profile=profile, manifest={})
    except Exception as error:
        result = {"ok": False, "error": "connector_error", "message": str(error)}
    payload = _safe_payload(result, request, operation)
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
            f"Subject: {payload['subject'] or '(no subject)'}",
            f"Words: {payload['word_count']}",
            "Internet fallback: blocked",
            "Memory promotion: blocked",
            f"Private report: {REPORT_NAME}",
        ]
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
