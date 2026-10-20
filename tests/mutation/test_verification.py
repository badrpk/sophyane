"""Task 3: bounded checks and byte-faithful rollback evidence."""

from __future__ import annotations

import shutil
import subprocess
import time
from pathlib import Path

import pytest

from sophyane.mutation.verification import StaticVerifier, build_reversal_patch


def test_python_and_cpp_checks_aggregate_without_executing_candidate(tmp_path: Path) -> None:
    (tmp_path / "sample.py").write_text(
        "from pathlib import Path\nPath('executed').write_text('bad')\nVALUE = 1\n"
    )
    (tmp_path / "sample.cpp").write_text("int answer() { return 42; }\n")
    if shutil.which("clang++") is None:
        pytest.skip("clang++ unavailable")

    result = StaticVerifier().run(tmp_path, ("sample.cpp", "sample.py"), ("refactor",))

    assert result.ok and result.failure_boundary is None and result.diagnostics == ""
    assert result.checks == ("cpp:sample.cpp", "python:sample.py")
    assert not (tmp_path / "executed").exists()


def test_static_failure_fails_closed_and_records_check(tmp_path: Path) -> None:
    (tmp_path / "broken.py").write_text("def broken(:\n")

    result = StaticVerifier().run(tmp_path, ("broken.py",), ())

    assert not result.ok and result.failure_boundary == "python_syntax"
    assert result.checks == ("python:broken.py",)
    assert result.diagnostics


def test_cpp_warning_diagnostics_fail_closed(tmp_path: Path) -> None:
    if shutil.which("clang++") is None:
        pytest.skip("clang++ unavailable")
    (tmp_path / "sample.cpp").write_text("#warning verify this\nint answer() { return 42; }\n")

    result = StaticVerifier().run(tmp_path, ("sample.cpp",), ())

    assert not result.ok and result.failure_boundary == "cpp_syntax"
    assert "warning" in result.diagnostics


def test_regression_failure_fails_closed(tmp_path: Path) -> None:
    (tmp_path / "sample.py").write_text("VALUE = 1\n")

    result = StaticVerifier(regression_check=lambda path: False).run(
        tmp_path, ("sample.py",), ()
    )

    assert not result.ok and result.failure_boundary == "regression"
    assert result.checks == ("python:sample.py", "regression")


def test_regression_exception_fails_closed(tmp_path: Path) -> None:
    (tmp_path / "sample.py").write_text("VALUE = 1\n")

    def broken(path: Path) -> bool:
        raise RuntimeError("checker exploded")

    result = StaticVerifier(regression_check=broken).run(tmp_path, ("sample.py",), ())

    assert not result.ok and result.failure_boundary == "verifier_exception"
    assert "checker exploded" in result.diagnostics


def test_regression_timeout_is_bounded(tmp_path: Path) -> None:
    (tmp_path / "sample.py").write_text("VALUE = 1\n")

    def slow(path: Path) -> bool:
        time.sleep(2)
        return True

    start = time.monotonic()
    result = StaticVerifier(timeout_seconds=0.2, regression_check=slow).run(
        tmp_path, ("sample.py",), ()
    )

    assert time.monotonic() - start < 1.5
    assert not result.ok and result.failure_boundary == "timeout"
    assert result.checks == ("python:sample.py", "regression")


def test_rejects_path_escape_and_never_runs_intent_text(tmp_path: Path) -> None:
    (tmp_path / "sample.py").write_text("VALUE = 1\n")
    marker = tmp_path / "injected"
    intent = f"touch {marker}"

    accepted = StaticVerifier().run(tmp_path, ("sample.py",), (intent,))
    rejected = StaticVerifier().run(tmp_path, ("../outside.py",), ())

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

    (tmp_path / "sample.py").write_text("VALUE = 1\n")

    def broken(*args, **kwargs):
        raise OSError("checker unavailable")

    monkeypatch.setattr(verification.subprocess, "run", broken)
    result = StaticVerifier().run(tmp_path, ("sample.py",), ())

    assert not result.ok and result.failure_boundary == "verifier_exception"
    assert result.checks == ("python:sample.py",)
    assert "checker unavailable" in result.diagnostics
