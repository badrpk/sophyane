"""Task 4: mutation orchestration stays inside the lab and fails closed."""

from __future__ import annotations

from pathlib import Path

import pytest

from sophyane.mutation import MutationIntent, MutationProposal
from sophyane.mutation.adapters import AnalysisResult
from sophyane.mutation.containment import LabTransaction
from sophyane.mutation.engine import MutationEngine
from sophyane.mutation.hashing import semantic_diff_hash, semantic_tree_hash
from sophyane.mutation.verification import StaticVerifier, VerificationEvidence


def _source(tmp_path: Path) -> Path:
    root = tmp_path / "source"
    (root / "pkg").mkdir(parents=True)
    (root / "pkg" / "first.py").write_text("VALUE = 1\n")
    (root / "pkg" / "second.py").write_text("from .first import VALUE\nANSWER = VALUE\n")
    return root


def _intent(source: Path, *paths: str, invariants: tuple[str, ...] = ()) -> MutationIntent:
    return MutationIntent("refactor", source, paths, invariants)


def _source_bytes(source: Path) -> dict[str, bytes]:
    return {path.relative_to(source).as_posix(): path.read_bytes() for path in source.rglob("*") if path.is_file()}


def test_multi_file_acceptance_preserves_source_and_returns_relative_semantic_evidence(
    tmp_path: Path,
) -> None:
    source = _source(tmp_path)
    before = _source_bytes(source)
    edits = {
        "pkg/first.py": "VALUE = 2\n",
        "pkg/second.py": "from .first import VALUE\nANSWER = VALUE + 1\n",
    }
    engine = MutationEngine(lab_root=tmp_path / "lab")

    result = engine.mutate(_intent(source, *edits), MutationProposal(edits, "planner"))

    assert result.status == "accepted", result.failure_boundary
    assert result.transaction_id and result.lab_path.parent == tmp_path / "lab"
    assert result.lab_path.name.endswith(result.transaction_id)
    assert _source_bytes(source) == before
    assert _source_bytes(result.lab_path) == {**before, **{key: value.encode() for key, value in edits.items()}}
    assert result.reversal_patch == "" and result.failure_boundary is None
    assert result.checks == ("python:pkg/first.py", "python:pkg/second.py")
    assert len(result.baseline_hash) == len(result.candidate_hash) == len(result.semantic_diff_hash) == 64
    assert result.baseline_hash != result.candidate_hash


def test_hashes_are_computed_from_transaction_relative_adapter_paths(tmp_path: Path) -> None:
    source = _source(tmp_path)
    name = "pkg/first.py"

    class AbsolutePathAdapter:
        def analyze(self, path: Path, invariants: tuple[str, ...]) -> AnalysisResult:
            digest = "before" if path.read_text() == "VALUE = 1\n" else "after"
            return AnalysisResult("python", str(path), True, digest, None, "")

    engine = MutationEngine(
        lab_root=tmp_path / "lab", language_adapters={".py": AbsolutePathAdapter()}
    )
    result = engine.mutate(_intent(source, name), MutationProposal({name: "VALUE = 2\n"}, "planner"))

    assert result.status == "accepted", result.failure_boundary
    assert result.baseline_hash == semantic_tree_hash((AnalysisResult("python", name, True, "before", None, ""),))
    assert result.candidate_hash == semantic_tree_hash((AnalysisResult("python", name, True, "after", None, ""),))
    assert result.semantic_diff_hash == semantic_diff_hash({name: "before"}, {name: "after"})


@pytest.mark.parametrize("bad_path", ["../escape.py", "/absolute.py", "pkg/second.py"])
def test_invalid_proposal_is_rejected_before_any_lab_write(tmp_path: Path, bad_path: str) -> None:
    source = _source(tmp_path)
    before = _source_bytes(source)
    lab = tmp_path / "lab"
    result = MutationEngine(lab_root=lab).mutate(
        _intent(source, "pkg/first.py"), MutationProposal({bad_path: "VALUE = 2\n"}, "planner")
    )

    assert result.status == "reversed" and result.failure_boundary == "proposal"
    assert result.transaction_id == "" and result.reversal_patch == ""
    assert not lab.exists()
    assert _source_bytes(source) == before


def test_non_text_replacement_is_rejected_before_any_lab_write(tmp_path: Path) -> None:
    source = _source(tmp_path)
    lab = tmp_path / "lab"
    result = MutationEngine(lab_root=lab).mutate(
        _intent(source, "pkg/first.py"), MutationProposal({"pkg/first.py": b"VALUE = 2\n"}, "planner")  # type: ignore[arg-type]
    )

    assert result.status == "reversed" and result.failure_boundary == "proposal"
    assert not lab.exists()


def test_syntax_failure_reverses_candidate_and_emits_patch(tmp_path: Path) -> None:
    source = _source(tmp_path)
    before = _source_bytes(source)
    result = MutationEngine(lab_root=tmp_path / "lab").mutate(
        _intent(source, "pkg/first.py"),
        MutationProposal({"pkg/first.py": "def broken(:\n"}, "planner"),
    )

    assert result.status == "reversed" and result.failure_boundary == "python_syntax"
    assert "-def broken(:" in result.reversal_patch and "+VALUE = 1" in result.reversal_patch
    assert _source_bytes(result.lab_path) == before
    assert _source_bytes(source) == before


def test_invariant_failure_reverses_candidate(tmp_path: Path) -> None:
    source = _source(tmp_path)
    before = _source_bytes(source)
    result = MutationEngine(lab_root=tmp_path / "lab").mutate(
        _intent(source, "pkg/first.py", invariants=("function:required",)),
        MutationProposal({"pkg/first.py": "def renamed():\n    return 1\n"}, "planner"),
    )

    assert result.status == "reversed" and result.failure_boundary == "python_invariant"
    assert result.reversal_patch
    assert _source_bytes(result.lab_path) == _source_bytes(source) == before


def test_regression_failure_reverses_after_static_checks(tmp_path: Path) -> None:
    source = _source(tmp_path)
    before = _source_bytes(source)
    lab = tmp_path / "lab"
    verifier = StaticVerifier(lab_root=lab, regression_check=lambda path: False)
    result = MutationEngine(lab_root=lab, verifier=verifier).mutate(
        _intent(source, "pkg/first.py"),
        MutationProposal({"pkg/first.py": "VALUE = 3\n"}, "planner"),
    )

    assert result.status == "reversed" and result.failure_boundary == "regression"
    assert result.checks == ("python:pkg/first.py", "regression")
    assert result.reversal_patch
    assert _source_bytes(result.lab_path) == _source_bytes(source) == before


def test_partial_write_exception_restores_baseline(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    source = _source(tmp_path)
    before = _source_bytes(source)
    original = LabTransaction._atomic_replace_text
    writes = 0

    def fail_second(self: LabTransaction, name: str, text: str) -> None:
        nonlocal writes
        writes += 1
        if writes == 2:
            raise OSError("injected write failure")
        original(self, name, text)

    monkeypatch.setattr(LabTransaction, "_atomic_replace_text", fail_second)
    result = MutationEngine(lab_root=tmp_path / "lab").mutate(
        _intent(source, "pkg/first.py", "pkg/second.py"),
        MutationProposal({"pkg/first.py": "VALUE = 2\n", "pkg/second.py": "ANSWER = 2\n"}, "planner"),
    )

    assert result.status == "reversed" and result.failure_boundary == "apply"
    assert result.reversal_patch
    assert _source_bytes(result.lab_path) == _source_bytes(source) == before


def test_verifier_exception_reverses_candidate(tmp_path: Path) -> None:
    source = _source(tmp_path)
    before = _source_bytes(source)

    class ExplodingVerifier:
        def run(self, transaction_path: Path, changed_paths: tuple[str, ...], intents: tuple[str, ...]) -> object:
            raise RuntimeError("verification unavailable")

    result = MutationEngine(lab_root=tmp_path / "lab", verifier=ExplodingVerifier()).mutate(  # type: ignore[arg-type]
        _intent(source, "pkg/first.py"), MutationProposal({"pkg/first.py": "VALUE = 2\n"}, "planner")
    )

    assert result.status == "reversed" and result.failure_boundary == "verifier_exception"
    assert result.reversal_patch and _source_bytes(result.lab_path) == before
    assert _source_bytes(source) == before


def test_unsafe_lab_entry_left_by_verifier_is_restored_without_following_link(tmp_path: Path) -> None:
    source = _source(tmp_path)
    before = _source_bytes(source)
    outside = tmp_path / "outside.txt"
    outside.write_text("untouched\n")

    class SwappingVerifier:
        def run(self, transaction_path: Path, changed_paths: tuple[str, ...], intents: tuple[str, ...]) -> VerificationEvidence:
            target = transaction_path / changed_paths[0]
            target.unlink()
            target.symlink_to(outside)
            return VerificationEvidence(True, ("injected",), None, "")

    result = MutationEngine(lab_root=tmp_path / "lab", verifier=SwappingVerifier()).mutate(  # type: ignore[arg-type]
        _intent(source, "pkg/first.py"), MutationProposal({"pkg/first.py": "VALUE = 2\n"}, "planner")
    )

    assert result.status == "reversed"
    assert not (result.lab_path / "pkg/first.py").is_symlink()
    assert _source_bytes(result.lab_path) == _source_bytes(source) == before
    assert outside.read_text() == "untouched\n"
