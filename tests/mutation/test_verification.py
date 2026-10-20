"""Task 3: bounded checks and byte-faithful rollback evidence."""

from __future__ import annotations

import shutil
import subprocess
import time
import os
from pathlib import Path

import pytest

from sophyane.mutation.verification import StaticVerifier, build_reversal_patch


def _transaction(tmp_path: Path) -> tuple[Path, Path]:
    lab = tmp_path / "lab"
    transaction = lab / "transaction"
    transaction.mkdir(parents=True)
    return lab, transaction


def test_python_and_cpp_checks_aggregate_without_executing_candidate(tmp_path: Path) -> None:
    lab, transaction = _transaction(tmp_path)
    (transaction / "sample.py").write_text(
        "from pathlib import Path\nPath('executed').write_text('bad')\nVALUE = 1\n"
    )
    (transaction / "sample.cpp").write_text("int answer() { return 42; }\n")
    if shutil.which("clang++") is None:
        pytest.skip("clang++ unavailable")

    result = StaticVerifier(lab_root=lab).run(transaction, ("sample.cpp", "sample.py"), ("refactor",))

    assert result.ok and result.failure_boundary is None and result.diagnostics == ""
    assert result.checks == ("cpp:sample.cpp", "python:sample.py")
    assert not (transaction / "executed").exists()


def test_static_failure_fails_closed_and_records_check(tmp_path: Path) -> None:
    lab, transaction = _transaction(tmp_path)
    (transaction / "broken.py").write_text("def broken(:\n")

    result = StaticVerifier(lab_root=lab).run(transaction, ("broken.py",), ())

    assert not result.ok and result.failure_boundary == "python_syntax"
    assert result.checks == ("python:broken.py",)
    assert result.diagnostics


def test_cpp_warning_diagnostics_fail_closed(tmp_path: Path) -> None:
    if shutil.which("clang++") is None:
        pytest.skip("clang++ unavailable")
    lab, transaction = _transaction(tmp_path)
    (transaction / "sample.cpp").write_text("#warning verify this\nint answer() { return 42; }\n")

    result = StaticVerifier(lab_root=lab).run(transaction, ("sample.cpp",), ())

    assert not result.ok and result.failure_boundary == "cpp_syntax"
    assert "warning" in result.diagnostics


def test_regression_failure_fails_closed(tmp_path: Path) -> None:
    lab, transaction = _transaction(tmp_path)
    (transaction / "sample.py").write_text("VALUE = 1\n")

    result = StaticVerifier(lab_root=lab, regression_check=lambda path: False).run(
        transaction, ("sample.py",), ()
    )

    assert not result.ok and result.failure_boundary == "regression"
    assert result.checks == ("python:sample.py", "regression")


def test_regression_exception_fails_closed(tmp_path: Path) -> None:
    lab, transaction = _transaction(tmp_path)
    (transaction / "sample.py").write_text("VALUE = 1\n")

    def broken(path: Path) -> bool:
        raise RuntimeError("checker exploded")

    result = StaticVerifier(lab_root=lab, regression_check=broken).run(transaction, ("sample.py",), ())

    assert not result.ok and result.failure_boundary == "verifier_exception"
    assert "checker exploded" in result.diagnostics


def test_regression_timeout_is_bounded(tmp_path: Path) -> None:
    lab, transaction = _transaction(tmp_path)
    (transaction / "sample.py").write_text("VALUE = 1\n")

    def slow(path: Path) -> bool:
        time.sleep(2)
        return True

    start = time.monotonic()
    result = StaticVerifier(timeout_seconds=0.2, lab_root=lab, regression_check=slow).run(
        transaction, ("sample.py",), ()
    )

    assert time.monotonic() - start < 1.5
    assert not result.ok and result.failure_boundary == "timeout"
    assert result.checks == ("python:sample.py", "regression")


def test_rejects_path_escape_and_never_runs_intent_text(tmp_path: Path) -> None:
    lab, transaction = _transaction(tmp_path)
    (transaction / "sample.py").write_text("VALUE = 1\n")
    marker = tmp_path / "injected"
    intent = f"touch {marker}"

    accepted = StaticVerifier(lab_root=lab).run(transaction, ("sample.py",), (intent,))
    rejected = StaticVerifier(lab_root=lab).run(transaction, ("../outside.py",), ())

    assert accepted.ok and not marker.exists()
    assert not rejected.ok and rejected.failure_boundary == "verifier_path"


def test_reversal_patch_applies_exact_bytes_in_sorted_order(tmp_path: Path) -> None:
    baseline = {
        "z.py": b"first\nlast\n",
        "a.py": b"new\n",
        "gone.py": b"restored\n",
        "unchanged.py": b"same\n",
    }
    candidate = {
        "z.py": b"first\nchanged\n",
        "a.py": b"old\n",
        "added.py": b"remove me\n",
        "unchanged.py": b"same\n",
    }
    for name, content in candidate.items():
        (tmp_path / name).write_bytes(content)

    patch = build_reversal_patch(baseline, candidate)
    result = subprocess.run(
        ["git", "apply", "-p1", "-"],
        input=patch.encode(), cwd=tmp_path, capture_output=True, timeout=5,
    )

    assert result.returncode == 0, result.stderr.decode()
    assert {p.name: p.read_bytes() for p in tmp_path.iterdir() if p.is_file()} == baseline
    assert patch == build_reversal_patch(dict(reversed(list(baseline.items()))), candidate)
    assert patch.index("added.py") < patch.index("gone.py") < patch.index("z.py")


def test_reversal_patch_preserves_missing_final_newline(tmp_path: Path) -> None:
    baseline = {"sample.py": b"VALUE = 1"}
    candidate = {"sample.py": b"VALUE = 2"}
    (tmp_path / "sample.py").write_bytes(candidate["sample.py"])

    patch = build_reversal_patch(baseline, candidate)
    result = subprocess.run(
        ["patch", "-p1", "--batch", "--forward"],
        input=patch.encode(), cwd=tmp_path, capture_output=True, timeout=5,
    )

    assert result.returncode == 0, result.stderr.decode()
    assert (tmp_path / "sample.py").read_bytes() == baseline["sample.py"]


def test_reversal_patch_rejects_non_text_changes() -> None:
    with pytest.raises(ValueError, match="UTF-8"):
        build_reversal_patch({"sample.py": b"\xff"}, {"sample.py": b"\xfe"})


def test_reversal_patch_preserves_unicode_line_separator(tmp_path: Path) -> None:
    baseline = {"sample.py": "VALUE = 'a\u2028b'\n".encode()}
    candidate = {"sample.py": "VALUE = 'c\u2028d'\n".encode()}
    (tmp_path / "sample.py").write_bytes(candidate["sample.py"])

    patch = build_reversal_patch(baseline, candidate)
    result = subprocess.run(
        ["patch", "-p1", "--batch", "--forward"],
        input=patch.encode(), cwd=tmp_path, capture_output=True, timeout=5,
    )

    assert result.returncode == 0, result.stderr.decode()
    assert (tmp_path / "sample.py").read_bytes() == baseline["sample.py"]


def test_reversal_patch_rejects_header_injection() -> None:
    with pytest.raises(ValueError, match="patch path"):
        build_reversal_patch({"safe.py\n+++ b/other.py": b"good\n"}, {})


@pytest.mark.parametrize(
    ("baseline", "candidate"),
    [
        ({"empty.py": b""}, {}),
        ({}, {"empty.py": b""}),
        ({"sample.py": b"one\ntwo"}, {"sample.py": b"one\nchanged\n"}),
        ({"sample.py": b"one\ntwo\n"}, {"sample.py": b"one\nchanged"}),
    ],
)
def test_reversal_patch_restores_empty_files_and_line_endings(
    tmp_path: Path, baseline: dict[str, bytes], candidate: dict[str, bytes]
) -> None:
    for name, content in candidate.items():
        (tmp_path / name).write_bytes(content)

    patch = build_reversal_patch(baseline, candidate)
    result = subprocess.run(
        ["git", "apply", "-p1", "-"],
        input=patch.encode(), cwd=tmp_path, capture_output=True, timeout=5,
    )

    assert result.returncode == 0, result.stderr.decode()
    assert {p.name: p.read_bytes() for p in tmp_path.iterdir() if p.is_file()} == baseline


def test_static_checker_exception_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sophyane.mutation import verification

    lab, transaction = _transaction(tmp_path)
    (transaction / "sample.py").write_text("VALUE = 1\n")

    def broken(*args, **kwargs):
        raise OSError("checker unavailable")

    monkeypatch.setattr(verification.subprocess, "Popen", broken)
    result = StaticVerifier(lab_root=lab).run(transaction, ("sample.py",), ())

    assert not result.ok and result.failure_boundary == "verifier_exception"
    assert result.checks == ("python:sample.py",)
    assert "checker unavailable" in result.diagnostics


def test_transaction_must_be_inside_configured_lab_before_temp_write(tmp_path: Path) -> None:
    lab = tmp_path / "lab"
    lab.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "sample.py").write_text("VALUE = 1\n")

    result = StaticVerifier(lab_root=lab).run(outside, ("sample.py",), ())

    assert not result.ok and result.failure_boundary == "verifier_path"
    assert list(lab.iterdir()) == []


def test_transaction_root_itself_cannot_be_lab_root(tmp_path: Path) -> None:
    lab = tmp_path / "lab"
    lab.mkdir()

    result = StaticVerifier(lab_root=lab).run(lab, (), ())

    assert not result.ok and result.failure_boundary == "verifier_path"


def test_clang_lookup_ignores_attacker_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    lab, transaction = _transaction(tmp_path)
    (transaction / "sample.cpp").write_text("int answer() { return 42; }\n")
    attacker = tmp_path / "attacker"
    attacker.mkdir()
    (attacker / "clang++").write_text("#!/bin/sh\ntouch attacker-ran\nexit 0\n")
    (attacker / "clang++").chmod(0o755)
    monkeypatch.setenv("PATH", str(attacker))

    result = StaticVerifier(lab_root=lab).run(transaction, ("sample.cpp",), ())

    assert result.ok
    assert not (transaction / "attacker-ran").exists()


def test_checker_output_limit_fails_closed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from sophyane.mutation import verification

    lab, transaction = _transaction(tmp_path)
    (transaction / "sample.py").write_text("VALUE = 1\n")

    monkeypatch.setattr(
        verification,
        "_PYTHON_CHECK",
        f"import sys; sys.stdout.write('x' * {verification._MAX_CHECK_OUTPUT + 1})",
    )
    result = StaticVerifier(lab_root=lab).run(transaction, ("sample.py",), ())

    assert not result.ok and result.failure_boundary == "output_limit"


def test_regression_timeout_kills_descendant_process_group(tmp_path: Path) -> None:
    lab, transaction = _transaction(tmp_path)
    (transaction / "sample.py").write_text("VALUE = 1\n")
    pid_file = transaction / "child.pid"

    def spawns_child(path: Path) -> bool:
        child = subprocess.Popen(["sleep", "30"])
        path.joinpath("child.pid").write_text(str(child.pid))
        time.sleep(30)
        return True

    result = StaticVerifier(timeout_seconds=0.2, lab_root=lab, regression_check=spawns_child).run(
        transaction, ("sample.py",), ()
    )

    assert not result.ok and result.failure_boundary == "timeout"
    child_pid = int(pid_file.read_text())
    deadline = time.monotonic() + 1.0
    while time.monotonic() < deadline:
        try:
            os.kill(child_pid, 0)
        except ProcessLookupError:
            break
        state_path = Path(f"/proc/{child_pid}/stat")
        try:
            state = state_path.read_text().split()[2]
        except (FileNotFoundError, ProcessLookupError):
            break
        if state == "Z":
            break
        time.sleep(0.02)
    else:
        pytest.fail("regression descendant remained alive after timeout")


def test_reversal_patch_marks_changed_header_like_lines(tmp_path: Path) -> None:
    baseline = {"sample.py": b"+++ old\n--- old\n"}
    candidate = {"sample.py": b"+++ new\n--- new\n"}
    (tmp_path / "sample.py").write_bytes(candidate["sample.py"])

    patch = build_reversal_patch(baseline, candidate)
    result = subprocess.run(
        ["patch", "-p1", "--batch", "--forward"],
        input=patch.encode(), cwd=tmp_path, capture_output=True, timeout=5,
    )

    assert result.returncode == 0, result.stderr.decode()
    assert (tmp_path / "sample.py").read_bytes() == baseline["sample.py"]


def test_reversal_patch_preserves_no_newline_for_header_like_final_line(tmp_path: Path) -> None:
    baseline = {"sample.py": b"+++ old"}
    candidate = {"sample.py": b"+++ new"}
    (tmp_path / "sample.py").write_bytes(candidate["sample.py"])

    patch = build_reversal_patch(baseline, candidate)

    assert "\\ No newline at end of file" in patch
    result = subprocess.run(
        ["patch", "-p1", "--batch", "--forward"],
        input=patch.encode(), cwd=tmp_path, capture_output=True, timeout=5,
    )
    assert result.returncode == 0, result.stderr.decode()
    assert (tmp_path / "sample.py").read_bytes() == baseline["sample.py"]


def test_checker_leader_exit_cannot_leave_forked_descendant_running(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sophyane.mutation import verification

    lab, transaction = _transaction(tmp_path)
    (transaction / "sample.py").write_text("VALUE = 1\n")
    child_pid_file = transaction / "sample.py.child"
    monkeypatch.setattr(
        verification,
        "_PYTHON_CHECK",
        (
            "import os, sys, time; "
            "child = os.fork(); "
            "(open(sys.argv[1] + '.child', 'w').write(str(os.getpid())), time.sleep(30)) "
            "if child == 0 else None"
        ),
    )

    result = StaticVerifier(timeout_seconds=0.2, lab_root=lab).run(
        transaction, ("sample.py",), ()
    )

    assert not result.ok and result.failure_boundary == "timeout"
    child_pid = int(child_pid_file.read_text())
    deadline = time.monotonic() + 1.0
    while time.monotonic() < deadline:
        try:
            os.kill(child_pid, 0)
        except ProcessLookupError:
            break
        state_path = Path(f"/proc/{child_pid}/stat")
        if not state_path.exists() or state_path.read_text().split()[2] == "Z":
            break
        time.sleep(0.02)
    else:
        pytest.fail("checker descendant remained alive after timeout cleanup")


def test_checker_descendant_output_after_leader_exit_hits_output_limit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sophyane.mutation import verification

    lab, transaction = _transaction(tmp_path)
    (transaction / "sample.py").write_text("VALUE = 1\n")
    child_pid_file = transaction / "sample.py.child"
    monkeypatch.setattr(
        verification,
        "_PYTHON_CHECK",
        (
            "import os, sys, time; "
            "child = os.fork(); "
            "(open(sys.argv[1] + '.child', 'w').write(str(os.getpid())), "
            "time.sleep(0.05), sys.stdout.write('x' * "
            f"{verification._MAX_CHECK_OUTPUT + 1}" "), sys.stdout.flush(), time.sleep(30)) "
            "if child == 0 else None"
        ),
    )
    selector_type = verification.selectors.DefaultSelector
    original_select = selector_type.select
    delayed = False

    def delay_first_select(selector, timeout=None):
        nonlocal delayed
        if not delayed:
            delayed = True
            time.sleep(0.1)
            return []
        return original_select(selector, timeout)

    monkeypatch.setattr(selector_type, "select", delay_first_select)

    result = StaticVerifier(timeout_seconds=0.5, lab_root=lab).run(
        transaction, ("sample.py",), ()
    )

    assert not result.ok and result.failure_boundary == "output_limit"
    child_pid = int(child_pid_file.read_text())
    deadline = time.monotonic() + 1.0
    while time.monotonic() < deadline:
        try:
            os.kill(child_pid, 0)
        except ProcessLookupError:
            break
        state_path = Path(f"/proc/{child_pid}/stat")
        try:
            state = state_path.read_text().split()[2]
        except (FileNotFoundError, ProcessLookupError):
            break
        if state == "Z":
            break
        time.sleep(0.02)
    else:
        pytest.fail("checker descendant remained alive after output-limit cleanup")
