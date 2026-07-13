"""Mobile-friendly Sophyane web interface using only Python's standard library."""

from __future__ import annotations

import argparse
import json
import threading
import webbrowser
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from sophyane.agent import SophyaneAgent
from sophyane.logging_config import configure_logging
from sophyane.main import create_provider, load_runtime_config, show_status
from sophyane.memory import MemoryStore
from sophyane.version import __version__


HTML = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<meta name="theme-color" content="#101827">
<title>Sophyane</title>
<style>
:root{color-scheme:dark;--bg:#0b1020;--panel:#151d2f;--line:#2a3650;--text:#eef4ff;--muted:#9fb0ca;--accent:#67e8f9}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);font:16px system-ui,-apple-system,Segoe UI,sans-serif}
main{max-width:900px;margin:auto;min-height:100vh;display:flex;flex-direction:column;padding:16px}
header{display:flex;justify-content:space-between;align-items:center;border-bottom:1px solid var(--line);padding-bottom:12px}
h1{font-size:1.3rem;margin:0}.status{font-size:.82rem;color:var(--muted)}
#chat{flex:1;overflow:auto;padding:18px 0}.msg{max-width:85%;white-space:pre-wrap;line-height:1.45;padding:12px 14px;border-radius:14px;margin:10px 0;background:var(--panel);border:1px solid var(--line)}
.user{margin-left:auto;background:#173248}.assistant{margin-right:auto}form{position:sticky;bottom:0;display:flex;gap:8px;padding:12px 0;background:var(--bg)}
textarea{flex:1;resize:none;min-height:52px;max-height:160px;border:1px solid var(--line);border-radius:14px;background:var(--panel);color:var(--text);padding:14px;font:inherit}
button{border:0;border-radius:14px;padding:0 18px;background:var(--accent);color:#08202a;font-weight:700}button:disabled{opacity:.5}
small{color:var(--muted)}
</style>
</head>
<body><main>
<header><div><h1>🧠 Sophyane</h1><small>Private local AI harness</small></div><div class="status" id="status">Connecting…</div></header>
<section id="chat"><div class="msg assistant">Welcome. Your conversations and API keys remain on the host device.</div></section>
<form id="form"><textarea id="prompt" placeholder="Ask Sophyane…" required></textarea><button id="send">Send</button></form>
</main>
<script>
const chat=document.querySelector('#chat'),form=document.querySelector('#form'),prompt=document.querySelector('#prompt'),send=document.querySelector('#send');
function add(text,role){const el=document.createElement('div');el.className='msg '+role;el.textContent=text;chat.appendChild(el);el.scrollIntoView({behavior:'smooth',block:'end'});}
fetch('/api/status').then(r=>r.json()).then(x=>document.querySelector('#status').textContent=x.status).catch(()=>document.querySelector('#status').textContent='Offline');
form.addEventListener('submit',async e=>{e.preventDefault();const text=prompt.value.trim();if(!text)return;add(text,'user');prompt.value='';send.disabled=true;try{const r=await fetch('/api/chat',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({message:text})});const x=await r.json();add(x.response||x.error||'No response','assistant');}catch(err){add('Connection error: '+err,'assistant')}finally{send.disabled=false;prompt.focus();}});
prompt.addEventListener('keydown',e=>{if(e.key==='Enter'&&!e.shiftKey){e.preventDefault();form.requestSubmit();}});
</script></body></html>"""


class WebRuntime:
    def __init__(self) -> None:
        self.config = load_runtime_config()
        self.memory = MemoryStore()
        self.logger = configure_logging()
        self.agent = SophyaneAgent(create_provider(self.config), self.memory, self.logger)
        self.lock = threading.Lock()

    def chat(self, message: str) -> str:
        with self.lock:
            response = self.agent.ask(message)
            return response.text

    def status(self) -> str:
        return show_status(self.config).replace("\n", " · ")


class Handler(BaseHTTPRequestHandler):
    runtime: WebRuntime

    def _send(self, body: bytes, content_type: str, status: int = 200) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, data: dict[str, Any], status: int = 200) -> None:
        self._send(json.dumps(data).encode(), "application/json; charset=utf-8", status)

    def do_GET(self) -> None:  # noqa: N802
        if self.path == "/":
            self._send(HTML.encode(), "text/html; charset=utf-8")
        elif self.path == "/api/status":
            self._json({"version": __version__, "status": self.runtime.status()})
        else:
            self._json({"error": "Not found"}, HTTPStatus.NOT_FOUND)

    def do_POST(self) -> None:  # noqa: N802
        if self.path != "/api/chat":
            self._json({"error": "Not found"}, HTTPStatus.NOT_FOUND)
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length <= 0 or length > 1_000_000:
                raise ValueError("Invalid request size")
            payload = json.loads(self.rfile.read(length))
            message = str(payload.get("message", "")).strip()
            if not message:
                raise ValueError("Message is required")
            self._json({"response": self.runtime.chat(message)})
        except (ValueError, json.JSONDecodeError) as error:
            self._json({"error": str(error)}, HTTPStatus.BAD_REQUEST)
        except Exception as error:  # keep server responsive
            self.runtime.logger.exception("Web request failed")
            self._json({"error": f"Sophyane error: {error}"}, HTTPStatus.INTERNAL_SERVER_ERROR)

    def log_message(self, format: str, *args: Any) -> None:
        self.runtime.logger.info("web: " + format, *args)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run Sophyane's browser interface")
    parser.add_argument("--host", default="127.0.0.1", help="127.0.0.1 locally; 0.0.0.0 for LAN/mobile access")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()

    Handler.runtime = WebRuntime()
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    local_url = f"http://127.0.0.1:{args.port}"
    print(f"Sophyane Web {__version__}: {local_url}")
    if args.host == "0.0.0.0":
        print("Mobile access: open this host's LAN IP on the same port. Do not expose it directly to the public internet.")
    if not args.no_browser:
        threading.Timer(0.8, lambda: webbrowser.open(local_url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping Sophyane Web.")
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
