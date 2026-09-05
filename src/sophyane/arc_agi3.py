"""ARC-AGI-3 adapter with durable, experience-driven game memory."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable, Iterable

DEFAULT_STATE_ROOT = Path.home() / ".local/share/sophyane/arc_agi3"


@dataclass(frozen=True)
class ArcDecision:
    action: str
    data: dict[str, int]
    hypothesis: str = ""
    notes: str = ""


@dataclass(frozen=True)
class ArcRunResult:
    game_id: str
    steps: int
    wins: int
    game_overs: int
    score: float | None
    scorecard_id: str | None
    trajectory: str
    status: str


def _jsonable(value: Any, depth: int = 0) -> Any:
    if depth > 5:
        return repr(value)[:500]
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, dict):
        return {str(k): _jsonable(v, depth + 1) for k, v in list(value.items())[:80]}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v, depth + 1) for v in value[:256]]
    if hasattr(value, "tolist"):
        return _jsonable(value.tolist(), depth + 1)
    if hasattr(value, "__dict__"):
        return {str(k): _jsonable(v, depth + 1) for k, v in vars(value).items() if not str(k).startswith("_")}
    return str(value)[:1000]


def observation_payload(observation: Any) -> dict[str, Any]:
    payload = _jsonable(observation)
    return payload if isinstance(payload, dict) else {"observation": payload}


def _action_name(action: Any) -> str:
    return str(getattr(action, "name", action)).split(".")[-1].upper()


def parse_decision(text: str, allowed_actions: Iterable[Any]) -> ArcDecision:
    names = {_action_name(action) for action in allowed_actions}
    match = re.search(r"\{[\s\S]*\}", text or "")
    if not match:
        raise ValueError("model did not return a JSON action")
    raw = json.loads(match.group(0))
    action = _action_name(raw.get("action", ""))
    if action not in names:
        raise ValueError(f"action {action!r} not in {sorted(names)}")
    data = raw.get("data") or {}
    if not isinstance(data, dict):
        raise ValueError("action data must be an object")
    clean = {key: max(0, min(63, int(data[key]))) for key in ("x", "y") if key in data}
    return ArcDecision(action, clean, str(raw.get("hypothesis", ""))[:1000], str(raw.get("notes", ""))[:2000])


class ArcRSIMemory:
    """Per-game hypotheses: benchmark-time learning, not weight updates."""
    def __init__(self, root: Path = DEFAULT_STATE_ROOT) -> None:
        self.root = Path(root)

    def game_dir(self, game_id: str) -> Path:
        path = self.root / re.sub(r"[^a-zA-Z0-9_-]", "_", game_id)
        path.mkdir(parents=True, exist_ok=True)
        return path

    def manual(self, game_id: str) -> str:
        path = self.game_dir(game_id) / "manual.md"
        return path.read_text(encoding="utf-8")[-8000:] if path.exists() else ""

    def update(self, game_id: str, decision: ArcDecision, outcome: str) -> None:
        lesson = decision.hypothesis or decision.notes
        if lesson:
            with (self.game_dir(game_id) / "manual.md").open("a", encoding="utf-8") as handle:
                handle.write(f"\n- {decision.action} ({outcome}): {lesson}\n")

    def record(self, game_id: str, event: dict[str, Any]) -> Path:
        path = self.game_dir(game_id) / "trajectory.jsonl"
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(event, ensure_ascii=False) + "\n")
        return path


class SophyaneArcAgent:
    SYSTEM = """You are Sophyane's ARC-AGI-3 interactive reasoning policy.
There are no instructions. Infer objects, controls, dynamics, goal and failure
conditions from state changes. Prefer informative reversible probes, then the
shortest reliable plan. Return exactly one JSON object:
{"action":"ACTION1","data":{},"hypothesis":"...","notes":"..."}
For coordinate actions use data {"x":0..63,"y":0..63}."""

    def __init__(self, generate: Callable[[str, str], str], memory: ArcRSIMemory, *, ecosystem: Any | None = None, provider_id: str = "configured") -> None:
        self.generate, self.memory = generate, memory
        self.ecosystem, self.provider_id = ecosystem, provider_id

    def decide(self, game_id: str, observation: Any, actions: Iterable[Any], step: int, *, evidence: Any | None = None) -> ArcDecision:
        choices = list(actions)
        recalls = self.ecosystem.recall(self.provider_id, game_id, evidence) if self.ecosystem is not None and evidence is not None else []
        from sophyane.badrpk_arc_catalog import bounded_catalog
        prompt = json.dumps({"game": game_id, "step": step, "allowed_actions": [_action_name(a) for a in choices], "observation": observation_payload(observation), "frame_evidence": asdict(evidence) if evidence is not None else None, "verified_same_game_recalls": recalls, "badrpk_ecosystem": bounded_catalog(), "learned_manual": self.memory.manual(game_id)}, ensure_ascii=False)
        return parse_decision(self.generate(prompt, self.SYSTEM), choices)


def _state_name(observation: Any) -> str:
    state = getattr(observation, "state", None)
    return str(getattr(state, "name", state or "UNKNOWN")).upper()


def _resolve_action(actions: Iterable[Any], name: str) -> Any:
    return next(action for action in actions if _action_name(action) == name)


def run_game(arcade: Any, game_id: str, agent: SophyaneArcAgent, *, max_steps: int = 200, reset_on_game_over: bool = True) -> ArcRunResult:
    env = arcade.make(game_id, render_mode=None, save_recording=True, include_frame_data=True)
    if env is None:
        raise RuntimeError(f"ARC toolkit could not create {game_id}")
    actions = list(env.action_space)
    observation = getattr(env, "observation_space", None)
    if observation is None:
        observation = env.reset()
        actions = list(env.action_space)
    wins = game_overs = step = 0
    trajectory = agent.memory.game_dir(game_id) / "trajectory.jsonl"
    for step in range(1, max_steps + 1):
        before = observation_payload(observation)
        before_evidence = agent.ecosystem.evidence(game_id, step, observation, before) if agent.ecosystem is not None else None
        decision = agent.decide(game_id, observation, actions, step, evidence=before_evidence)
        observation = env.step(
            _resolve_action(actions, decision.action),
            data=decision.data,
            reasoning={"hypothesis": decision.hypothesis, "notes": decision.notes},
        )
        state, changed = _state_name(observation), before != observation_payload(observation)
        after_evidence = agent.ecosystem.evidence(game_id, step, observation, observation_payload(observation)) if agent.ecosystem is not None else None
        if before_evidence is not None and after_evidence is not None:
            changed = after_evidence.changed
            agent.ecosystem.remember(agent.provider_id, game_id, before_evidence, decision.action, decision.data, after_evidence, state)
        agent.memory.update(game_id, decision, f"state={state}, changed={changed}")
        trajectory = agent.memory.record(game_id, {"time": time.time(), "step": step, "decision": asdict(decision), "state": state, "changed": changed})
        if state == "WIN":
            wins += 1
        elif state == "GAME_OVER":
            game_overs += 1
            if reset_on_game_over:
                observation = env.reset()
            else:
                break
        actions = list(env.action_space)
    scorecard = arcade.get_scorecard()
    score = getattr(scorecard, "score", None) if scorecard is not None else None
    scorecard_id = (
        getattr(scorecard, "scorecard_id", None)
        or getattr(scorecard, "card_id", None)
        or getattr(scorecard, "id", None)
        if scorecard is not None else None
    )
    return ArcRunResult(game_id, step, wins, game_overs, score, scorecard_id, str(trajectory), _state_name(observation))


def capability_rank(*, toolkit: bool, real_frames: bool, action_loop: bool, durable_learning: bool, measured_score: float | None = None) -> dict[str, Any]:
    readiness = sum([toolkit, real_frames, action_loop, durable_learning]) / 4
    tier = "incompatible" if readiness == 0 else "adapter-ready" if readiness < 1 else "evaluation-ready"
    return {"tier": "measured" if measured_score is not None else tier, "adapter_readiness": readiness, "rhae": measured_score, "claim": "empirical" if measured_score is not None else "unscored; run an official scorecard"}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run Sophyane on ARC-AGI-3")
    parser.add_argument("--game", default="ls20")
    parser.add_argument("--max-steps", type=int, default=200)
    parser.add_argument("--state-root", type=Path, default=DEFAULT_STATE_ROOT)
    parser.add_argument(
        "--provider", choices=("configured", "codex_cli"), default="configured",
        help="Use normal Sophyane provider selection or Mode 4 Codex CLI",
    )
    args = parser.parse_args(argv)
    try:
        import arc_agi
    except ImportError:
        parser.error("ARC toolkit missing; install Sophyane with the 'arc' extra")
    if args.provider == "codex_cli":
        from sophyane.providers.codex_cli import CodexCliProvider
        # Keep ARC reasoning context separate from repository-review sessions.
        # Codex requires a trusted git worktree. A game-specific child keeps
        # its persisted thread isolated while inheriting this repository's
        # trust boundary.
        run_key = hashlib.sha256(str(args.state_root.resolve()).encode()).hexdigest()[:12]
        workspace = Path.cwd() / ".sophyane-workspace" / "arc-codex" / run_key / args.game
        workspace.mkdir(parents=True, exist_ok=True)
        provider = CodexCliProvider(workspace=workspace)
    else:
        from sophyane.config import load_config
        from sophyane.main import create_provider
        provider = create_provider(load_config())
    memory_root = args.state_root / args.provider
    from sophyane.arc_ecosystem import BadrpkArcEcosystem
    ecosystem = BadrpkArcEcosystem(memory_root)
    result = run_game(
        arc_agi.Arcade(), args.game,
        SophyaneArcAgent(provider.generate, ArcRSIMemory(memory_root), ecosystem=ecosystem, provider_id=args.provider),
        max_steps=args.max_steps,
    )
    print(json.dumps(asdict(result), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
