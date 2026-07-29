"""Eval datasets + experiments (local LangSmith-lite)."""
from __future__ import annotations
import json
import time
import uuid
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Callable

DATA_DIR = Path.home() / ".local/state/sophyane/datasets"
EXP_DIR = Path.home() / ".local/state/sophyane/experiments"
PROMPT_DIR = Path.home() / ".local/state/sophyane/prompts"
for d in (DATA_DIR, EXP_DIR, PROMPT_DIR):
    d.mkdir(parents=True, exist_ok=True)

@dataclass
class Example:
    inputs: dict[str, Any]
    outputs: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)

@dataclass
class Dataset:
    name: str
    examples: list[Example] = field(default_factory=list)
    version: int = 1

    def path(self) -> Path:
        return DATA_DIR / f"{self.name}.v{self.version}.json"

    def save(self) -> Path:
        p = self.path()
        p.write_text(
            json.dumps({"name": self.name, "version": self.version, "examples": [asdict(e) for e in self.examples]}, indent=2),
            encoding="utf-8",
        )
        return p

    @classmethod
    def load(cls, name: str, version: int | None = None) -> "Dataset":
        files = sorted(DATA_DIR.glob(f"{name}.v*.json"))
        if not files:
            raise FileNotFoundError(name)
        path = files[-1] if version is None else DATA_DIR / f"{name}.v{version}.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        return cls(
            name=data["name"],
            version=int(data.get("version", 1)),
            examples=[Example(**e) for e in data.get("examples", [])],
        )

def save_prompt_version(name: str, text: str, meta: dict[str, Any] | None = None) -> Path:
    existing = sorted(PROMPT_DIR.glob(f"{name}.v*.txt"))
    ver = len(existing) + 1
    path = PROMPT_DIR / f"{name}.v{ver}.txt"
    path.write_text(text, encoding="utf-8")
    (PROMPT_DIR / f"{name}.v{ver}.meta.json").write_text(
        json.dumps({"name": name, "version": ver, "meta": meta or {}, "ts": time.time()}, indent=2),
        encoding="utf-8",
    )
    return path

def load_prompt(name: str, version: int | None = None) -> str:
    files = sorted(PROMPT_DIR.glob(f"{name}.v*.txt"))
    if not files:
        raise FileNotFoundError(name)
    path = files[-1] if version is None else PROMPT_DIR / f"{name}.v{version}.txt"
    return path.read_text(encoding="utf-8")

Evaluator = Callable[[dict[str, Any], dict[str, Any]], dict[str, Any]]

def exact_match(expected: dict[str, Any], actual: dict[str, Any]) -> dict[str, Any]:
    ok = expected == actual
    return {"score": 1.0 if ok else 0.0, "passed": ok}

def contains_key(key: str) -> Evaluator:
    def _ev(expected: dict[str, Any], actual: dict[str, Any]) -> dict[str, Any]:
        ok = key in actual
        return {"score": 1.0 if ok else 0.0, "passed": ok}
    return _ev

@dataclass
class ExperimentResult:
    experiment_id: str
    dataset: str
    scores: list[dict[str, Any]]
    mean_score: float
    ts: float = field(default_factory=time.time)

    def save(self) -> Path:
        p = EXP_DIR / f"{self.experiment_id}.json"
        p.write_text(json.dumps(asdict(self), indent=2), encoding="utf-8")
        return p

def run_experiment(
    dataset: Dataset,
    predict: Callable[[dict[str, Any]], dict[str, Any]],
    evaluators: list[Evaluator] | None = None,
    name: str | None = None,
) -> ExperimentResult:
    evaluators = evaluators or [exact_match]
    scores: list[dict[str, Any]] = []
    for i, ex in enumerate(dataset.examples):
        actual = predict(ex.inputs)
        row: dict[str, Any] = {"index": i, "actual": actual}
        for j, ev in enumerate(evaluators):
            row[f"eval_{j}"] = ev(ex.outputs, actual)
        scores.append(row)
    vals = [r.get("eval_0", {}).get("score", 0.0) for r in scores]
    mean = sum(vals) / len(vals) if vals else 0.0
    result = ExperimentResult(
        experiment_id=name or str(uuid.uuid4()),
        dataset=f"{dataset.name}.v{dataset.version}",
        scores=scores,
        mean_score=mean,
    )
    result.save()
    return result

def compare_experiments(*paths: Path) -> dict[str, Any]:
    rows = []
    for p in paths:
        data = json.loads(Path(p).read_text(encoding="utf-8"))
        rows.append({"id": data.get("experiment_id"), "mean": data.get("mean_score"), "dataset": data.get("dataset")})
    rows.sort(key=lambda r: r["mean"], reverse=True)
    return {"ranking": rows}
