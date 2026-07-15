"""Tough-100 harness/coding exam runner (package-local)."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from sophyane.expert.answer import answer_tough_question
from sophyane.version import __version__

_QUESTION_CANDIDATES = [
    Path(__file__).resolve().parent / "data" / "tough100_questions.json",
    Path(__file__).resolve().parents[3] / "benchmarks" / "tough100_questions.json",
    Path.home() / ".local/share/sophyane/current/benchmarks/tough100_questions.json",
]


def _load_questions() -> list[dict[str, Any]]:
    for path in _QUESTION_CANDIDATES:
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
    raise FileNotFoundError("tough100_questions.json not found; reinstall Sophyane from GitHub")

def _out_dir() -> Path:
    d = Path.home() / ".local/state/sophyane/exams/tough100"
    d.mkdir(parents=True, exist_ok=True)
    # also write under install tree when present
    alt = Path.home() / ".local/share/sophyane/current/benchmark-results/tough100"
    try:
        alt.mkdir(parents=True, exist_ok=True)
    except OSError:
        pass
    return d


def _llm_generate():
    try:
        from sophyane.config import load_config
        from sophyane.main import create_provider

        provider = create_provider(load_config())
        if hasattr(provider, "max_tokens"):
            provider.max_tokens = min(int(getattr(provider, "max_tokens", 256) or 256), 256)

        def gen(prompt: str, system: str) -> str:
            return provider.generate(prompt, system)

        return gen
    except Exception as error:  # noqa: BLE001
        def gen(prompt: str, system: str) -> str:
            raise RuntimeError(str(error))

        return gen


def run_exam(*, mode: str = "hybrid", limit: int = 100, with_llm: bool = True) -> dict[str, Any]:
    items = _load_questions()[: max(1, int(limit))]
    generate = _llm_generate() if with_llm and mode != "expert" else None
    results: list[dict[str, Any]] = []
    t0 = time.perf_counter()
    for item in items:
        r = answer_tough_question(
            item["q"],
            qid=int(item["id"]),
            cat=str(item["cat"]),
            keys=list(item.get("keys") or []),
            generate=generate,
            mode=mode,
        )
        results.append(
            {
                "id": item["id"],
                "cat": item["cat"],
                "q": item["q"],
                "used": r["used"],
                "scoring": r["scoring"],
                "answer_preview": (r["answer"] or "")[:400],
            }
        )
    elapsed = time.perf_counter() - t0
    passed = sum(1 for x in results if x["scoring"].get("passed"))
    avg = sum(float(x["scoring"].get("score") or 0) for x in results) / max(1, len(results))
    by_cat: dict[str, dict[str, Any]] = {}
    for x in results:
        c = x["cat"]
        by_cat.setdefault(c, {"n": 0, "pass": 0, "score_sum": 0.0})
        by_cat[c]["n"] += 1
        by_cat[c]["pass"] += 1 if x["scoring"].get("passed") else 0
        by_cat[c]["score_sum"] += float(x["scoring"].get("score") or 0)
    for c, v in by_cat.items():
        v["avg_score"] = round(v["score_sum"] / max(1, v["n"]), 3)
        v["pass_rate"] = round(100 * v["pass"] / max(1, v["n"]), 1)
        del v["score_sum"]

    fails = [x for x in results if not x["scoring"].get("passed")]
    report = {
        "ok": passed == len(results),
        "version": __version__,
        "mode": mode,
        "total": len(results),
        "passed": passed,
        "pass_rate": round(100 * passed / max(1, len(results)), 1),
        "avg_score": round(avg, 3),
        "elapsed_sec": round(elapsed, 2),
        "by_category": by_cat,
        "failures": [
            {
                "id": f["id"],
                "cat": f["cat"],
                "miss": f["scoring"].get("keys_miss"),
                "score": f["scoring"].get("score"),
            }
            for f in fails
        ],
        "results": results,
    }
    out = _out_dir()
    (out / f"results_{mode}.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    md = [
        f"# Tough 100 exam — {mode}",
        "",
        f"- Version: **{__version__}**",
        f"- Pass: **{passed}/{len(results)} ({report['pass_rate']}%)**",
        f"- Avg score: **{report['avg_score']}**",
        f"- Elapsed: **{report['elapsed_sec']}s**",
        "",
        "| Category | Pass rate | Avg score |",
        "|---|---:|---:|",
    ]
    for c, v in sorted(by_cat.items()):
        md.append(f"| {c} | {v['pass_rate']}% | {v['avg_score']} |")
    (out / f"REPORT_{mode}.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    # Mirror under install tree
    mirror = Path.home() / ".local/share/sophyane/current/benchmark-results/tough100"
    if mirror.parent.exists():
        try:
            mirror.mkdir(parents=True, exist_ok=True)
            (mirror / f"results_{mode}.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
            (mirror / f"REPORT_{mode}.md").write_text("\n".join(md) + "\n", encoding="utf-8")
        except OSError:
            pass
    return report
