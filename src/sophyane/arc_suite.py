"""Resumable all-environment ARC-AGI-3 evaluation for Sophyane Mode 4."""
from __future__ import annotations
import argparse, hashlib, json, time
from dataclasses import asdict
from pathlib import Path

from sophyane.arc_agi3 import ArcRSIMemory, SophyaneArcAgent, run_game
from sophyane.arc_ecosystem import BadrpkArcEcosystem
from sophyane.providers.codex_cli import CodexCliProvider


def _game_id(info):
    return str(getattr(info, "game_id", None) or getattr(info, "id", None) or info)[:4].lower()


def run_suite(*, max_steps: int, state_root: Path, resume: bool = True) -> dict:
    import arc_agi
    state_root.mkdir(parents=True, exist_ok=True)
    journal = state_root / "suite-results.jsonl"
    completed = set()
    if resume and journal.exists():
        for line in journal.read_text(encoding="utf-8", errors="replace").splitlines():
            try: completed.add(json.loads(line)["game_id"])
            except Exception: pass
    arcade = arc_agi.Arcade()
    games = sorted(dict.fromkeys(_game_id(item) for item in arcade.get_environments()))
    results = []
    for game_id in games:
        if game_id in completed:
            continue
        key = hashlib.sha256(str(state_root.resolve()).encode()).hexdigest()[:12]
        workspace = Path.cwd() / ".sophyane-workspace/arc-codex" / key / game_id
        workspace.mkdir(parents=True, exist_ok=True)
        provider = CodexCliProvider(workspace=workspace)
        game_root = state_root / "codex_cli"
        ecosystem = BadrpkArcEcosystem(game_root)
        started = time.time()
        try:
            result = asdict(run_game(arcade, game_id, SophyaneArcAgent(provider.generate, ArcRSIMemory(game_root), ecosystem=ecosystem, provider_id="codex_cli"), max_steps=max_steps))
            record = {**result, "elapsed_seconds": round(time.time() - started, 3), "error": None}
        except Exception as error:
            record = {"game_id": game_id, "score": None, "elapsed_seconds": round(time.time() - started, 3), "error": str(error)}
        with journal.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
            handle.flush()
        results.append(record)
    all_records = [json.loads(line) for line in journal.read_text(encoding="utf-8").splitlines() if line.strip()]
    report = {"games_available": len(games), "games_recorded": len(all_records), "max_steps_per_game": max_steps,
              "scorecard_id": next((r.get("scorecard_id") for r in reversed(all_records) if r.get("scorecard_id")), None),
              "latest_rhae": next((r.get("score") for r in reversed(all_records) if r.get("score") is not None), None),
              "complete": len({r.get("game_id") for r in all_records}) == len(games), "results": all_records}
    (state_root / "suite-report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description="Run all public ARC-AGI-3 environments with Sophyane Mode 4")
    parser.add_argument("--max-steps", type=int, default=200)
    parser.add_argument("--state-root", type=Path, default=Path(".sophyane-workspace/arc-full-eval"))
    parser.add_argument("--no-resume", action="store_true")
    args = parser.parse_args(argv)
    print(json.dumps(run_suite(max_steps=args.max_steps, state_root=args.state_root, resume=not args.no_resume), indent=2))
    return 0


if __name__ == "__main__": raise SystemExit(main())
