"""Workspace-confined execution with verifiable evidence."""
from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Iterable


@dataclass(frozen=True)
class FileEvidence:
    path: str
    size: int
    sha256: str


@dataclass(frozen=True)
class CommandEvidence:
    argv: list[str]
    cwd: str
    exit_code: int
    stdout: str
    stderr: str
    started_at: float
    finished_at: float
    timed_out: bool = False


@dataclass
class ExecutionReport:
    workspace: str
    files: list[FileEvidence] = field(default_factory=list)
    commands: list[CommandEvidence] = field(default_factory=list)

    @property
    def verified(self) -> bool:
        return bool(self.files) and bool(self.commands) and all(
            item.exit_code == 0 and not item.timed_out for item in self.commands
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "workspace": self.workspace,
            "files": [asdict(item) for item in self.files],
            "commands": [asdict(item) for item in self.commands],
            "verified": self.verified,
        }

    def write_json(self, path: str | Path) -> None:
        Path(path).write_text(json.dumps(self.to_dict(), indent=2), encoding="utf-8")


_READ_ONLY_SHELL_COMMANDS = {
    "find",
    "du",
    "ls",
    "cat",
    "head",
    "tail",
    "sort",
    "grep",
    "sed",
    "awk",
    "wc",
    "stat",
    "numfmt",
    "printf",
}

_BLOCKED_SHELL_PATTERNS = (
    r"(?:^|[\s|;&])rm(?:\s|$)",
    r"(?:^|[\s|;&])mv(?:\s|$)",
    r"(?:^|[\s|;&])cp(?:\s|$)",
    r"(?:^|[\s|;&])mkdir(?:\s|$)",
    r"(?:^|[\s|;&])touch(?:\s|$)",
    r"(?:^|[\s|;&])chmod(?:\s|$)",
    r"(?:^|[\s|;&])chown(?:\s|$)",
    r"(?:^|[\s|;&])dd(?:\s|$)",
    r"(?:^|[\s|;&])mkfs(?:\s|$)",
    r"(?:^|[\s|;&])mount(?:\s|$)",
    r"(?:^|[\s|;&])umount(?:\s|$)",
    r"(?:^|[\s|;&])sudo(?:\s|$)",
    r"(?:^|[\s|;&])su(?:\s|$)",
    r"(?:^|[\s|;&])kill(?:\s|$)",
    r"(?:^|[\s|;&])pkill(?:\s|$)",
    r"(?:^|[\s|;&])curl(?:\s|$)",
    r"(?:^|[\s|;&])wget(?:\s|$)",
    r"(?:^|[\s|;&])nc(?:\s|$)",
    r"(?:^|[\s|;&])python(?:3)?(?:\s|$)",
    r"(?:^|[\s|;&])perl(?:\s|$)",
    r"(?:^|[\s|;&])ruby(?:\s|$)",
    r"(?:^|[\s|;&])eval(?:\s|$)",
    r"(?:^|[\s|;&])exec(?:\s|$)",
    r"\$\(",
    r"`",
    r"&&",
    r"\|\|",
    r";",
)


def _validate_guarded_shell(argv: list[str]) -> None:
    """Allow only read-only bash/sh inspection pipelines."""
    if len(argv) != 3 or argv[1] not in {"-c", "-lc"}:
        raise PermissionError(
            "bash/sh is allowed only as bash -c <command> "
            "or bash -lc <command>"
        )

    command = str(argv[2]).strip()
    if not command:
        raise PermissionError("empty shell command")

    for pattern in _BLOCKED_SHELL_PATTERNS:
        if re.search(pattern, command, flags=re.IGNORECASE):
            raise PermissionError(
                f"guarded shell rejected unsafe pattern: {pattern}"
            )

    # Permit stderr/stdout suppression to /dev/null only.
    without_devnull = re.sub(
        r"(?:\d*)>\s*/dev/null",
        "",
        command,
        flags=re.IGNORECASE,
    )
    if ">" in without_devnull:
        raise PermissionError(
            "guarded shell permits output redirection only to /dev/null"
        )

    # Validate every pipeline stage.
    for raw_stage in command.split("|"):
        stage = raw_stage.strip()
        if not stage:
            raise PermissionError("empty shell pipeline stage")

        tokens = stage.split()

        # Ignore leading environment assignments.
        while tokens and re.fullmatch(
            r"[A-Za-z_][A-Za-z0-9_]*=.*",
            tokens[0],
        ):
            tokens.pop(0)

        if not tokens:
            raise PermissionError(
                "missing executable in shell pipeline"
            )

        executable = Path(tokens[0]).name
        if executable not in _READ_ONLY_SHELL_COMMANDS:
            raise PermissionError(
                f"shell pipeline command not allowlisted: {executable}"
            )


class WorkspaceExecutor:
    """Create files and run allowlisted commands inside one workspace."""

    DEFAULT_ALLOWED = {
        "python",
        "python3",
        "pytest",
        "ruff",
        "mypy",
        "pyright",
        "git",

        # Read-only filesystem and system inspection.
        "find",
        "du",
        "ls",
        "cat",
        "head",
        "tail",
        "sort",
        "grep",
        "sed",
        "awk",
        "wc",
        "stat",
        "numfmt",

        # Shell entry points are accepted only through
        # _validate_guarded_shell() below.
        "bash",
        "sh",
    }

    def __init__(
        self,
        workspace: str | Path,
        *,
        allowed_commands: Iterable[str] | None = None,
        timeout_seconds: float = 120.0,
    ) -> None:
        self.workspace = Path(workspace).expanduser().resolve()
        self.workspace.mkdir(parents=True, exist_ok=True)
        self.allowed_commands = set(self.DEFAULT_ALLOWED)
        if allowed_commands is not None:
            self.allowed_commands.update(allowed_commands)
        self.timeout_seconds = max(1.0, float(timeout_seconds))
        self.report = ExecutionReport(str(self.workspace))

    def _resolve(self, relative_path: str | Path) -> Path:
        candidate = (self.workspace / relative_path).resolve()
        if candidate != self.workspace and self.workspace not in candidate.parents:
            raise PermissionError("path escapes configured workspace")
        return candidate

    @staticmethod
    def _hash(path: Path) -> FileEvidence:
        payload = path.read_bytes()
        return FileEvidence(
            path=str(path),
            size=len(payload),
            sha256=hashlib.sha256(payload).hexdigest(),
        )

    def write_text(self, relative_path: str | Path, content: str) -> FileEvidence:
        path = self._resolve(relative_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        evidence = self._hash(path)
        self.report.files.append(evidence)
        return evidence

    def verify_file(self, relative_path: str | Path) -> FileEvidence:
        path = self._resolve(relative_path)
        if not path.is_file():
            raise FileNotFoundError(path)
        evidence = self._hash(path)
        self.report.files.append(evidence)
        return evidence

    def run(self, argv: list[str], *, cwd: str | Path = ".") -> CommandEvidence:
        if not argv:
            raise ValueError("command argv cannot be empty")

        argv = list(argv)

        # Repair common compact-model shell argument mistakes:
        # ["bash", "c", "..."]  -> ["bash", "-c", "..."]
        # ["bash", "lc", "..."] -> ["bash", "-lc", "..."]
        if len(argv) >= 3 and Path(argv[0]).name in {"bash", "sh"}:
            if argv[1] == "c":
                argv[1] = "-c"
            elif argv[1] == "lc":
                argv[1] = "-lc"

        executable = Path(argv[0]).name
        if executable not in self.allowed_commands:
            raise PermissionError(f"command not allowlisted: {executable}")
        if executable in {"bash", "sh"}:
            _validate_guarded_shell(argv)
        workdir = self._resolve(cwd)
        started = time.time()
        try:
            completed = subprocess.run(
                argv,
                cwd=workdir,
                text=True,
                capture_output=True,
                timeout=self.timeout_seconds,
                env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
                check=False,
            )
            evidence = CommandEvidence(
                argv=list(argv),
                cwd=str(workdir),
                exit_code=completed.returncode,
                stdout=completed.stdout,
                stderr=completed.stderr,
                started_at=started,
                finished_at=time.time(),
            )
        except subprocess.TimeoutExpired as error:
            evidence = CommandEvidence(
                argv=list(argv),
                cwd=str(workdir),
                exit_code=124,
                stdout=error.stdout or "",
                stderr=error.stderr or "",
                started_at=started,
                finished_at=time.time(),
                timed_out=True,
            )
        self.report.commands.append(evidence)
        return evidence


class EvidenceVerifier:
    """Reject success claims that lack objective filesystem and command evidence."""

    def verify(
        self,
        report: ExecutionReport,
        *,
        required_files: Iterable[str] = (),
        required_commands: Iterable[str] = (),
    ) -> tuple[bool, list[str]]:
        reasons: list[str] = []
        files = {Path(item.path).name for item in report.files}
        commands = {Path(item.argv[0]).name for item in report.commands if item.argv}
        for name in required_files:
            if Path(name).name not in files:
                reasons.append(f"missing file evidence: {name}")
        for name in required_commands:
            if Path(name).name not in commands:
                reasons.append(f"missing command evidence: {name}")
        for command in report.commands:
            if command.exit_code != 0 or command.timed_out:
                reasons.append(
                    f"command failed: {' '.join(command.argv)} exit={command.exit_code}"
                )
        if not report.files:
            reasons.append("no filesystem evidence")
        if not report.commands:
            reasons.append("no shell evidence")
        return not reasons, reasons
