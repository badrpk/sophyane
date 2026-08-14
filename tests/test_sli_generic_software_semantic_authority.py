from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import sophyane.sli_semantic_intelligence as sem
import sophyane.code_memory.compose as compose


LIVE = (
    "Provide a terminal-access agent with explicit safety guardrails "
    "to monitor long-running background processes or daemon crash logs, "
    "dynamically diagnose out-of-memory or port-binding conflicts, "
    "and execute safe corrective shell scripts."
)


def _chunk(
    text: str,
    *,
    language: str = "python",
    path: str = "agent.py",
):
    return SimpleNamespace(
        text=text,
        language=language,
        path=path,
        source="test",
        meta={},
    )


def test_final_compatibility_uses_ontology_signals_for_new_capability():
    plan = sem.build_semantic_plan(LIVE)

    chunk = _chunk(
        "import subprocess\n"
        "process = subprocess.Popen(argv)\n"
        "process.poll()\n"
    )

    assert sem._final_compatible(
        chunk,
        plan,
        "process_supervision",
    )


def test_safe_command_execution_can_use_generic_ontology_evidence():
    plan = sem.build_semantic_plan(LIVE)

    chunk = _chunk(
        "import shlex\n"
        "import subprocess\n"
        "argv = shlex.split(command)\n"
        "subprocess.run(argv, shell=False, timeout=30)\n"
    )

    assert sem._final_compatible(
        chunk,
        plan,
        "safe_command_execution",
    )


def test_terminal_agent_has_non_browser_software_target():
    language, artifact = sem.infer_target(LIVE)

    assert language == "python"
    assert artifact == "python_application"


def test_browser_request_still_has_browser_target():
    assert sem.infer_target(
        "Build a browser app for monitoring servers."
    ) == (
        "javascript",
        "browser_application",
    )


def test_informational_request_is_not_forced_to_python():
    assert sem.infer_target(
        "Explain how daemon process monitoring works."
    ) == (
        None,
        None,
    )


def test_non_browser_request_does_not_choose_html_from_incidental_chunk(
    tmp_path: Path,
    monkeypatch,
):
    python_chunk = SimpleNamespace(
        id="python-1",
        text=(
            "import subprocess\n"
            "def main():\n"
            "    subprocess.run(['true'], shell=False)\n"
            "if __name__ == '__main__':\n"
            "    main()\n"
        ),
        language="python",
        path="agent.py",
        source="test",
        meta={},
    )

    html_chunk = SimpleNamespace(
        id="html-1",
        text="<html><body>irrelevant</body></html>",
        language="html",
        path="index.html",
        source="test",
        meta={},
    )

    monkeypatch.setattr(
        compose,
        "retrieve_ranked",
        lambda *_args, **_kwargs: [
            (html_chunk, 0.99),
            (python_chunk, 0.98),
        ],
    )

    monkeypatch.setattr(
        compose,
        "apply_outcome",
        lambda *_args, **_kwargs: None,
    )

    report, _ = compose.compose_from_request(
        LIVE,
        tmp_path,
        store=SimpleNamespace(),
    )

    assert not (tmp_path / "index.html").exists()
    assert (tmp_path / "main.py").exists()
    assert report is not None
