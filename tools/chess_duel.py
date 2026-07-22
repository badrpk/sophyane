#!/usr/bin/env python3
"""Browser chess arena: local Llama 3B versus Gemini."""

from __future__ import annotations

import html
import json
import os
import random
import re
import subprocess
import threading
import time
import urllib.error
import urllib.request
import webbrowser
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import chess


HOST = os.environ.get("SOPHYANE_CHESS_HOST", "127.0.0.1")
PORT = int(os.environ.get("SOPHYANE_CHESS_PORT", "8788"))

LOCAL_OPENAI_URL = os.environ.get(
    "SOPHYANE_CHESS_LOCAL_URL",
    "http://127.0.0.1:8766/v1/chat/completions",
)
OLLAMA_URL = os.environ.get(
    "SOPHYANE_CHESS_OLLAMA_URL",
    "http://127.0.0.1:11434/api/chat",
)
LOCAL_MODEL = os.environ.get(
    "SOPHYANE_CHESS_LOCAL_MODEL",
    "llama3.2:3b",
)
GEMINI_MODEL = os.environ.get(
    "SOPHYANE_CHESS_GEMINI_MODEL",
    "gemini-3.5-flash",
)
MOVE_DELAY = float(os.environ.get("SOPHYANE_CHESS_MOVE_DELAY", "1.4"))
REQUEST_TIMEOUT = int(os.environ.get("SOPHYANE_CHESS_TIMEOUT", "90"))
MAX_PLIES = int(os.environ.get("SOPHYANE_CHESS_MAX_PLIES", "240"))


def http_json(
    url: str,
    payload: dict[str, Any] | None = None,
    *,
    headers: dict[str, str] | None = None,
    timeout: int = REQUEST_TIMEOUT,
) -> dict[str, Any]:
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json", **(headers or {})},
        method="GET" if payload is None else "POST",
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def recursively_find_api_key(value: Any) -> str:
    if isinstance(value, dict):
        preferred = (
            "gemini_api_key",
            "google_api_key",
            "api_key",
            "apikey",
            "key",
        )
        for key in preferred:
            candidate = value.get(key)
            if isinstance(candidate, str) and candidate.startswith("AIza"):
                return candidate
        for key, child in value.items():
            if "gemini" in str(key).lower() or "google" in str(key).lower():
                found = recursively_find_api_key(child)
                if found:
                    return found
        for child in value.values():
            found = recursively_find_api_key(child)
            if found:
                return found
    elif isinstance(value, list):
        for child in value:
            found = recursively_find_api_key(child)
            if found:
                return found
    elif isinstance(value, str) and value.startswith("AIza"):
        return value
    return ""


def gemini_api_key() -> str:
    for env_name in ("GEMINI_API_KEY", "GOOGLE_API_KEY"):
        value = os.environ.get(env_name, "").strip()
        if value:
            return value

    config_path = Path.home() / ".config" / "sophyane" / "config.json"
    try:
        config = json.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return ""
    return recursively_find_api_key(config)


def extract_move(text: str, legal_moves: set[str]) -> str | None:
    cleaned = text.strip().lower()

    # Direct answer.
    for token in re.findall(r"\b[a-h][1-8][a-h][1-8][qrbn]?\b", cleaned):
        if token in legal_moves:
            return token

    # JSON-shaped response.
    try:
        obj = json.loads(text)
        if isinstance(obj, dict):
            for key in ("move", "uci", "best_move"):
                candidate = str(obj.get(key, "")).lower().strip()
                if candidate in legal_moves:
                    return candidate
    except json.JSONDecodeError:
        pass

    return None


def chess_prompt(board: chess.Board, agent_name: str) -> str:
    legal = [move.uci() for move in board.legal_moves]
    history = " ".join(move.uci() for move in board.move_stack[-16:]) or "(none)"

    return f"""You are {agent_name}, playing a legal chess game.

Position FEN:
{board.fen()}

Your colour:
{"White" if board.turn == chess.WHITE else "Black"}

Recent moves:
{history}

Legal UCI moves:
{" ".join(legal)}

Choose one strong legal move.

Return exactly one UCI move from the supplied legal-move list.
Do not return prose, Markdown, SAN notation, analysis, or multiple moves.
Example format: e2e4
"""


class AgentError(RuntimeError):
    pass


class ExpertRulesAgent:
    name = "Expert Rules Engine"

    @staticmethod
    def _score_move(board: chess.Board, move: chess.Move) -> float:
        score = 0.0

        piece_values = {
            chess.PAWN: 1.0,
            chess.KNIGHT: 3.2,
            chess.BISHOP: 3.3,
            chess.ROOK: 5.0,
            chess.QUEEN: 9.0,
            chess.KING: 0.0,
        }

        if board.is_capture(move):
            victim = board.piece_at(move.to_square)
            attacker = board.piece_at(move.from_square)
            if victim:
                score += 10.0 * piece_values[victim.piece_type]
            if attacker:
                score -= piece_values[attacker.piece_type]

        if move.promotion:
            score += piece_values.get(move.promotion, 0.0) + 6.0

        if board.gives_check(move):
            score += 3.0

        center = {
            chess.D4, chess.E4, chess.D5, chess.E5,
            chess.C3, chess.D3, chess.E3, chess.F3,
            chess.C4, chess.F4, chess.C5, chess.F5,
            chess.C6, chess.D6, chess.E6, chess.F6,
        }
        if move.to_square in center:
            score += 1.2

        moving_piece = board.piece_at(move.from_square)
        if moving_piece:
            if moving_piece.piece_type in (chess.KNIGHT, chess.BISHOP):
                home_rank = 0 if moving_piece.color == chess.WHITE else 7
                if chess.square_rank(move.from_square) == home_rank:
                    score += 1.0

            if moving_piece.piece_type == chess.KING and board.is_castling(move):
                score += 5.0

            if moving_piece.piece_type == chess.QUEEN and len(board.move_stack) < 12:
                score -= 1.2

        probe = board.copy(stack=False)
        probe.push(move)

        if probe.is_checkmate():
            score += 100000.0
        elif probe.is_stalemate():
            score -= 10.0

        opponent_replies = list(probe.legal_moves)
        if opponent_replies:
            worst_reply = 0.0
            for reply in opponent_replies:
                if probe.is_capture(reply):
                    victim = probe.piece_at(reply.to_square)
                    if victim:
                        worst_reply = max(
                            worst_reply,
                            piece_values[victim.piece_type],
                        )
            score -= 0.45 * worst_reply

        score += random.random() * 0.05
        return score

    def generate(self, prompt: str) -> tuple[str, str]:
        raise AgentError("ExpertRulesAgent does not use text generation")

    def choose(self, board: chess.Board) -> tuple[chess.Move, str, str, bool]:
        legal_moves = list(board.legal_moves)
        if not legal_moves:
            raise AgentError("No legal moves available")

        best = max(legal_moves, key=lambda m: self._score_move(board, m))
        explanation = (
            "Selected by deterministic chess heuristics: captures, checks, "
            "development, centre control, castling, promotion, and mate."
        )
        return best, explanation, "expert-rules-v1", False


class GeminiAgent:
    name = "Gemini 3.5 Flash"

    def generate(self, prompt: str) -> tuple[str, str]:
        key = gemini_api_key()
        if not key:
            raise AgentError(
                "Gemini API key not found. Set GEMINI_API_KEY or configure "
                "Gemini through sophyane --setup."
            )

        model = GEMINI_MODEL.strip().lower().replace(" ", "-")
        url = (
            "https://generativelanguage.googleapis.com/v1beta/models/"
            f"{model}:generateContent?key={key}"
        )
        payload = {
            "systemInstruction": {
                "parts": [
                    {
                        "text": (
                            "You select chess moves. Return only one legal UCI "
                            "move from the user's supplied list."
                        )
                    }
                ]
            },
            "contents": [
                {
                    "role": "user",
                    "parts": [{"text": prompt}],
                }
            ],
            "generationConfig": {
                "temperature": 0.25,
                "maxOutputTokens": 20,
            },
        }

        result = http_json(url, payload)
        candidates = result.get("candidates") or []
        if not candidates:
            raise AgentError(f"No Gemini candidate returned: {result}")

        parts = (
            candidates[0]
            .get("content", {})
            .get("parts", [])
        )
        text = "".join(str(part.get("text", "")) for part in parts)
        return text, model


@dataclass
class ArenaState:
    board: chess.Board = field(default_factory=chess.Board)
    running: bool = False
    thinking: bool = False
    status: str = "Ready"
    error: str = ""
    winner: str = ""
    last_move: str = ""
    last_backend: str = ""
    white_fallbacks: int = 0
    black_fallbacks: int = 0
    moves: list[dict[str, Any]] = field(default_factory=list)
    generation: int = 0

    def reset(self) -> None:
        self.board.reset()
        self.running = False
        self.thinking = False
        self.status = "Ready"
        self.error = ""
        self.winner = ""
        self.last_move = ""
        self.last_backend = ""
        self.white_fallbacks = 0
        self.black_fallbacks = 0
        self.moves.clear()
        self.generation += 1

    def snapshot(self) -> dict[str, Any]:
        outcome = self.board.outcome(claim_draw=True)
        return {
            "fen": self.board.fen(),
            "turn": "white" if self.board.turn else "black",
            "running": self.running,
            "thinking": self.thinking,
            "status": self.status,
            "error": self.error,
            "winner": self.winner,
            "last_move": self.last_move,
            "last_backend": self.last_backend,
            "white_fallbacks": self.white_fallbacks,
            "black_fallbacks": self.black_fallbacks,
            "moves": list(self.moves),
            "game_over": outcome is not None,
            "result": self.board.result(claim_draw=True) if outcome else "*",
            "legal_count": self.board.legal_moves.count(),
            "fullmove": self.board.fullmove_number,
            "local_model": LOCAL_MODEL,
            "gemini_model": GEMINI_MODEL,
        }


STATE = ArenaState()
LOCK = threading.RLock()
WHITE_AGENT = ExpertRulesAgent()
BLACK_AGENT = GeminiAgent()


def finish_game_locked() -> None:
    outcome = STATE.board.outcome(claim_draw=True)
    if not outcome:
        return

    STATE.running = False
    STATE.thinking = False
    STATE.status = "Game finished"
    result = STATE.board.result(claim_draw=True)

    if result == "1-0":
        STATE.winner = "Expert Rules Engine wins"
    elif result == "0-1":
        STATE.winner = "Gemini 3.5 Flash wins"
    else:
        STATE.winner = f"Draw: {outcome.termination.name.replace('_', ' ').title()}"


def choose_move(
    board: chess.Board,
    agent: ExpertRulesAgent | GeminiAgent,
) -> tuple[chess.Move, str, str, bool]:
    legal_moves = list(board.legal_moves)
    legal_uci = {move.uci() for move in legal_moves}
    prompt = chess_prompt(board, agent.name)
    last_error = ""

    if isinstance(agent, ExpertRulesAgent):
        return agent.choose(board)

    for _attempt in range(2):
        try:
            raw, backend = agent.generate(prompt)
            chosen = extract_move(raw, legal_uci)
            if chosen:
                return chess.Move.from_uci(chosen), raw.strip(), backend, False
            last_error = f"Invalid response: {raw[:160]!r}"
        except Exception as error:  # noqa: BLE001
            last_error = str(error)

        prompt += (
            "\nYour prior response was invalid. Return exactly one move from "
            "the legal UCI list."
        )

    # Keep the visible match progressing while clearly recording that the AI
    # failed to provide a valid move.
    fallback = random.choice(legal_moves)
    return fallback, last_error, "legal-random-fallback", True


def game_loop(generation: int) -> None:
    while True:
        with LOCK:
            if generation != STATE.generation or not STATE.running:
                STATE.thinking = False
                return

            if STATE.board.is_game_over(claim_draw=True):
                finish_game_locked()
                return

            if len(STATE.board.move_stack) >= MAX_PLIES:
                STATE.running = False
                STATE.thinking = False
                STATE.status = "Stopped at maximum move limit"
                STATE.winner = "Draw by configured move limit"
                return

            board_copy = STATE.board.copy(stack=True)
            is_white = board_copy.turn == chess.WHITE
            agent = WHITE_AGENT if is_white else BLACK_AGENT
            STATE.thinking = True
            STATE.error = ""
            STATE.status = f"{agent.name} is thinking"

        started = time.perf_counter()

        try:
            move, raw, backend, fallback = choose_move(board_copy, agent)
            elapsed = round(time.perf_counter() - started, 2)
        except Exception as error:  # noqa: BLE001
            with LOCK:
                STATE.running = False
                STATE.thinking = False
                STATE.status = "Agent failure"
                STATE.error = str(error)
            return

        with LOCK:
            if generation != STATE.generation or not STATE.running:
                STATE.thinking = False
                return

            # Position may only be changed by this game thread.
            if move not in STATE.board.legal_moves:
                STATE.running = False
                STATE.thinking = False
                STATE.status = "Internal move validation failure"
                STATE.error = f"Rejected illegal move: {move.uci()}"
                return

            san = STATE.board.san(move)
            ply = len(STATE.board.move_stack) + 1
            STATE.board.push(move)

            if fallback:
                if is_white:
                    STATE.white_fallbacks += 1
                else:
                    STATE.black_fallbacks += 1

            STATE.last_move = move.uci()
            STATE.last_backend = backend
            STATE.moves.append(
                {
                    "ply": ply,
                    "agent": agent.name,
                    "colour": "White" if is_white else "Black",
                    "uci": move.uci(),
                    "san": san,
                    "seconds": elapsed,
                    "backend": backend,
                    "fallback": fallback,
                    "response": raw[:240],
                }
            )
            STATE.thinking = False
            STATE.status = f"{agent.name} played {san}"

            if STATE.board.is_game_over(claim_draw=True):
                finish_game_locked()
                return

        time.sleep(MOVE_DELAY)


INDEX_HTML = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<title>Sophyane AI Chess Arena</title>
<style>
:root {
  color-scheme: dark;
  --bg:#0b1020;
  --panel:#151c31;
  --soft:#202a45;
  --text:#edf2ff;
  --muted:#9aa8c7;
  --accent:#69d2a7;
  --danger:#ff7a8a;
  --light:#d8c6a5;
  --dark:#735541;
}
*{box-sizing:border-box}
body{
  margin:0;
  min-height:100vh;
  font-family:system-ui,-apple-system,Segoe UI,sans-serif;
  background:radial-gradient(circle at top,#18233f,var(--bg) 55%);
  color:var(--text);
}
header{
  padding:18px 18px 8px;
  text-align:center;
}
h1{margin:0;font-size:clamp(1.45rem,5vw,2.4rem)}
.subtitle{color:var(--muted);margin-top:7px}
.layout{
  width:min(1180px,100%);
  margin:auto;
  padding:14px;
  display:grid;
  grid-template-columns:minmax(290px,680px) minmax(280px,1fr);
  gap:16px;
}
.card{
  background:rgba(21,28,49,.94);
  border:1px solid #293453;
  border-radius:18px;
  box-shadow:0 18px 45px #0007;
  overflow:hidden;
}
.players{
  display:grid;
  grid-template-columns:1fr 1fr;
  gap:10px;
  margin-bottom:12px;
}
.player{
  padding:12px;
  border-radius:14px;
  background:var(--panel);
  border:1px solid #2a3657;
}
.player.active{
  outline:2px solid var(--accent);
  box-shadow:0 0 24px #69d2a744;
}
.player strong{display:block;font-size:1.02rem}
.player small{color:var(--muted)}
.board-wrap{padding:14px}
#board{
  width:100%;
  max-width:680px;
  aspect-ratio:1;
  margin:auto;
  display:grid;
  grid-template-columns:repeat(8,1fr);
  border:6px solid #30261f;
  border-radius:10px;
  overflow:hidden;
}
.square{
  border:0;
  padding:0;
  display:grid;
  place-items:center;
  font-size:clamp(28px,8vw,64px);
  line-height:1;
  user-select:none;
}
.square.light{background:var(--light)}
.square.dark{background:var(--dark)}
.square.last{box-shadow:inset 0 0 0 5px #f6dc5d}
.controls{
  display:grid;
  grid-template-columns:repeat(3,1fr);
  gap:9px;
  padding:0 14px 14px;
}
button.action{
  border:0;
  min-height:48px;
  border-radius:12px;
  font-weight:800;
  font-size:1rem;
  background:var(--accent);
  color:#08150f;
}
button.secondary{background:#364262;color:var(--text)}
button.danger{background:var(--danger);color:#25070b}
.side{padding:14px}
.status{
  min-height:62px;
  padding:12px;
  border-radius:13px;
  background:var(--soft);
  margin-bottom:12px;
}
#error{color:var(--danger);white-space:pre-wrap}
.stats{
  display:grid;
  grid-template-columns:1fr 1fr;
  gap:8px;
  margin-bottom:12px;
}
.stat{background:#10172a;padding:10px;border-radius:10px}
.stat small{display:block;color:var(--muted)}
.moves{
  max-height:55vh;
  overflow:auto;
  border-radius:12px;
  background:#0e1527;
}
.move{
  display:grid;
  grid-template-columns:42px 1fr auto;
  gap:8px;
  padding:9px 10px;
  border-bottom:1px solid #202a45;
  font-size:.92rem;
}
.move small{color:var(--muted)}
.fallback{color:#ffd36a}
@media(max-width:820px){
  .layout{grid-template-columns:1fr}
  .moves{max-height:36vh}
}
</style>
</head>
<body>
<header>
  <h1>♟ Sophyane AI Chess Arena</h1>
  <div class="subtitle">Expert Rules Engine vs Gemini 3.5 Flash</div>
</header>

<main class="layout">
  <section>
    <div class="players">
      <div class="player" id="whitePlayer">
        <strong>♔ Expert Rules Engine</strong>
        <small>White · deterministic local engine</small>
      </div>
      <div class="player" id="blackPlayer">
        <strong>♚ Gemini 3.5 Flash</strong>
        <small>Black · Google cloud</small>
      </div>
    </div>

    <div class="card">
      <div class="board-wrap"><div id="board"></div></div>
      <div class="controls">
        <button class="action" onclick="command('/api/start')">Start</button>
        <button class="action secondary" onclick="command('/api/pause')">Pause</button>
        <button class="action danger" onclick="command('/api/reset')">Reset</button>
      </div>
    </div>
  </section>

  <aside class="card side">
    <div class="status">
      <strong id="status">Loading…</strong>
      <div id="winner"></div>
      <div id="error"></div>
    </div>

    <div class="stats">
      <div class="stat"><small>Move</small><strong id="moveNumber">—</strong></div>
      <div class="stat"><small>Last move</small><strong id="lastMove">—</strong></div>
      <div class="stat"><small>Expert fallbacks</small><strong id="wf">0</strong></div>
      <div class="stat"><small>Gemini fallbacks</small><strong id="bf">0</strong></div>
    </div>

    <h3>Move history</h3>
    <div class="moves" id="moves"></div>
  </aside>
</main>

<script>
const pieces = {
  p:"♟",r:"♜",n:"♞",b:"♝",q:"♛",k:"♚",
  P:"♙",R:"♖",N:"♘",B:"♗",Q:"♕",K:"♔"
};

function fenBoard(fen){
  const rows = fen.split(" ")[0].split("/");
  const cells = [];
  for(const row of rows){
    for(const ch of row){
      if(/[1-8]/.test(ch)){
        for(let i=0;i<Number(ch);i++) cells.push("");
      } else cells.push(ch);
    }
  }
  return cells;
}

function lastSquares(uci){
  if(!uci || uci.length < 4) return new Set();
  const squareIndex = sq => {
    const file = sq.charCodeAt(0)-97;
    const rank = Number(sq[1]);
    return (8-rank)*8+file;
  };
  return new Set([squareIndex(uci.slice(0,2)),squareIndex(uci.slice(2,4))]);
}

function renderBoard(state){
  const board = document.getElementById("board");
  const cells = fenBoard(state.fen);
  const marked = lastSquares(state.last_move);
  board.innerHTML = "";
  cells.forEach((piece,i)=>{
    const rank = Math.floor(i/8);
    const file = i%8;
    const sq = document.createElement("div");
    sq.className = "square " + ((rank+file)%2 ? "dark":"light");
    if(marked.has(i)) sq.classList.add("last");
    sq.textContent = pieces[piece] || "";
    board.appendChild(sq);
  });
}

function escapeHtml(value){
  const d=document.createElement("div");
  d.textContent=String(value ?? "");
  return d.innerHTML;
}

function render(state){
  renderBoard(state);

  document.getElementById("status").textContent = state.status;
  document.getElementById("winner").textContent = state.winner || "";
  document.getElementById("error").textContent = state.error || "";
  document.getElementById("moveNumber").textContent = state.fullmove;
  document.getElementById("lastMove").textContent = state.last_move || "—";
  document.getElementById("wf").textContent = state.white_fallbacks;
  document.getElementById("bf").textContent = state.black_fallbacks;

  document.getElementById("whitePlayer").classList.toggle(
    "active", state.turn === "white" && !state.game_over
  );
  document.getElementById("blackPlayer").classList.toggle(
    "active", state.turn === "black" && !state.game_over
  );

  const moves = [...state.moves].reverse();
  document.getElementById("moves").innerHTML = moves.map(m => `
    <div class="move">
      <strong>${m.ply}</strong>
      <span>
        ${escapeHtml(m.agent)}:
        <strong>${escapeHtml(m.san)}</strong>
        ${m.fallback ? '<span class="fallback"> fallback</span>' : ''}
        <br><small>${escapeHtml(m.backend)} · ${m.seconds}s</small>
      </span>
      <code>${escapeHtml(m.uci)}</code>
    </div>
  `).join("") || '<div class="move">No moves yet</div>';
}

async function command(path){
  try{
    const response = await fetch(path,{method:"POST"});
    render(await response.json());
  }catch(error){
    document.getElementById("error").textContent=String(error);
  }
}

async function refresh(){
  try{
    const response = await fetch("/api/state",{cache:"no-store"});
    render(await response.json());
  }catch(error){
    document.getElementById("error").textContent=String(error);
  }
}
refresh();
setInterval(refresh,700);
</script>
</body>
</html>
"""


class Handler(BaseHTTPRequestHandler):
    server_version = "SophyaneChess/1.0"

    def log_message(self, fmt: str, *args: Any) -> None:
        print(f"[chess] {self.address_string()} {fmt % args}")

    def send_bytes(
        self,
        body: bytes,
        content_type: str,
        status: int = 200,
    ) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def send_json(self, value: Any, status: int = 200) -> None:
        self.send_bytes(
            json.dumps(value).encode("utf-8"),
            "application/json; charset=utf-8",
            status,
        )

    def do_GET(self) -> None:
        if self.path == "/" or self.path.startswith("/index"):
            self.send_bytes(
                INDEX_HTML.encode("utf-8"),
                "text/html; charset=utf-8",
            )
            return

        if self.path == "/api/state":
            with LOCK:
                self.send_json(STATE.snapshot())
            return

        self.send_json({"error": "Not found"}, 404)

    def do_POST(self) -> None:
        if self.path == "/api/start":
            with LOCK:
                if STATE.board.is_game_over(claim_draw=True):
                    STATE.reset()
                if not STATE.running:
                    STATE.running = True
                    STATE.error = ""
                    STATE.status = "Game started"
                    generation = STATE.generation
                    threading.Thread(
                        target=game_loop,
                        args=(generation,),
                        daemon=True,
                    ).start()
                self.send_json(STATE.snapshot())
            return

        if self.path == "/api/pause":
            with LOCK:
                STATE.running = False
                STATE.thinking = False
                STATE.status = "Paused"
                self.send_json(STATE.snapshot())
            return

        if self.path == "/api/reset":
            with LOCK:
                STATE.reset()
                self.send_json(STATE.snapshot())
            return

        self.send_json({"error": "Not found"}, 404)


def open_browser(url: str) -> None:
    try:
        if shutil_which("termux-open-url"):
            subprocess.Popen(
                ["termux-open-url", url],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            return
        webbrowser.open(url)
    except Exception as error:  # noqa: BLE001
        print(f"Open this URL manually: {url} ({error})")


def shutil_which(command: str) -> str | None:
    from shutil import which

    return which(command)


def main() -> int:
    url = f"http://{HOST}:{PORT}"
    print("Sophyane AI Chess Arena")
    print("========================")
    print(f"White: Expert Rules Engine ({LOCAL_MODEL})")
    print(f"Black: Gemini ({GEMINI_MODEL})")
    print(f"Browser: {url}")
    print()
    print("Local backend order:")
    print(f"  1. {LOCAL_OPENAI_URL}")
    print(f"  2. {OLLAMA_URL}")
    print()
    print("Press Ctrl+C to stop.")

    server = ThreadingHTTPServer((HOST, PORT), Handler)
    threading.Timer(1.0, open_browser, args=(url,)).start()

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping chess arena.")
    finally:
        server.server_close()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
