"""Bounded static checks and deterministic candidate-to-baseline patches."""

from __future__ import annotations

import difflib
import math
import multiprocessing
from multiprocessing.connection import Connection
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Mapping, Sequence

from .containment import LabPathError, _relative_path


@dataclass(frozen=True)
class VerificationEvidence:
    ok: bool
    checks: tuple[str, ...]
    failure_boundary: str | None
    diagnostics: str


_PYTHON_CHECK = (
    "from pathlib import Path; import sys; "
    "compile(Path(sys.argv[1]).read_bytes(), sys.argv[1], 'exec', dont_inherit=True)"
)
_CPP_SUFFIXES = frozenset({".cc", ".cpp", ".cxx", ".h", ".hh", ".hpp", ".hxx"})


def _regression_worker(check: Callable[[Path], bool], path: Path, sender: Connection) -> None:
    try:
        sender.send(("result", check(path) is True))
    except BaseException as error:
        sender.send(("exception", f"{type(error).__name__}: {error}"[:4096]))
    finally:
        sender.close()


class StaticVerifier:
    """Run only fixed syntax checks on regular files in one transaction root.

    ``intents`` describe the requested change; they never select commands.
    The optional regression callback is engine-injected and runs in a child
    process so its timeout can be enforced even if it blocks.
    """

    def __init__(
        self,
        timeout_seconds: float = 30.0,
        regression_check: Callable[[Path], bool] | None = None,
    ) -> None:
        self.timeout_seconds = timeout_seconds
        self.regression_check = regression_check

    @staticmethod
    def _checked_file(root: Path, name: str) -> Path:
        relative = _relative_path(name)
        cursor = root
        for part in relative.parts:
            cursor = cursor / part
            info = cursor.lstat()
            if stat.S_ISLNK(info.st_mode):
                raise LabPathError(f"transaction path contains symlink: {name!r}")
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            raise LabPathError(f"transaction file is not a single-link regular file: {name!r}")
        if not cursor.resolve(strict=True).is_relative_to(root):
            raise LabPathError(f"path escapes transaction: {name!r}")
        return cursor

    @staticmethod
    def _environment(scratch: Path) -> dict[str, str]:
        return {
            "PATH": os.defpath,
            "HOME": str(scratch),
            "TMPDIR": str(scratch),
            "XDG_CACHE_HOME": str(scratch),
            "PYTHONDONTWRITEBYTECODE": "1",
            "LC_ALL": "C",
        }

    def _run_regression(self, root: Path, deadline: float) -> tuple[str, str]:
        assert self.regression_check is not None
        context = multiprocessing.get_context("fork")
        receiver, sender = context.Pipe(duplex=False)
        process = context.Process(
            target=_regression_worker, args=(self.regression_check, root, sender), daemon=True
        )
        try:
            process.start()
            sender.close()
            remaining = deadline - time.monotonic()
            if remaining <= 0 or not receiver.poll(remaining):
                if process.is_alive():
                    return "timeout", "regression check timed out"
                return "verifier_exception", "regression check exited without evidence"
            kind, value = receiver.recv()
            if kind == "exception":
                return "verifier_exception", value
            if value is not True:
                return "regression", "regression check returned false"
            return "", ""
        finally:
            if process.is_alive():
                process.terminate()
                process.join(timeout=0.1)
                if process.is_alive():
                    process.kill()
            if process.pid is not None:
                process.join(timeout=0.1)
            receiver.close()
            sender.close()

    def run(
        self,
        transaction_path: Path,
        changed_paths: Sequence[str],
        intents: Sequence[str],
    ) -> VerificationEvidence:
        checks: list[str] = []
        try:
            if not math.isfinite(self.timeout_seconds) or self.timeout_seconds <= 0:
                return VerificationEvidence(False, (), "timeout", "invalid verification timeout")
            deadline = time.monotonic() + self.timeout_seconds
            root = Path(transaction_path).absolute()
            if not stat.S_ISDIR(root.lstat().st_mode) or root.is_symlink():
                raise LabPathError("transaction root is not a regular directory")
            paths = sorted(set(changed_paths))
            if not paths:
                raise LabPathError("no changed paths to verify")
            for name in paths:
                self._checked_file(root, name)

            failures: list[tuple[str, str]] = []
            with tempfile.TemporaryDirectory(prefix="verification-", dir=root) as scratch_name:
                scratch = Path(scratch_name)
                environment = self._environment(scratch)
                for name in paths:
                    suffix = Path(name).suffix.lower()
                    if suffix == ".py":
                        kind = "python"
                        command = [sys.executable, "-I", "-c", _PYTHON_CHECK, name]
                    elif suffix in _CPP_SUFFIXES:
                        kind = "cpp"
                        compiler = shutil.which("clang++")
                        if compiler is None:
                            checks.append(f"cpp:{name}")
                            failures.append(("cpp_tool", "clang++ is unavailable"))
                            continue
                        command = [compiler, "-std=c++17", "-fsyntax-only", "-x", "c++", "--", name]
                    else:
                        checks.append(f"unsupported:{name}")
                        failures.append(("verifier_path", f"unsupported source type: {name}"))
                        continue
                    checks.append(f"{kind}:{name}")
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        return VerificationEvidence(False, tuple(checks), "timeout", "static checks timed out")
                    try:
                        result = subprocess.run(
                            command, cwd=root, env=environment, capture_output=True,
                            timeout=remaining, check=False,
                        )
                    except subprocess.TimeoutExpired:
                        return VerificationEvidence(False, tuple(checks), "timeout", "static checks timed out")
                    if result.returncode != 0 or (kind == "cpp" and result.stderr.strip()):
                        detail = result.stderr.decode("utf-8", errors="replace").strip()
                        failures.append((
                            f"{kind}_syntax", detail[:4096] or f"{kind} checker exited {result.returncode}"
                        ))
            if failures:
                return VerificationEvidence(
                    False, tuple(checks), failures[0][0],
                    "\n".join(detail for _, detail in failures),
                )
            if self.regression_check is not None:
                checks.append("regression")
                boundary, detail = self._run_regression(root, deadline)
                if boundary:
                    return VerificationEvidence(False, tuple(checks), boundary, detail)
            return VerificationEvidence(True, tuple(checks), None, "")
        except LabPathError as error:
            return VerificationEvidence(False, tuple(checks), "verifier_path", str(error))
        except Exception as error:
            return VerificationEvidence(
                False, tuple(checks), "verifier_exception", f"{type(error).__name__}: {error}"
            )


def _patch_lines(content: bytes | None) -> list[str]:
    if content is None:
        return []
    pieces = content.decode("utf-8").split("\n")
    lines = [piece + "\n" for piece in pieces[:-1]]
    if pieces[-1]:
        lines.append(pieces[-1])
    return lines


def build_reversal_patch(baseline: Mapping[str, bytes], candidate: Mapping[str, bytes]) -> str:
    """Return a stable unified patch that transforms candidate into baseline."""
    chunks: list[str] = []
    for name in sorted(set(baseline) | set(candidate)):
        _relative_path(name)
        if any(ord(char) < 32 or char in "\x7f\x85\u2028\u2029" for char in name):
            raise ValueError(f"invalid patch path: {name!r}")
        before = candidate.get(name)
        after = baseline.get(name)
        if before == after:
            continue
        try:
            old_lines = _patch_lines(before)
            new_lines = _patch_lines(after)
        except UnicodeDecodeError as error:
            raise ValueError(f"reversal patch requires UTF-8 text: {name}") from error
        if (before is not None and b"\x00" in before) or (after is not None and b"\x00" in after):
            raise ValueError(f"reversal patch requires UTF-8 text: {name}")
        fromfile = f"a/{name}" if before is not None else "/dev/null"
        tofile = f"b/{name}" if after is not None else "/dev/null"
        if before is None and after == b"":
            chunks.append(
                f"diff --git a/{name} b/{name}\n"
                "new file mode 100644\n"
                "index 0000000..e69de29\n"
            )
            continue
        if before == b"" and after is None:
            chunks.append(
                f"diff --git a/{name} b/{name}\n"
                "deleted file mode 100644\n"
                "index e69de29..0000000\n"
            )
            continue
        for line in difflib.unified_diff(old_lines, new_lines, fromfile, tofile, lineterm="\n"):
            if line.startswith(("--- ", "+++ ", "@@ ")) or line.endswith("\n"):
                chunks.append(line)
            else:
                chunks.append(f"{line}\n\\ No newline at end of file\n")
    return "".join(chunks)
