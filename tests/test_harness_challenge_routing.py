from __future__ import annotations

from pathlib import Path

from sophyane.harness_acceptance import criteria
from sophyane.harness_task_policy import (
    classify,
    filesystem_only_request,
    is_execution_request,
    protected_context,
)
from sophyane.harness_workspace import select_workspace


PROMPTS = [
    (
        "Create a complete FastAPI TODO application with authentication, "
        "SQLite, tests, Dockerfile, GitHub Actions, and README. Build it, "
        "run all tests, fix every error automatically until everything "
        "passes, then summarize what you changed."
    ),
    (
        "Analyze this entire repository. Find dead code, duplicate logic, "
        "performance bottlenecks, security problems, architectural issues, "
        "and produce a prioritized refactoring plan with exact file names "
        "and patches."
    ),
    (
        "Find the 20 largest files on my mobile, identify duplicates larger "
        "than 50 MB, estimate reclaimable storage, and produce a safe cleanup "
        "plan without deleting anything."
    ),
    (
        "Implement an MCP server that exposes every deterministic Sophyane "
        "capability as MCP tools. Verify it using an MCP client and fix every "
        "issue until all tests pass."
    ),
    (
        "Review every failing pytest in this repository. Fix them one by one, "
        "rerunning only affected tests after each change. Continue until the "
        "entire suite passes or no deterministic fix remains."
    ),
    (
        "Benchmark every native backend (NIFDU, neuron, Python runtime and "
        "LLM). Measure latency, throughput, RAM, CPU, startup time and "
        "generate a Markdown report with tables and recommendations."
    ),
    (
        "Search the repository for technical debt. Replace duplicated code "
        "with reusable components while preserving behaviour. Run the "
        "complete test suite after every logical change and stop only when "
        "all tests pass."
    ),
    (
        "Design a production architecture that lets Sophyane compete with "
        "Claude Code. Include orchestration, long-running agents, memory, "
        "MCP, tool routing, distributed execution, recovery after crashes, "
        "and autonomous retries. Then generate an implementation roadmap."
    ),
    (
        "Starting from this repository, improve startup speed by at least "
        "30%. Measure the current performance, identify bottlenecks, "
        "implement optimizations, rerun benchmarks, and show before-and-after "
        "results with evidence."
    ),
    (
        "Take complete ownership of this repository for the next hour. "
        "Continuously inspect, improve, test, refactor, document, and "
        "benchmark the project. Do not stop after one task; keep choosing "
        "the highest-impact next action until I interrupt you."
    ),
]


def test_all_challenge_prompts_are_execution_or_storage_workflows() -> None:
    for index, prompt in enumerate(PROMPTS):
        policy = classify(prompt)

        if index == 2:
            assert policy.filesystem_only
        else:
            assert policy.execution


def test_repository_audit_not_hijacked_by_duplicate_file_scan() -> None:
    prompt = PROMPTS[1]

    assert not filesystem_only_request(prompt)
    assert is_execution_request(prompt)


def test_storage_cleanup_remains_filesystem_workflow() -> None:
    prompt = PROMPTS[2]

    assert filesystem_only_request(prompt)


def test_neuron_and_nifdu_are_protected_terms() -> None:
    context = protected_context(PROMPTS[5])

    assert "NIFDU" in context
    assert "local NIFDU Neuron runtime" in context
    assert "AWS Neuron" not in context


def test_fastapi_project_uses_isolated_workspace(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        Path,
        "home",
        staticmethod(lambda: tmp_path),
    )

    selected = select_workspace(
        PROMPTS[0],
        tmp_path / "sophyane-repo",
    )

    assert selected != (tmp_path / "sophyane-repo").resolve()
    assert ".sophyane/generated-projects" in str(selected)


def test_compound_acceptance_criteria_are_preserved() -> None:
    expected_minimums = [6, 5, 4, 3, 2, 5, 3, 2, 3, 2]

    for prompt, minimum in zip(PROMPTS, expected_minimums):
        assert len(criteria(prompt)) >= minimum
