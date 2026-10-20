"""Bounded static checks and deterministic candidate-to-baseline patches."""

from __future__ import annotations

import difflib
import math
import multiprocessing
from multiprocessing.connection import Connection
import os
import selectors
import shutil
import stat
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Mapping, Sequence

from .containment import DEFAULT_LAB_ROOT, LabPathError, _relative_path


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
_MAX_CHECK_OUTPUT = 64 * 1024


def _regression_worker(check: Callable[[Path], bool], path: Path, sender: Connection) -> None:
    try:
        os.setsid()
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
        lab_root: Path = DEFAULT_LAB_ROOT,
    ) -> None:
        self.timeout_seconds = timeout_seconds
        self.regression_check = regression_check
        self.lab_root = Path(lab_root)

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

    def _validate_transaction(self, transaction_path: Path, deadline: float) -> Path:
        if time.monotonic() >= deadline:
            raise TimeoutError("transaction validation timed out")
        lab = self.lab_root.absolute().resolve(strict=True)
        root = Path(transaction_path).absolute().resolve(strict=True)
        if time.monotonic() >= deadline:
            raise TimeoutError("transaction validation timed out")
        if root == lab or not root.is_relative_to(lab):
            raise LabPathError("transaction path is outside configured mutation lab")
        if not stat.S_ISDIR(root.lstat().st_mode):
            raise LabPathError("transaction root is not a directory")
        return root

    @staticmethod
    def _kill_process_group(process: subprocess.Popen[bytes]) -> None:
        try:
            os.killpg(process.pid, 9)
        except ProcessLookupError:
            pass
        if process.poll() is None:
            process.wait(timeout=0.2)

    @staticmethod
    def _process_group_exists(process_group_id: int) -> bool:
        try:
            os.killpg(process_group_id, 0)
        except ProcessLookupError:
            return False
        except PermissionError:
            return True
        return True

    def _run_checker(
        self,
        command: list[str],
        root: Path,
        environment: dict[str, str],
        deadline: float,
    ) -> tuple[str, str]:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return "timeout", "static checker timed out before startup"
        try:
            process = subprocess.Popen(
                command, cwd=root, env=environment,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                start_new_session=True,
            )
        except (OSError, ValueError) as error:
            return "verifier_exception", f"checker startup failed: {error}"
        assert process.stdout is not None and process.stderr is not None
        selector = selectors.DefaultSelector()
        streams = {process.stdout: bytearray(), process.stderr: bytearray()}
        for stream in streams:
            os.set_blocking(stream.fileno(), False)
            selector.register(stream, selectors.EVENT_READ)
        total = 0
        try:
            while selector.get_map():
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    self._kill_process_group(process)
                    return "timeout", "static checker timed out"
                events = selector.select(min(remaining, 0.05))
                if not events and process.poll() is not None:
                    for stream in tuple(streams):
                        try:
                            chunk = stream.read() or b""
                        except BlockingIOError:
                            chunk = b""
                        streams[stream].extend(chunk)
                    if not self._process_group_exists(process.pid):
                        break
                    time.sleep(min(remaining, 0.01))
                for key, _ in events:
                    stream = key.fileobj
                    chunk = stream.read(8192) or b""
                    if not chunk:
                        selector.unregister(stream)
                        continue
                    total += len(chunk)
                    if total > _MAX_CHECK_OUTPUT:
                        self._kill_process_group(process)
                        return "output_limit", "checker output exceeded capture limit"
                    streams[stream].extend(chunk)
            process.wait(timeout=max(0.0, deadline - time.monotonic()))
            if self._process_group_exists(process.pid):
                self._kill_process_group(process)
                return "timeout", "checker descendant process group did not exit"
            diagnostics = bytes(streams[process.stderr]).decode("utf-8", errors="replace").strip()
            if process.returncode != 0 or diagnostics:
                return "checker_failure", diagnostics[:_MAX_CHECK_OUTPUT] or f"checker exited {process.returncode}"
            return "", ""
        except subprocess.TimeoutExpired:
            self._kill_process_group(process)
            return "timeout", "static checker timed out"
        finally:
            selector.close()
            for stream in streams:
                stream.close()

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
                try:
                    os.killpg(process.pid, 9)
                except ProcessLookupError:
                    process.terminate()
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
            root = self._validate_transaction(transaction_path, deadline)
            paths = sorted(set(changed_paths))
            if not paths:
                raise LabPathError("no changed paths to verify")
            for name in paths:
                if time.monotonic() >= deadline:
                    return VerificationEvidence(False, tuple(checks), "timeout", "transaction path validation timed out")
                self._checked_file(root, name)
            if time.monotonic() >= deadline:
                return VerificationEvidence(False, tuple(checks), "timeout", "transaction path validation timed out")

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
                        if time.monotonic() >= deadline:
                            return VerificationEvidence(False, tuple(checks), "timeout", "checker lookup timed out")
                        compiler = shutil.which("clang++", path=os.defpath)
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
                    boundary, detail = self._run_checker(command, root, environment, deadline)
                    if boundary:
                        if boundary in {"timeout", "output_limit", "verifier_exception"}:
                            return VerificationEvidence(False, tuple(checks), boundary, detail)
                        failures.append((f"{kind}_syntax", detail))
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
        except TimeoutError as error:
            return VerificationEvidence(False, tuple(checks), "timeout", str(error))
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
        for index, line in enumerate(
            difflib.unified_diff(old_lines, new_lines, fromfile, tofile, lineterm="\n")
        ):
            if index < 2 or line.startswith("@@ ") or line.endswith("\n"):
                chunks.append(line)
            else:
                chunks.append(f"{line}\n\\ No newline at end of file\n")
    return "".join(chunks)
