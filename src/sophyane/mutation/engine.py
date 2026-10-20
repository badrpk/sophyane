"""Fail-closed orchestration of source snapshots and lab-only mutations."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import shutil
import stat
from typing import Mapping

from .adapters import AnalysisResult, CppAdapter, PythonAdapter
from .containment import DEFAULT_LAB_ROOT, LabPathError, LabTransaction, MutationLab, _relative_path
from .hashing import semantic_diff_hash, semantic_tree_hash
from .models import MutationIntent, MutationProposal, MutationResult
from .verification import StaticVerifier, build_reversal_patch


_CPP_SUFFIXES = frozenset({".cc", ".cpp", ".cxx", ".h", ".hh", ".hpp", ".hxx"})


class _MutationFailure(Exception):
    def __init__(self, boundary: str, detail: str = "") -> None:
        super().__init__(detail)
        self.boundary = boundary


class MutationEngine:
    """Accept a validated lab artifact or restore its original snapshot."""

    def __init__(
        self,
        lab_root: Path = DEFAULT_LAB_ROOT,
        language_adapters: Mapping[str, object] | None = None,
        verifier: StaticVerifier | None = None,
    ) -> None:
        self.lab_root = Path(lab_root)
        self.lab = MutationLab(self.lab_root)
        self.language_adapters = dict(language_adapters) if language_adapters is not None else {
            ".py": PythonAdapter(),
            "cpp": CppAdapter(),
        }
        self.verifier = verifier

    def _adapter_for(self, name: str) -> object:
        suffix = Path(name).suffix.lower()
        language = "python" if suffix == ".py" else "cpp" if suffix in _CPP_SUFFIXES else ""
        adapter = self.language_adapters.get(suffix) or self.language_adapters.get(language)
        if adapter is None:
            raise _MutationFailure("adapter", f"no adapter for {name!r}")
        return adapter

    def _validate_proposal(self, intent: MutationIntent, proposal: MutationProposal) -> None:
        try:
            allowed = {_relative_path(name).as_posix() for name in intent.allowed_paths}
            if not proposal.replacements:
                raise LabPathError("proposal has no replacements")
            for name, value in proposal.replacements.items():
                normalized = _relative_path(name).as_posix()
                if "\x00" in normalized or normalized not in allowed:
                    raise LabPathError(f"path is not in the allowlist: {name!r}")
                if not isinstance(value, str):
                    raise LabPathError("replacement values must be text")
                self._adapter_for(normalized)
        except (LabPathError, _MutationFailure, TypeError, ValueError) as error:
            raise _MutationFailure("proposal", str(error)) from error

    def _analyze(
        self, transaction: LabTransaction, paths: tuple[str, ...], *, candidate: bool,
        invariants: tuple[str, ...],
    ) -> tuple[AnalysisResult, ...]:
        results: list[AnalysisResult] = []
        for name in paths:
            path = transaction.path / name
            adapter = self._adapter_for(name)
            analysis = adapter.analyze(path, ())
            if not isinstance(analysis, AnalysisResult):
                raise _MutationFailure("analysis", f"adapter returned no analysis for {name!r}")
            if Path(analysis.path) != path:
                raise _MutationFailure("analysis", f"adapter reported a different path for {name!r}")
            if not analysis.ok or not analysis.semantic_digest:
                raise _MutationFailure(analysis.failure_boundary or "analysis", analysis.diagnostics)
            results.append(replace(analysis, path=name))

        if candidate:
            for invariant in invariants:
                failures: list[AnalysisResult] = []
                for name in paths:
                    checked = self._adapter_for(name).analyze(transaction.path / name, (invariant,))
                    if not isinstance(checked, AnalysisResult):
                        raise _MutationFailure("analysis", "adapter returned no invariant evidence")
                    if checked.ok:
                        break
                    failures.append(checked)
                else:
                    first = failures[0]
                    raise _MutationFailure(first.failure_boundary or "analysis", first.diagnostics)
        return tuple(results)

    def _bounded_verifier(self, timeout_seconds: float) -> StaticVerifier:
        if self.verifier is None:
            return StaticVerifier(timeout_seconds=timeout_seconds, lab_root=self.lab_root)
        if type(self.verifier) is StaticVerifier:
            return StaticVerifier(
                timeout_seconds=min(timeout_seconds, self.verifier.timeout_seconds),
                regression_check=self.verifier.regression_check,
                lab_root=self.lab_root,
            )
        return self.verifier

    def _rebuild_owned_transaction(self, transaction: LabTransaction) -> None:
        """Recover a poisoned candidate without following any path it contains."""
        root = transaction.path
        lab = self.lab.lab_root.resolve(strict=True)
        if (
            root.parent != lab
            or not root.name.startswith("mutation-")
            or not stat.S_ISDIR(root.lstat().st_mode)
        ):
            raise LabPathError("rollback target is not an owned lab transaction")
        baseline = transaction.baseline_files
        transaction.close()
        shutil.rmtree(root)
        root.mkdir(mode=0o700)
        for name, content in baseline.items():
            target = root.joinpath(*_relative_path(name).parts)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(content)

    def mutate(
        self,
        intent: MutationIntent,
        proposal: MutationProposal,
        *,
        timeout_seconds: float = 30.0,
    ) -> MutationResult:
        transaction: LabTransaction | None = None
        boundary = "snapshot"
        checks: tuple[str, ...] = ()
        baseline_hash = candidate_hash = diff_hash = ""
        candidate = None
        try:
            boundary = "proposal"
            self._validate_proposal(intent, proposal)
            boundary = "snapshot"
            transaction = self.lab.create_transaction(intent.source_root)
            baseline = transaction.baseline_files
            changed_paths = tuple(sorted(
                name for name, text in proposal.replacements.items()
                if baseline.get(name) != text.encode("utf-8")
            ))
            if not changed_paths:
                raise _MutationFailure("proposal", "proposal changes no files")
            boundary = "analysis_exception"
            before = self._analyze(transaction, changed_paths, candidate=False, invariants=())
            baseline_hash = semantic_tree_hash(before)
            boundary = "apply"
            transaction.apply_replacements(proposal.replacements, intent.allowed_paths)
            candidate = transaction.snapshot()
            boundary = "analysis_exception"
            after = self._analyze(transaction, changed_paths, candidate=True, invariants=intent.invariants)
            candidate_hash = semantic_tree_hash(after)
            diff_hash = semantic_diff_hash(
                {result.path: result.semantic_digest for result in before if result.semantic_digest},
                {result.path: result.semantic_digest for result in after if result.semantic_digest},
            )
            boundary = "verifier_exception"
            evidence = self._bounded_verifier(timeout_seconds).run(
                transaction.path, changed_paths, (intent.summary,)
            )
            checks = evidence.checks
            if not evidence.ok:
                raise _MutationFailure(evidence.failure_boundary or "verification", evidence.diagnostics)
            boundary = "verifier_mutation"
            if transaction.snapshot() != candidate:
                raise _MutationFailure("verifier_mutation", "verifier changed the lab candidate")
            return MutationResult(
                "accepted", transaction.transaction_id, transaction.path,
                baseline_hash, candidate_hash, diff_hash, "", None, checks,
            )
        except Exception as error:
            failure_boundary = error.boundary if isinstance(error, _MutationFailure) else boundary
            patch = ""
            if transaction is not None:
                try:
                    try:
                        failed_candidate = transaction.snapshot()
                    except Exception:
                        if candidate is None:
                            raise
                        failed_candidate = candidate
                    patch = build_reversal_patch(transaction.baseline_files, failed_candidate)
                except Exception:
                    failure_boundary = "reversal_evidence"
                try:
                    transaction.restore_baseline()
                except Exception:
                    try:
                        self._rebuild_owned_transaction(transaction)
                    except Exception:
                        failure_boundary = "rollback_exception"
            return MutationResult(
                "reversed",
                transaction.transaction_id if transaction is not None else "",
                transaction.path if transaction is not None else self.lab_root,
                baseline_hash, candidate_hash, diff_hash, patch, failure_boundary, checks,
            )
        finally:
            if transaction is not None:
                transaction.close()
