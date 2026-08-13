from types import SimpleNamespace

import sophyane.sli_semantic_intelligence as sem


def chunk(text):
    return SimpleNamespace(
        text=text,
        path="/tmp/example.py::candidate",
        language="python",
        source="regression",
        weight=1.0,
    )


def test_plain_identifier_signal_does_not_match_inside_identifier():
    assert not sem._strict_signal_present(
        "detail='failure'",
        "tail",
    )

    assert not sem._strict_signal_present(
        "catalog = {}",
        "log",
    )

    assert not sem._strict_signal_present(
        "rapid = True",
        "pid",
    )


def test_plain_identifier_signal_still_matches_as_word():
    assert sem._strict_signal_present(
        "tail = lines[-100:]",
        "tail",
    )

    assert not sem._strict_signal_present(
        "write_log(message)",
        "log",
    )

    assert sem._strict_signal_present(
        "log(message)",
        "log",
    )

    assert sem._strict_signal_present(
        "process.pid",
        "pid",
    )


def test_call_shaped_signals_still_match():
    assert sem._strict_signal_present(
        "process.poll()",
        "poll(",
    )

    assert sem._strict_signal_present(
        "sock.bind(address)",
        "bind(",
    )

    assert sem._strict_signal_present(
        "def main(): pass",
        "main(",
    )


def test_assignment_shaped_signals_still_match():
    assert sem._strict_signal_present(
        "timeout=300",
        "timeout=",
    )

    assert sem._strict_signal_present(
        "shell=False",
        "shell=false",
    )


def test_qualified_call_signal_still_matches():
    assert sem._strict_signal_present(
        "subprocess.run(command)",
        "subprocess.run",
    )


def test_path_signal_still_matches():
    assert sem._strict_signal_present(
        'Path("/proc/meminfo")',
        "/proc/",
    )


def test_strict_signal_count_uses_boundary_semantics():
    candidate = chunk(
        """
def endpoint():
    detail = "Database not initialized"
    catalog = {}
    rapid = True
"""
    )

    assert sem._strict_signal_count(
        candidate,
        "log_diagnostics",
    ) == 0


def test_behavioral_log_group_rejects_detail_tail_collision():
    candidate = chunk(
        """
def endpoint():
    detail = "failure"
    try:
        work()
    except Exception:
        import traceback
        traceback.print_exc()
"""
    )

    groups = sem._strict_behavioral_group_hits(
        candidate,
        "log_diagnostics",
    )

    # Diagnostic/error evidence exists, but no genuine log-access role.
    assert not groups[0]
    assert groups[1]

    assert not sem._strict_has_discriminative_evidence(
        candidate,
        "log_diagnostics",
    )


def test_real_log_reader_preserves_behavioral_admission():
    candidate = chunk(
        """
def inspect_log(path):
    text = path.read_text()
    tail = text.splitlines()[-100:]

    for line in tail:
        if "Traceback" in line:
            return line

    return None
"""
    )

    groups = sem._strict_behavioral_group_hits(
        candidate,
        "log_diagnostics",
    )

    assert groups[0]
    assert groups[1]

    assert sem._strict_has_discriminative_evidence(
        candidate,
        "log_diagnostics",
    )
