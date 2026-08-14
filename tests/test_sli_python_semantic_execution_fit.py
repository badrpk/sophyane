from __future__ import annotations

from types import SimpleNamespace

from sophyane.sli_semantic_intelligence import (
    CapabilityRequirement,
    SemanticPlan,
    _chunk_semantic_score,
)


def plan() -> SemanticPlan:
    return SemanticPlan(
        request=(
            "Build a Python process monitoring tool "
            "with safe command execution."
        ),
        concepts=[
            "python",
            "process",
            "monitoring",
            "safe",
            "command",
            "execution",
        ],
        capabilities=[],
        target_language="python",
        target_artifact="python_application",
    )


def requirement() -> CapabilityRequirement:
    return CapabilityRequirement(
        name="safe_command_execution",
        importance=2.0,
        reasons=["safe command execution"],
        query=(
            "python process monitoring safe command "
            "execution subprocess shell false timeout"
        ),
    )


def chunk(
    *,
    text: str,
    path: str,
    placement: str = "",
    language: str = "python",
):
    return SimpleNamespace(
        id=path,
        text=text,
        path=path,
        source="memory",
        language=language,
        weight=1.0,
        meta={
            "placement": placement,
        },
    )


def test_small_executable_python_component_beats_oversized_parent():
    small = chunk(
        text=(
            "import subprocess\n\n"
            "def safe_run(argv):\n"
            "    return subprocess.run(\n"
            "        argv,\n"
            "        shell=False,\n"
            "        timeout=30,\n"
            "    )\n"
        ),
        path="/repo/runtime.py::safe_run",
        placement="function",
    )

    large = chunk(
        text=(
            "import subprocess\n"
            + (
                "# process monitoring safe command execution "
                "subprocess shell timeout\n"
                * 1400
            )
        ),
        path="/repo/runtime.py",
        placement="python_module",
    )

    small_score = _chunk_semantic_score(
        small,
        requirement(),
        plan(),
    )

    large_score = _chunk_semantic_score(
        large,
        requirement(),
        plan(),
    )

    print(
        "SMALL_SCORE=",
        small_score,
    )

    print(
        "LARGE_SCORE=",
        large_score,
    )

    assert small_score > large_score


def test_small_but_unrelated_python_does_not_get_free_relevance():
    useful = chunk(
        text=(
            "import subprocess\n\n"
            "def safe_run(argv):\n"
            "    return subprocess.run(\n"
            "        argv,\n"
            "        shell=False,\n"
            "        timeout=30,\n"
            "    )\n"
        ),
        path="/repo/runtime.py::safe_run",
        placement="function",
    )

    unrelated = chunk(
        text=(
            "def calculate_invoice_total(items):\n"
            "    return sum(items)\n"
        ),
        path="/repo/billing.py::calculate_invoice_total",
        placement="function",
    )

    useful_score = _chunk_semantic_score(
        useful,
        requirement(),
        plan(),
    )

    unrelated_score = _chunk_semantic_score(
        unrelated,
        requirement(),
        plan(),
    )

    assert useful_score > unrelated_score


def test_browser_target_does_not_receive_python_execution_bonus():
    browser = plan()
    browser.target_language = "javascript"
    browser.target_artifact = "browser_application"

    candidate = chunk(
        text=(
            "import subprocess\n\n"
            "def safe_run(argv):\n"
            "    return subprocess.run(argv)\n"
        ),
        path="/repo/runtime.py::safe_run",
        placement="function",
    )

    score = _chunk_semantic_score(
        candidate,
        requirement(),
        browser,
    )

    assert isinstance(
        score,
        float,
    )
