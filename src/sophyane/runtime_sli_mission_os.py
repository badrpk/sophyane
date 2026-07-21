"""SLI Mission OS v1: deterministic decomposition for multi-service requests.

Complex requests are compiled into a persistent dependency graph before any provider
is asked to generate an artifact. Each node owns a workspace, capabilities, state,
validation contract and explicit prerequisites. External services remain blocked until
credentials/consent are supplied; the LLM cannot silently perform account actions.
"""
from __future__ import annotations

import hashlib
import json
import re
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class MissionNode:
    node_id: str
    title: str
    builder: str
    capabilities: tuple[str, ...]
    depends_on: tuple[str, ...] = ()
    state: str = "READY"
    blocked_reason: str = ""


@dataclass(frozen=True)
class MissionPlan:
    mission_id: str
    objective: str
    nodes: tuple[MissionNode, ...]
    confidence: float


_GROUPS = {
    "browser_game": ("game", "chess", "browser", "html5"),
    "local_ai": ("local llm", "local intelligence", "local model", "gguf"),
    "cloud_ai": ("gemini", "cloud intelligence", "cloud llm"),
    "recording": ("record", "recorded", "video", "capture"),
    "youtube": ("youtube", "upload"),
    "analytics": ("views", "analytics", "performance", "earning", "revenue"),
    "notifications": ("notification", "notify", "phone"),
    "schedule": ("every hour", "hourly", "each hour"),
}


def _present(text: str, group: str) -> bool:
    return any(marker in text for marker in _GROUPS[group])


def is_mission_request(request: str) -> bool:
    text = " ".join(str(request or "").lower().split())
    groups = {name for name in _GROUPS if _present(text, name)}
    # Mission mode is reserved for requests spanning independent runtimes/services.
    return len(groups) >= 4 and ("browser_game" in groups or "youtube" in groups)


def compile_mission(request: str) -> MissionPlan:
    objective = " ".join(str(request or "").strip().split())
    digest = hashlib.sha256(objective.encode("utf-8")).hexdigest()[:12]
    nodes: list[MissionNode] = []

    def add(node_id: str, title: str, builder: str, caps: tuple[str, ...],
            deps: tuple[str, ...] = (), state: str = "READY", reason: str = "") -> None:
        nodes.append(MissionNode(node_id, title, builder, caps, deps, state, reason))

    add("chess_ui", "Browser chess interface", "GAME_CHESS_BROWSER",
        ("html", "css", "javascript", "chess_rules", "responsive_ui"))
    add("arbiter", "Deterministic chess arbiter", "CHESS_ARBITER",
        ("legal_move_validation", "game_state", "pgn"), ("chess_ui",))

    if _present(objective.lower(), "local_ai"):
        add("local_ai", "Local LLM chess adapter", "LOCAL_LLM_ADAPTER",
            ("local_inference", "move_protocol", "timeout_fallback"), ("arbiter",))
    if _present(objective.lower(), "cloud_ai"):
        add("gemini_ai", "Gemini chess adapter", "GEMINI_ADAPTER",
            ("cloud_inference", "move_protocol", "rate_limit"), ("arbiter",),
            "BLOCKED", "Gemini credentials and explicit API consent required")

    players = tuple(x for x in ("local_ai", "gemini_ai") if any(n.node_id == x for n in nodes))
    add("match_controller", "Continuous match controller", "CHESS_MATCH_CONTROLLER",
        ("turn_control", "termination", "recovery"), ("arbiter",) + players)

    if _present(objective.lower(), "recording"):
        add("recorder", "Match recorder", "BROWSER_MEDIA_RECORDER",
            ("canvas_capture", "media_recorder", "artifact_storage"), ("match_controller",))
        add("encoder", "Video finalizer", "VIDEO_FINALIZER",
            ("webm", "metadata", "integrity_check"), ("recorder",))
    if _present(objective.lower(), "youtube"):
        upload_dep = ("encoder",) if any(n.node_id == "encoder" for n in nodes) else ("match_controller",)
        add("youtube", "YouTube publisher", "YOUTUBE_OAUTH_PUBLISHER",
            ("oauth2", "youtube_data_api", "resumable_upload"), upload_dep,
            "BLOCKED", "YouTube OAuth consent and channel authorization required")
    if _present(objective.lower(), "analytics"):
        add("analytics", "YouTube analytics collector", "YOUTUBE_ANALYTICS",
            ("views", "watch_time", "revenue_when_available"), ("youtube",),
            "BLOCKED", "YouTube Analytics authorization required")
    if _present(objective.lower(), "notifications"):
        deps = ("analytics",) if any(n.node_id == "analytics" for n in nodes) else ("match_controller",)
        add("notifications", "Phone performance notifications", "ANDROID_NOTIFICATION_WORKER",
            ("android_notifications", "summary_payload", "user_controls"), deps)
    if _present(objective.lower(), "schedule"):
        deps = ("notifications",) if any(n.node_id == "notifications" for n in nodes) else ("analytics",)
        add("hourly_scheduler", "Hourly reporting scheduler", "MISSION_SCHEDULER",
            ("hourly_schedule", "checkpoint", "retry_policy"), deps)

    return MissionPlan(f"mission-{digest}", objective, tuple(nodes), 0.97)


def _browser_files() -> dict[str, str]:
    return {
        "projects/chess_ui/index.html": """<!doctype html><html lang=\"en\"><meta charset=\"utf-8\"><meta name=\"viewport\" content=\"width=device-width,initial-scale=1\"><title>SLI Chess Mission</title><style>body{margin:0;font-family:system-ui;background:#111;color:#eee;display:grid;min-height:100vh;place-items:center}.app{width:min(94vw,720px)}#board{display:grid;grid-template-columns:repeat(8,1fr);aspect-ratio:1;border:2px solid #777}.sq{display:grid;place-items:center;font-size:clamp(22px,7vw,52px)}.sq:nth-child(16n+1),.sq:nth-child(16n+3),.sq:nth-child(16n+5),.sq:nth-child(16n+7),.sq:nth-child(16n+10),.sq:nth-child(16n+12),.sq:nth-child(16n+14),.sq:nth-child(16n+16){background:#ddd;color:#111}.sq{background:#555}button{min-height:48px;margin-top:12px;width:100%;font-size:1rem}</style><main class=\"app\"><h1>SLI Chess Mission</h1><p id=\"status\">Mission scaffold ready. AI adapters are isolated services.</p><div id=\"board\" aria-label=\"Chess board\"></div><button id=\"restart\">Restart match</button></main><script>const pieces=[...'♜♞♝♛♚♝♞♜♟♟♟♟♟♟♟♟',...Array(32).fill(''),...'♙♙♙♙♙♙♙♙♖♘♗♕♔♗♘♖'];const board=document.querySelector('#board');function draw(){board.innerHTML='';pieces.forEach((p,i)=>{const s=document.createElement('div');s.className='sq';s.textContent=p;s.setAttribute('aria-label',`square ${i+1}`);board.appendChild(s)})}document.querySelector('#restart').onclick=()=>{draw();document.querySelector('#status').textContent='Match reset; waiting for configured AI workers.'};draw();</script></html>""",
        "projects/shared/move-protocol.json": json.dumps({
            "version": 1,
            "request": {"fen": "string", "legal_moves": ["uci"], "deadline_ms": 15000},
            "response": {"move": "uci", "explanation": "optional", "worker": "local|gemini"},
        }, indent=2) + "\n",
    }


def materialize(plan: MissionPlan, workspace: Path) -> list[str]:
    root = workspace / plan.mission_id
    root.mkdir(parents=True, exist_ok=True)
    files = _browser_files()
    evidence: list[str] = []
    for relative, content in files.items():
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        evidence.append(f"- wrote {target.relative_to(workspace)}")

    for node in plan.nodes:
        node_dir = root / "projects" / node.node_id
        node_dir.mkdir(parents=True, exist_ok=True)
        manifest = {**asdict(node), "updated_at": time.time(), "attempts": 0}
        (node_dir / "node.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        if not (node_dir / "README.md").exists():
            (node_dir / "README.md").write_text(
                f"# {node.title}\n\nBuilder: `{node.builder}`\n\nState: `{node.state}`\n\n"
                f"Capabilities: {', '.join(node.capabilities)}\n\nDependencies: {', '.join(node.depends_on) or 'none'}\n"
                + (f"\nBlocked: {node.blocked_reason}\n" if node.blocked_reason else ""),
                encoding="utf-8",
            )
    ledger = {"schema": 1, "created_at": time.time(), **asdict(plan)}
    (root / "mission.json").write_text(json.dumps(ledger, indent=2), encoding="utf-8")
    (root / "events.jsonl").write_text(json.dumps({"ts": time.time(), "event": "MISSION_COMPILED", "mission_id": plan.mission_id}) + "\n", encoding="utf-8")
    evidence.extend((f"- mission ledger: {plan.mission_id}/mission.json", f"- nodes materialized: {len(plan.nodes)}"))
    return evidence


def install_sli_mission_os() -> None:
    from sophyane import adaptive_execution

    if getattr(adaptive_execution, "_sli_mission_os_installed", False):
        return
    original = adaptive_execution.run_adaptive_loop

    def run(*, initial_text: str, original_request: str, ask: Any, workspace: Path | None = None,
            max_steps: int = 12, progress: Any = None) -> str:
        if not is_mission_request(original_request):
            return original(initial_text=initial_text, original_request=original_request, ask=ask,
                            workspace=workspace, max_steps=max_steps, progress=progress)
        workspace_path = (workspace or Path.cwd()).resolve()
        progress = progress or (lambda _message: None)
        plan = compile_mission(original_request)
        blocked = sum(1 for node in plan.nodes if node.state == "BLOCKED")
        progress(f"SLI Mission OS: {plan.mission_id} / {len(plan.nodes)} nodes / {blocked} permission-gated")
        evidence = materialize(plan, workspace_path)
        ready = [node.node_id for node in plan.nodes if node.state == "READY"]
        return (
            f"SLI compiled a multi-project mission instead of requesting one giant provider artifact.\n\n"
            f"Mission: {plan.mission_id}\nWorkspace: {workspace_path / plan.mission_id}\n"
            f"Nodes: {len(plan.nodes)} ({blocked} blocked until explicit credentials/consent)\n"
            f"Ready nodes: {', '.join(ready)}\n\nExecution evidence:\n" + "\n".join(evidence)
        )

    adaptive_execution.run_adaptive_loop = run
    adaptive_execution._sli_mission_os_installed = True
