"""Indefinite local-only software curriculum for SLI.

The loop creates validator-grounded execution experiences. It does not alter
GGUF neural weights, launch browsers, run model-generated shell commands, or
use cloud providers.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import signal
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sophyane.providers.local_gguf import LocalGgufProvider
from sophyane.sli_learner import learn_execution

STATE_DIR = Path.home() / ".local/state/sophyane/sli-training"
PROJECT_DIR = Path.home() / ".sophyane/sli-training/projects"
CHECKPOINT = STATE_DIR / "checkpoint.json"
STOP = False

SYSTEM = (
    "You are Sophyane's local offline software curriculum model. Produce only "
    "the requested JSON or one complete index.html. Never use URLs, CDNs, "
    "packages, imports, network requests, backends, or shell commands."
)

SEEDS = (
    ("Tip calculator", "Create a responsive tip calculator in one offline HTML file.", "calculator"),
    ("Unit converter", "Create a responsive unit converter in one offline HTML file.", "converter"),
    ("Pomodoro timer", "Create a responsive Pomodoro timer in one offline HTML file.", "timer"),
    ("Expense tracker", "Create a personal expense tracker in one offline HTML file.", "tracker"),
    ("To-do list", "Create a responsive to-do list in one offline HTML file.", "todo"),
    ("Quiz app", "Create an interactive quiz in one offline HTML file.", "quiz"),
    ("Password generator", "Create an offline password generator in one HTML file.", "generator"),
    ("Memory game", "Create a simple memory card game in one offline HTML file.", "game"),
)


@dataclass
class Project:
    title: str
    request: str
    category: str
    criteria: list[str]


def stop(_signum: int, _frame: object) -> None:
    global STOP
    STOP = True
    print("\nCtrl+C received; saving a safe checkpoint after the current call.", flush=True)


def load_state() -> dict[str, Any]:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    PROJECT_DIR.mkdir(parents=True, exist_ok=True)
    if CHECKPOINT.exists():
        try:
            return json.loads(CHECKPOINT.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"started": 0, "completed": 0, "failed": 0, "iterations": 0, "titles": [], "current": None}


def save_state(state: dict[str, Any]) -> None:
    state["updated_at"] = time.time()
    temporary = CHECKPOINT.with_suffix(".tmp")
    temporary.write_text(json.dumps(state, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    temporary.replace(CHECKPOINT)


def extract_json(text: str) -> dict[str, Any] | None:
    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        value = json.loads(text[start : end + 1])
        return value if isinstance(value, dict) else None
    except json.JSONDecodeError:
        return None


def extract_html(text: str) -> str:
    value = str(text or "").strip().lstrip("\ufeff")
    match = re.search(r"```(?:html|htm)?\s*(.*?)```", value, re.I | re.S)
    if match:
        value = match.group(1).strip()
    lower = value.lower()
    starts = [position for position in (lower.find("<!doctype html"), lower.find("<html")) if position >= 0]
    if not starts:
        return ""
    value = value[min(starts) :]
    end = value.lower().rfind("</html>")
    return value[: end + 7].strip() if end >= 0 else ""


def snapshot(workspace: Path) -> dict[str, Any]:
    sample = []
    total = 0
    for path in sorted(workspace.rglob("*")):
        if path.is_file():
            size = path.stat().st_size
            total += size
            if len(sample) < 50:
                sample.append({"path": str(path.relative_to(workspace)), "bytes": size})
    return {"files": len(sample), "bytes": total, "sample": sample}


def validate(html: str, category: str) -> list[str]:
    lower = html.lower()
    errors = []
    checks = (
        (len(html) >= 700, "document is too small"),
        ("<html" in lower and "</html>" in lower, "complete html element is missing"),
        ("<body" in lower and "</body>" in lower, "complete body element is missing"),
        ("<script" in lower and "</script>" in lower, "interactive JavaScript is missing"),
        ("viewport" in lower, "mobile viewport is missing"),
        ("<style" in lower or "style=" in lower, "styling is missing"),
    )
    errors.extend(message for passed, message in checks if not passed)
    if any(marker in lower for marker in ("http://", "https://", "fetch(", "xmlhttprequest", "cdn.")):
        errors.append("external or network dependency detected")
    if category in {"calculator", "converter"} and ("<input" not in lower or "<button" not in lower):
        errors.append("input controls and buttons are required")
    if category == "timer" and not any(item in lower for item in ("setinterval", "settimeout")):
        errors.append("timer scheduling behavior is missing")
    return errors


def model() -> LocalGgufProvider:
    return LocalGgufProvider(timeout=90, temperature=0.35, max_tokens=1024)


def nominate(provider: LocalGgufProvider, titles: set[str], index: int) -> Project:
    prompt = (
        "Nominate one small offline single-file browser application. Return exactly JSON: "
        '{"title":"...","request":"Create ... in one offline HTML file.",'
        '"category":"calculator|converter|timer|tracker|todo|quiz|game|generator",'
        '"criteria":["...","...","..."]}. Avoid these titles: '
        + ", ".join(sorted(titles)[-20:])
    )
    for _ in range(3):
        try:
            value = extract_json(provider.generate(prompt, SYSTEM))
            if not value:
                continue
            title = str(value.get("title") or "").strip()[:100]
            request = str(value.get("request") or "").strip()[:300]
            category = str(value.get("category") or "tracker").strip().lower()
            criteria = [str(item).strip()[:160] for item in value.get("criteria", []) if str(item).strip()][:6]
            if title and request and title.lower() not in titles:
                return Project(title, request, category, criteria or ["Works offline", "Works on mobile", "Has useful interaction"])
        except Exception:
            pass
    title, request, category = SEEDS[index % len(SEEDS)]
    return Project(title, request, category, ["Works offline", "Works on mobile", "Handles invalid input safely"])


def generation_prompt(project: Project, previous: str, errors: list[str]) -> str:
    criteria = "\n".join(f"- {item}" for item in project.criteria)
    if not previous:
        return (
            f"Create: {project.request}\nAcceptance criteria:\n{criteria}\n"
            "Return only one complete HTML document beginning <!doctype html>. "
            "Put CSS and JavaScript inline; use no external resources."
        )
    feedback = "\n".join(f"- {item}" for item in errors) or "- Improve usability without removing working features."
    return (
        f"Replace and improve this offline application: {project.request}\n"
        f"Validator feedback:\n{feedback}\nAcceptance criteria:\n{criteria}\n"
        "Return only a complete replacement index.html.\nCURRENT HTML:\n" + previous[-2700:]
    )


def run_project(provider: LocalGgufProvider, project: Project, workspace: Path, max_loops: int, state: dict[str, Any]) -> tuple[bool, int]:
    workspace.mkdir(parents=True, exist_ok=True)
    previous = ""
    errors: list[str] = []
    hashes: list[str] = []
    target = workspace / "index.html"
    for iteration in range(1, max_loops + 1):
        if STOP:
            return False, iteration - 1
        before = snapshot(workspace)
        started = time.monotonic()
        trace_id = uuid.uuid4().hex[:12]
        try:
            raw = provider.generate(generation_prompt(project, previous, errors), SYSTEM)
            (workspace / f"provider-response-{int(time.time())}-{iteration}.txt").write_text(raw, encoding="utf-8")
            html = extract_html(raw)
            if not html:
                result = "Execution stopped safely: provider could not produce a usable HTML artifact."
                learn_execution(trace_id=trace_id, request=project.request, workspace_before=before, workspace_after=snapshot(workspace), status="failed", reward=-1.0, result=result, elapsed_seconds=time.monotonic() - started)
                errors = ["complete HTML was not returned"]
                continue
            digest = hashlib.sha256(html.encode()).hexdigest()
            if hashes[-3:].count(digest) >= 2:
                result = "Execution stopped safely after unchanged artifact stagnation. Previous working files were preserved."
                learn_execution(trace_id=trace_id, request=project.request, workspace_before=before, workspace_after=snapshot(workspace), status="failed", reward=-1.0, result=result, elapsed_seconds=time.monotonic() - started)
                return False, iteration
            hashes.append(digest)
            errors = validate(html, project.category)
            previous = html
            if errors:
                result = "Browser artifact validation failed. Previous working files were preserved. Errors: " + "; ".join(errors)
                learn_execution(trace_id=trace_id, request=project.request, workspace_before=before, workspace_after=snapshot(workspace), status="failed", reward=-1.0, result=result, elapsed_seconds=time.monotonic() - started)
                print(f"  {iteration}/{max_loops} failed: {'; '.join(errors[:3])}", flush=True)
            else:
                target.write_text(html, encoding="utf-8")
                result = ("Browser artifact generated. ""Structural verification completed. ""Project awaiting post-build validation.")
                learned = learn_execution(trace_id=trace_id, request=project.request, workspace_before=before, workspace_after=snapshot(workspace), status="succeeded", reward=1.0, result=result, elapsed_seconds=time.monotonic() - started)
                print(f"  {iteration}/{max_loops} passed reward={learned['quality_reward']:+.2f}", flush=True)
                return True, iteration
        except Exception as error:
            result = f"Execution stopped safely: local provider error. {type(error).__name__}: {error}"
            learn_execution(trace_id=trace_id, request=project.request, workspace_before=before, workspace_after=snapshot(workspace), status="failed", reward=-1.0, result=result, error=str(error), elapsed_seconds=time.monotonic() - started)
            print(f"  {iteration}/{max_loops} provider error: {error}", flush=True)
        state["iterations"] += 1
        state["current"] = {"title": project.title, "workspace": str(workspace), "iteration": iteration}
        save_state(state)
    return False, max_loops


def status() -> None:
    state = load_state()
    print(json.dumps({**state, "checkpoint": str(CHECKPOINT), "project_root": str(PROJECT_DIR)}, indent=2, ensure_ascii=False))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run local validated SLI curriculum training")
    parser.add_argument("--max-loops-per-project", type=int, default=100)
    parser.add_argument("--max-projects", type=int, default=0, help="0 continues until Ctrl+C")
    parser.add_argument("--min-free-gib", type=float, default=1.0)
    parser.add_argument("--status", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    if args.status:
        status()
        return 0
    state = load_state()
    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)
    provider = model()
    titles = {str(item).lower() for item in state.get("titles", [])}
    run_count = 0
    print("Sophyane local SLI curriculum loop; stop safely with Ctrl+C")
    print("This improves SLI experience and policy, not GGUF neural weights.")
    while not STOP and (args.max_projects <= 0 or run_count < args.max_projects):
        free = shutil.disk_usage(Path.home()).free / (1024 ** 3)
        if free < args.min_free_gib:
            print(f"Paused: only {free:.2f} GiB free")
            save_state(state)
            return 2
        project = nominate(provider, titles, int(state["started"]))
        print(f"\nProject {int(state['started']) + 1}: {project.title}\n{project.request}")
        if args.dry_run:
            return 0
        workspace = PROJECT_DIR / f"{time.strftime('%Y%m%d-%H%M%S')}-{re.sub(r'[^a-z0-9]+', '-', project.title.lower()).strip('-')[:60]}"
        state["started"] += 1
        state["current"] = {"title": project.title, "workspace": str(workspace), "iteration": 0}
        save_state(state)
        succeeded, loops = run_project(provider, project, workspace, max(1, min(100, args.max_loops_per_project)), state)
        if STOP:
            break
        if succeeded:
            state["completed"] += 1
            titles.add(project.title.lower())
            state["titles"] = sorted(titles)
            print(f"Completed after {loops} loop(s)")
        else:
            state["failed"] += 1
            print(f"Not finalized after {loops} loop(s)")
        state["current"] = None
        save_state(state)
        run_count += 1
    save_state(state)
    print("Training loop stopped safely.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
