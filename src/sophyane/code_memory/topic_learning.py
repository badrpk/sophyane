"""Autonomous topic-focused SLI learning built on Sophyane's existing runtime."""
from __future__ import annotations

import json
import os
import re
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable

Progress = Callable[[str], None]

ROOT = Path.home() / ".local/share/sophyane/continuous_sli/topics"

FACETS = (
    "core concepts and terminology",
    "architecture and system components",
    "runtime orchestration and control flow",
    "memory retrieval and context management",
    "tool execution permissions and sandboxing",
    "planning verification and failure recovery",
    "observability tracing and evaluation",
    "security prompt injection and trust boundaries",
    "benchmarks testing and quality gates",
    "production case studies and implementation patterns",
    "performance latency and cost control",
    "open research gaps and emerging approaches",
)

SOURCE_VIEWS = (
    "implementation code",
    "technical documentation",
    "reference architecture",
    "tests and benchmarks",
)


@dataclass
class TopicRun:
    topic: str
    started_at: float
    finished_at: float
    iterations: int
    successful_iterations: int
    new_chunks: int
    no_novelty_streak: int
    stopped_reason: str
    requests: list[dict]


def _normalise(value: str) -> str:
    return " ".join(str(value or "").strip().split())


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")[:80] or "topic"


def _env_int(name: str, default: int, minimum: int = 1) -> int:
    try:
        return max(minimum, int(os.environ.get(name, default)))
    except (TypeError, ValueError):
        return default


def _request(topic: str, iteration: int) -> tuple[str, str, str]:
    facet = FACETS[iteration % len(FACETS)]
    source_view = SOURCE_VIEWS[(iteration // len(FACETS)) % len(SOURCE_VIEWS)]
    instruction = (
        "Acquire, validate and learn multiple permissively licensed sources about "
        f"{topic}, focusing on {facet}. Prefer substantial {source_view}; inspect "
        "all relevant source, documentation and test files rather than only one "
        "browser entry point. Semantically chunk, embed, deduplicate and promote "
        "novel reusable knowledge into SLI memory. Do not generate an unrelated demo."
    )
    return instruction, facet, source_view


def _embedding_status() -> str:
    try:
        from sophyane.code_memory.embedder import get_embedder
        embedder = get_embedder()
        return str(getattr(embedder, "description", type(embedder).__name__))
    except Exception as error:  # noqa: BLE001
        return f"unavailable: {type(error).__name__}: {error}"


def learn_topic(
    topic: str,
    *,
    progress: Progress | None = None,
    max_iterations: int | None = None,
    novelty_patience: int | None = None,
) -> TopicRun:
    """Expand one topic repeatedly until saturation, limit, or Ctrl+C."""
    from sophyane.code_memory.continuous_sli_loop import execute_instruction

    progress = progress or (lambda message: print(f"[SLI] {message}", flush=True))
    topic = _normalise(topic)
    if not topic:
        raise ValueError("topic must not be empty")

    max_iterations = max_iterations or _env_int("SOPHYANE_TOPIC_MAX_ITERATIONS", 24)
    novelty_patience = novelty_patience or _env_int("SOPHYANE_TOPIC_NOVELTY_PATIENCE", 4)

    topic_root = ROOT / _slug(topic)
    topic_root.mkdir(parents=True, exist_ok=True)
    started = time.time()
    records: list[dict] = []
    total_new = 0
    successes = 0
    no_novelty = 0
    stopped_reason = "iteration_limit"

    saved = {name: os.environ.get(name) for name in (
        "SOPHYANE_DISABLE_BROWSER_OPEN",
        "SOPHYANE_NO_AUTO_OPEN",
        "SOPHYANE_BROWSER_PREVIEW",
        "SOPHYANE_CONTINUOUS_AUTO_PREVIEW",
    )}
    os.environ["SOPHYANE_DISABLE_BROWSER_OPEN"] = "1"
    os.environ["SOPHYANE_NO_AUTO_OPEN"] = "1"
    os.environ["SOPHYANE_BROWSER_PREVIEW"] = "0"
    os.environ["SOPHYANE_CONTINUOUS_AUTO_PREVIEW"] = "0"

    progress(f"Topic curriculum: {topic}")
    progress(f"Embedding backend: {_embedding_status()}")
    progress(
        f"Iterations: up to {max_iterations}; saturation after "
        f"{novelty_patience} consecutive zero-novelty rounds"
    )

    try:
        for iteration in range(max_iterations):
            instruction, facet, source_view = _request(topic, iteration)
            progress(
                f"Topic iteration {iteration + 1}/{max_iterations}: "
                f"{facet} [{source_view}]"
            )
            event = execute_instruction(instruction, progress=progress)
            learned = int(event.chunks_learned)
            total_new += learned
            successes += int(event.success)
            no_novelty = no_novelty + 1 if learned == 0 else 0
            record = {
                "iteration": iteration + 1,
                "facet": facet,
                "source_view": source_view,
                "request": instruction,
                "success": event.success,
                "chunks_learned": learned,
                "workspace": event.workspace,
                "seconds": event.elapsed_seconds,
            }
            records.append(record)
            (topic_root / "events.jsonl").open("a", encoding="utf-8").write(
                json.dumps(record, ensure_ascii=False) + "\n"
            )
            progress(
                f"Topic coverage progress: +{learned} chunks; "
                f"total +{total_new}; zero-novelty streak {no_novelty}/{novelty_patience}"
            )
            if no_novelty >= novelty_patience:
                stopped_reason = "semantic_saturation"
                break
    except KeyboardInterrupt:
        stopped_reason = "user_interrupt"
    finally:
        for name, value in saved.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value

    result = TopicRun(
        topic=topic,
        started_at=started,
        finished_at=time.time(),
        iterations=len(records),
        successful_iterations=successes,
        new_chunks=total_new,
        no_novelty_streak=no_novelty,
        stopped_reason=stopped_reason,
        requests=records,
    )
    (topic_root / "summary.json").write_text(
        json.dumps(asdict(result), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return result


def run_topic_learning_loop() -> int:
    print("\n◆ Continuous SLI topic learning")
    print("  Enter one topic. Sophyane expands, acquires, chunks, embeds and learns")
    print("  repeatedly until semantic saturation, the iteration cap, or Ctrl+C.")
    print("  Commands: /status, /history, /quit\n")

    while True:
        try:
            topic = input("SLI topic ❯ ").strip()
        except EOFError:
            return 0
        except KeyboardInterrupt:
            print("\nContinuous topic learning stopped.")
            return 130

        if not topic:
            continue
        if topic.lower() in {"/quit", "/exit", "quit", "exit"}:
            return 0
        if topic.lower() in {"/status", "/history"}:
            from sophyane.code_memory.continuous_sli_loop import _print_history, _print_status
            (_print_status if topic.lower() == "/status" else _print_history)()
            continue

        result = learn_topic(topic)
        print("\nTopic learning summary")
        print("──────────────────────")
        print("Topic                :", result.topic)
        print("Iterations           :", result.iterations)
        print("Successful iterations:", result.successful_iterations)
        print("New chunks           :", result.new_chunks)
        print("Stopped              :", result.stopped_reason)
        print("State                :", ROOT / _slug(result.topic))
        print()
