from __future__ import annotations

from types import SimpleNamespace

import sophyane.sli_semantic_intelligence as sem


def chunk(text: str):
    return SimpleNamespace(
        text=text,
        path="/tmp/example.py::candidate",
        language="python",
        source="regression",
        weight=1.0,
    )


def test_generic_process_word_does_not_prove_process_supervision():
    candidate = chunk(
        "def describe():\n"
        "    process = 'background process'\n"
        "    return process\n"
    )

    assert sem._strict_signal_count(
        candidate,
        "process_supervision",
    ) >= 1

    assert not sem._strict_has_discriminative_evidence(
        candidate,
        "process_supervision",
    )


def test_real_process_control_proves_process_supervision():
    candidate = chunk(
        "import subprocess\n"
        "\n"
        "def supervise(cmd):\n"
        "    proc = subprocess.Popen(cmd)\n"
        "    if proc.poll() is None:\n"
        "        proc.terminate()\n"
        "        proc.wait()\n"
    )

    assert sem._strict_strong_signal_count(
        candidate,
        "process_supervision",
    ) >= 1

    assert sem._strict_has_discriminative_evidence(
        candidate,
        "process_supervision",
    )


def test_generic_log_word_does_not_prove_log_diagnostics():
    candidate = chunk(
        "def label():\n"
        "    log = 'application log'\n"
        "    return log\n"
    )

    assert sem._strict_signal_count(
        candidate,
        "log_diagnostics",
    ) >= 1

    assert not sem._strict_has_discriminative_evidence(
        candidate,
        "log_diagnostics",
    )


def test_traceback_alone_does_not_prove_log_diagnostics():
    candidate = chunk(
        "def inspect_failure(text):\n"
        "    if 'Traceback' in text:\n"
        "        return text\n"
    )

    assert not sem._strict_has_discriminative_evidence(
        candidate,
        "log_diagnostics",
    )


def test_log_access_plus_traceback_proves_log_diagnostics():
    candidate = chunk(
        "from pathlib import Path\n"
        "\n"
        "def inspect_failure(path):\n"
        "    text = Path(path).read_text()\n"
        "    if 'Traceback' in text:\n"
        "        return text\n"
        "    return ''\n"
    )

    assert sem._strict_has_discriminative_evidence(
        candidate,
        "log_diagnostics",
    )


def test_if_and_match_do_not_prove_rules_validation():
    candidate = chunk(
        "def choose(value):\n"
        "    if value:\n"
        "        match = value\n"
        "        return match\n"
    )

    assert sem._strict_signal_count(
        candidate,
        "rules_and_validation",
    ) >= 2

    assert not sem._strict_has_discriminative_evidence(
        candidate,
        "rules_and_validation",
    )


def test_validate_proves_rules_validation_when_minimum_is_met():
    candidate = chunk(
        "def validate(value):\n"
        "    if value is None:\n"
        "        raise ValueError('invalid')\n"
        "    return value\n"
    )

    assert sem._strict_signal_count(
        candidate,
        "rules_and_validation",
    ) >= 2

    assert sem._strict_has_discriminative_evidence(
        candidate,
        "rules_and_validation",
    )


def test_memory_word_alone_does_not_prove_resource_diagnostics():
    candidate = chunk(
        "def describe():\n"
        "    memory = 'cached state'\n"
        "    return memory\n"
    )

    assert sem._strict_signal_count(
        candidate,
        "resource_diagnostics",
    ) >= 1

    assert not sem._strict_has_discriminative_evidence(
        candidate,
        "resource_diagnostics",
    )


def test_oom_proves_resource_diagnostics():
    candidate = chunk(
        "def diagnose(stderr):\n"
        "    return 'oom' in stderr.lower()\n"
    )

    assert sem._strict_has_discriminative_evidence(
        candidate,
        "resource_diagnostics",
    )


def test_safe_subprocess_run_proves_command_execution():
    candidate = chunk(
        "import subprocess\n"
        "\n"
        "def run(cmd):\n"
        "    return subprocess.run(\n"
        "        cmd,\n"
        "        shell=False,\n"
        "        check=True,\n"
        "        timeout=10,\n"
        "    )\n"
    )

    assert sem._strict_has_discriminative_evidence(
        candidate,
        "safe_command_execution",
    )
