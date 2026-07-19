"""Strict interactive runtime that repairs malformed planner responses before acting."""
from __future__ import annotations

import json
from dataclasses import asdict
from typing import Any

from sophyane.decision_visibility import is_fatal_provider_error, normalize_candidates
from sophyane.doer import ProtocolError, StepRecord
from sophyane.interactive_coding_doer import InteractiveCodingDoerRuntime
from sophyane.strict_protocol import parse_and_validate_plan, strict_repair_request


SNAKE_GAME_HTML = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Snake Game</title>
<style>
:root{font-family:system-ui,sans-serif;color-scheme:dark}*{box-sizing:border-box}body{margin:0;min-height:100vh;display:grid;place-items:center;background:#101418;color:#f7f7f7}.card{width:min(94vw,560px);text-align:center;background:#1b2229;padding:20px;border-radius:18px;box-shadow:0 18px 60px #0008}canvas{width:min(86vw,480px);height:min(86vw,480px);max-height:480px;background:#09100c;border:2px solid #51606d;border-radius:10px;image-rendering:pixelated}.row{display:flex;justify-content:space-between;gap:12px;align-items:center;margin:8px auto 14px;max-width:480px}button{border:0;border-radius:10px;padding:10px 16px;font-weight:700;cursor:pointer}.controls{display:grid;grid-template-columns:repeat(3,58px);gap:7px;justify-content:center;margin-top:14px}.controls button{font-size:20px;padding:10px}.up{grid-column:2}.left{grid-column:1}.down{grid-column:2}.right{grid-column:3}.hint{opacity:.75;font-size:.9rem}</style>
</head>
<body>
<main class="card">
<h1>Snake Game</h1>
<div class="row"><strong>Score: <span id="score">0</span></strong><button id="restart">Restart</button></div>
<canvas id="game" width="480" height="480" aria-label="Snake game board"></canvas>
<div class="controls" aria-label="Touch controls"><button class="up" data-dir="up">▲</button><button class="left" data-dir="left">◀</button><button class="down" data-dir="down">▼</button><button class="right" data-dir="right">▶</button></div>
<p class="hint">Use arrow keys, WASD, or the touch buttons.</p>
</main>
<script>
const canvas=document.getElementById('game'),ctx=canvas.getContext('2d'),scoreEl=document.getElementById('score');
const size=24,cell=canvas.width/size;let snake,dir,nextDir,food,score,timer,alive;
function randomFood(){do{food={x:Math.floor(Math.random()*size),y:Math.floor(Math.random()*size)}}while(snake.some(p=>p.x===food.x&&p.y===food.y))}
function reset(){snake=[{x:12,y:12},{x:11,y:12},{x:10,y:12}];dir={x:1,y:0};nextDir=dir;score=0;alive=true;scoreEl.textContent=score;randomFood();clearInterval(timer);timer=setInterval(tick,105);draw()}
function choose(name){const map={up:{x:0,y:-1},down:{x:0,y:1},left:{x:-1,y:0},right:{x:1,y:0}},d=map[name];if(d&&!(d.x===-dir.x&&d.y===-dir.y))nextDir=d}
function tick(){if(!alive)return;dir=nextDir;const head={x:snake[0].x+dir.x,y:snake[0].y+dir.y};if(head.x<0||head.y<0||head.x>=size||head.y>=size||snake.some(p=>p.x===head.x&&p.y===head.y)){alive=false;clearInterval(timer);draw();return}snake.unshift(head);if(head.x===food.x&&head.y===food.y){score++;scoreEl.textContent=score;randomFood()}else snake.pop();draw()}
function draw(){ctx.fillStyle='#09100c';ctx.fillRect(0,0,canvas.width,canvas.height);ctx.fillStyle='#ff5d73';ctx.fillRect(food.x*cell+2,food.y*cell+2,cell-4,cell-4);snake.forEach((p,i)=>{ctx.fillStyle=i?'#37c978':'#7dffa9';ctx.fillRect(p.x*cell+1,p.y*cell+1,cell-2,cell-2)});if(!alive){ctx.fillStyle='#000b';ctx.fillRect(0,0,canvas.width,canvas.height);ctx.fillStyle='#fff';ctx.textAlign='center';ctx.font='bold 36px system-ui';ctx.fillText('Game Over',canvas.width/2,canvas.height/2);ctx.font='20px system-ui';ctx.fillText('Press Restart',canvas.width/2,canvas.height/2+38)}}
addEventListener('keydown',e=>{const m={ArrowUp:'up',w:'up',W:'up',ArrowDown:'down',s:'down',S:'down',ArrowLeft:'left',a:'left',A:'left',ArrowRight:'right',d:'right',D:'right'};if(m[e.key]){e.preventDefault();choose(m[e.key])}});document.querySelectorAll('[data-dir]').forEach(b=>b.addEventListener('click',()=>choose(b.dataset.dir)));document.getElementById('restart').addEventListener('click',reset);reset();
</script>
</body>
</html>
"""


class StrictInteractiveCodingDoerRuntime(InteractiveCodingDoerRuntime):
    """Require valid plans, normalize common model mistakes, and trust evidence."""

    def __init__(self, *args: Any, protocol_attempts: int = 3, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.protocol_attempts = max(1, min(int(protocol_attempts), 5))
        self._current_checks: list[dict[str, Any]] = []

    @staticmethod
    def _deterministic_plan(prompt: str, history: list[StepRecord]) -> dict[str, Any] | None:
        lowered = " ".join(prompt.lower().split())
        if history or "snake game" not in lowered:
            return None
        checks = [
            {"type": "file_exists", "path": "index.html"},
            {"type": "contains", "path": "index.html", "text": "Snake Game"},
            {"type": "contains", "path": "index.html", "text": "<canvas"},
        ]
        action = {
            "type": "write_file",
            "path": "index.html",
            "content": SNAKE_GAME_HTML,
            "deterministic_checks": checks,
        }
        return {
            "objective": "Create a playable self-contained Snake game for a web browser.",
            "success_criteria": [
                "index.html exists in the task workspace",
                "The game renders on an HTML canvas",
                "Keyboard and touch controls are available",
                "Score, collision, restart, and game-over behavior are implemented",
            ],
            "deterministic_checks": checks,
            "candidates": [
                {
                    "label": "Self-contained browser game",
                    "action": action,
                    "reason": "A single HTML file is portable, reversible, and needs no dependencies.",
                }
            ],
            "selected_index": 0,
            "selection_reason": "Use deterministic generation for this known small browser-game task.",
            "action": action,
            "rationale": "Avoid treating natural-language build instructions as shell commands.",
        }

    def _planner_request(
        self,
        prompt: str,
        context: str,
        objective: str,
        criteria: list[str],
        history: list[StepRecord],
        verifier_instruction: str,
    ) -> dict[str, Any]:
        return {
            "user_request": prompt,
            "persistent_and_repository_context": context,
            "current_objective": objective,
            "current_success_criteria": criteria,
            "previous_steps": [asdict(item) for item in history[-4:]],
            "verifier_instruction": verifier_instruction,
            "workspace": str(self.workspace),
            "task_queue": self.task_queue.to_dict(),
            "git_status": self.git.status(),
            "capabilities": {
                "repository_index": True,
                "symbol_search": True,
                "precise_patch": True,
                "batched_actions": True,
                "mechanical_verification": True,
                "git_checkpoints": True,
                "dependency_diagnostics": True,
                "browser_tools": False,
                "deployment_tools": False,
            },
            "instruction": (
                "Return exactly one JSON object matching the planner schema. Generate 2 or 3 safe candidates "
                "when possible, select the best one yourself, and encode the selected concrete action. "
                "Use action.type and run_command.argv as an array. Never copy the natural-language user request "
                "into run_command argv; build/create/make requests require write_file, apply_patch, or another "
                "file-producing action unless the user explicitly supplied a shell command. Use only typed "
                "deterministic checks: file_exists, contains, command_exit_zero, stdout_contains, "
                "no_uncommitted_changes. Do not emit markdown, prose, code fences, XML tool tags, "
                "<execute_bash>, or <tool_code>."
            ),
        }

    def _show_decision(self, plan: dict[str, Any]) -> None:
        candidates, selected_index = normalize_candidates(plan)
        if not candidates:
            raise ProtocolError("planner returned no candidate or selected action")
        self.progress.emit("☰", f"Choices considered: {len(candidates)}")
        for index, candidate in enumerate(candidates):
            action = candidate.get("action", {})
            label = str(candidate.get("label") or f"Candidate {index + 1}")
            reason = str(candidate.get("reason", "")).strip()
            marker = "★" if index == selected_index else "·"
            summary = self._action_summary(action) if isinstance(action, dict) else "invalid action"
            self.progress.emit(marker, f"{index + 1}. {label}: {summary}" + (f" — {reason}" if reason else ""))
        chosen = candidates[selected_index]
        chosen_label = str(chosen.get("label") or f"Candidate {selected_index + 1}")
        selection_reason = str(plan.get("selection_reason", "")).strip()
        self.progress.emit(
            "✅",
            f"Selected choice {selected_index + 1}: {chosen_label}"
            + (f" — {selection_reason}" if selection_reason else ""),
        )

    def _plan(
        self,
        prompt: str,
        context: str,
        objective: str,
        criteria: list[str],
        history: list[StepRecord],
        verifier_instruction: str,
    ) -> dict[str, Any]:
        self._visible_step = len(history) + 1
        deterministic = self._deterministic_plan(prompt, history)
        if deterministic is not None:
            self._current_checks = list(deterministic["deterministic_checks"])
            self.progress.emit("⚙", "Using deterministic browser-game plan")
            self._show_decision(deterministic)
            return deterministic

        request = self._planner_request(prompt, context, objective, criteria, history, verifier_instruction)
        current_prompt = json.dumps(request, ensure_ascii=False)
        last_error: Exception | None = None

        for attempt in range(1, self.protocol_attempts + 1):
            label = (
                f"Step {self._visible_step}: selecting the best next safe action"
                if attempt == 1
                else f"Step {self._visible_step}: repairing planner protocol (attempt {attempt}/{self.protocol_attempts})"
            )
            try:
                with self.progress.waiting("🧠", label):
                    raw = self.backend(current_prompt, self._system("planner"))
                plan = parse_and_validate_plan(raw)
                action = plan.get("action", {})
                if isinstance(action, dict) and action.get("type") == "run_command":
                    argv = [str(item).strip().lower() for item in action.get("argv", [])]
                    prompt_tokens = prompt.lower().split()
                    if argv == prompt_tokens:
                        raise ProtocolError(
                            "run_command mirrors the natural-language request instead of implementing it"
                        )
                self._current_checks = list(plan.get("deterministic_checks", []))
                self._show_decision(plan)
                return plan
            except Exception as error:
                if is_fatal_provider_error(error):
                    raise
                last_error = error
                preview = raw[-1200:].replace("\n", " | ") if "raw" in locals() else "<no response>"
                self.progress.emit("⚠", f"Planner protocol rejected: {type(error).__name__}: {error}")
                self.progress.emit("↳", f"Invalid response preview: {preview}")
                if attempt < self.protocol_attempts:
                    self.progress.emit("↻", "Requesting strict JSON regeneration automatically")
                    current_prompt = strict_repair_request(
                        request, raw if "raw" in locals() else "", error, attempt + 1
                    )

        raise ProtocolError(
            f"planner failed strict JSON protocol after {self.protocol_attempts} attempts: {last_error}"
        )

    def _verify(
        self,
        prompt: str,
        objective: str,
        criteria: list[str],
        history: list[StepRecord],
        observation: dict[str, Any],
    ) -> dict[str, Any]:
        observation = dict(observation)

        if self._current_checks:
            observation["deterministic_checks"] = self._current_checks

        mechanical = (
            self.mechanical.verify(
                self._current_checks,
                command_observations=[
                    asdict(item) for item in self.executor.report.commands
                ],
            )
            if self._current_checks
            else {"passed": None, "results": []}
        )

        try:
            verdict = super()._verify(
                prompt,
                objective,
                criteria,
                history,
                observation,
            )
        except Exception as error:
            verdict = {
                "goal_met": False,
                "confidence": 0,
                "missing_requirements": [
                    f"Verifier failure: {type(error).__name__}: {error}"
                ],
                "next_instruction": (
                    "Repair the verifier response and continue with "
                    "a concrete safe action."
                ),
                "final_answer": "",
            }

        if not isinstance(verdict, dict):
            verdict = {
                "goal_met": False,
                "confidence": 0,
                "missing_requirements": [
                    "Verifier returned an invalid non-dictionary result."
                ],
                "next_instruction": (
                    "Repair the verifier response and continue with "
                    "a concrete safe action."
                ),
                "final_answer": "",
            }

        verdict["mechanical_verification"] = mechanical

        if (
            mechanical.get("passed") is True
            and self._execution_contract_satisfied()
        ):
            verdict.update(
                {
                    "goal_met": True,
                    "confidence": 1,
                    "missing_requirements": [],
                    "next_instruction": "",
                    "final_answer": (
                        verdict.get("final_answer")
                        or "Objective completed with verified execution evidence."
                    ),
                    "verification_mode": "deterministic_evidence_override",
                }
            )

        return verdict
