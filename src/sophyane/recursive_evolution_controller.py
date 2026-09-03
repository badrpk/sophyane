"""Bounded supervised recursive self-improvement for Sophyane.

Design authority:

- Mode 4 / NIFDU owns code-change instruction and review authority.
- Mode 3 is the bounded local operations worker for one Mode-4 instruction.
- Candidate mutation happens only in an isolated Git worktree.
- Sophyane owns deterministic validation, testing, fitness and acceptance.
- Mode 4 / NIFDU never directly executes filesystem mutations.
- No commit or push is performed by this controller.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
from typing import Callable


class RecursiveEvolutionError(RuntimeError):
    """Fail-closed RSI controller error."""


@dataclass(frozen=True)
class EvolutionConfig:
    max_iterations: int = 3
    max_files_per_candidate: int = 2
    require_clean_candidate: bool = True


@dataclass(frozen=True)
class CandidateProposal:
    reason: str
    files: tuple[str, ...]
    verification: tuple[str, ...]


@dataclass(frozen=True)
class CandidateUpdate:
    """One exact, bounded replacement in an existing regular file."""

    old: str
    new: str


_SAFE_RELATIVE = re.compile(
    r"^[A-Za-z0-9_./-]+$"
)


def resolve_candidate_path(
    workspace: Path,
    relative: str,
) -> Path:
    root = Path(workspace).resolve()

    raw = Path(
        str(relative)
    )

    if raw.is_absolute():
        raise RecursiveEvolutionError(
            "absolute candidate paths are forbidden"
        )

    if not _SAFE_RELATIVE.fullmatch(
        raw.as_posix()
    ):
        raise RecursiveEvolutionError(
            "candidate path contains unsafe characters"
        )

    if any(
        part in {
            "",
            ".",
            "..",
        }
        for part in raw.parts
    ):
        raise RecursiveEvolutionError(
            "candidate path contains unsafe traversal"
        )

    target = (
        root / raw
    ).resolve()

    try:
        target.relative_to(
            root
        )
    except ValueError as error:
        raise RecursiveEvolutionError(
            "candidate path escapes workspace"
        ) from error

    return target


def parse_candidate(
    text: str,
) -> CandidateProposal:
    lines = str(
        text or ""
    ).replace(
        "\r\n",
        "\n",
    ).splitlines()

    stripped = [
        line.rstrip()
        for line in lines
    ]

    if not stripped:
        raise RecursiveEvolutionError(
            "empty RSI candidate"
        )

    if stripped[0].strip() != "RSI_CANDIDATE":
        raise RecursiveEvolutionError(
            "candidate must begin with RSI_CANDIDATE"
        )

    if stripped[-1].strip() != "END_RSI_CANDIDATE":
        raise RecursiveEvolutionError(
            "candidate must end with END_RSI_CANDIDATE"
        )

    mode = None

    reason_lines: list[str] = []
    files: list[str] = []
    verification: list[str] = []

    for raw in stripped[1:-1]:
        token = raw.strip()

        if token == "reason:":
            mode = "reason"
            continue

        if token == "files:":
            mode = "files"
            continue

        if token == "verification:":
            mode = "verification"
            continue

        if not token:
            continue

        if mode == "reason":
            reason_lines.append(
                token
            )

        elif mode == "files":
            if not token.startswith("- "):
                raise RecursiveEvolutionError(
                    "file entries must begin with '- '"
                )

            value = token[2:].strip()

            resolve_candidate_path(
                Path("/tmp/rsi-contract-root"),
                value,
            )

            files.append(
                value
            )

        elif mode == "verification":
            if not token.startswith("- "):
                raise RecursiveEvolutionError(
                    "verification entries must begin with '- '"
                )

            verification.append(
                token[2:].strip()
            )

    reason = " ".join(
        reason_lines
    ).strip()

    if not reason:
        raise RecursiveEvolutionError(
            "candidate reason is required"
        )

    if not files:
        raise RecursiveEvolutionError(
            "candidate must identify at least one file"
        )

    if not verification:
        raise RecursiveEvolutionError(
            "candidate must provide verification commands"
        )

    return CandidateProposal(
        reason=reason,
        files=tuple(files),
        verification=tuple(
            verification
        ),
    )


def build_local_llm_prompt(
    *,
    objective: str,
    repository_summary: str,
    max_files: int,
) -> str:
    return f"""You are the LOCAL LLM intelligence component for Sophyane Mode-3 recursive self-improvement.

Objective:
{objective}

Repository evidence:
{repository_summary}

Propose exactly ONE bounded candidate improvement.

Rules:
- maximum {max_files} files
- use repository-relative paths only
- prefer the smallest mutation that can improve the objective
- include deterministic verification commands
- do not claim success
- do not execute anything
- Do not commit
- Do not push

Return exactly:

RSI_CANDIDATE
reason:
<one concise reason>
files:
- <relative file>
verification:
- <deterministic verification command>
END_RSI_CANDIDATE
"""


def build_nifdu_review_prompt(
    *,
    objective: str,
    diff: str,
    verification: str,
) -> str:
    return f"""You are the external NIFDU engineering reviewer.

Objective:
{objective}

Verified candidate diff:
{diff}

Verification evidence:
{verification}

Review only.

Do not execute.
Do not modify files.
Do not commit.
Do not push.

Return exactly one of:

APPROVE
REJECT: <short reason>
"""


class RecursiveEvolutionController:
    def __init__(
        self,
        *,
        repository: Path,
        config: EvolutionConfig | None = None,
    ):
        self.repository = Path(
            repository
        ).resolve()

        self.config = (
            config
            or EvolutionConfig()
        )

        if not self.repository.is_dir():
            raise RecursiveEvolutionError(
                "repository does not exist"
            )

        self._candidate_base = Path(
            tempfile.gettempdir()
        ) / "sophyane-mode3-rsi"

    def candidate_root(
        self,
        name: str,
    ) -> Path:
        token = re.sub(
            r"[^A-Za-z0-9_.-]+",
            "-",
            str(name),
        ).strip("-")

        if not token:
            raise RecursiveEvolutionError(
                "candidate name is empty"
            )

        return (
            self._candidate_base
            / token
        ).resolve()

    def create_worktree(
        self,
        *,
        name: str,
        revision: str = "HEAD",
    ) -> Path:
        target = self.candidate_root(
            name
        )

        if target.exists():
            shutil.rmtree(
                target
            )

        target.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        result = subprocess.run(
            [
                "git",
                "-C",
                str(self.repository),
                "worktree",
                "add",
                "--detach",
                str(target),
                revision,
            ],
            text=True,
            capture_output=True,
            check=False,
        )

        if result.returncode != 0:
            raise RecursiveEvolutionError(
                "unable to create isolated worktree: "
                + result.stderr.strip()
            )

        return target

    def remove_worktree(
        self,
        workspace: Path,
    ) -> None:
        target = Path(
            workspace
        ).resolve()

        subprocess.run(
            [
                "git",
                "-C",
                str(self.repository),
                "worktree",
                "remove",
                "--force",
                str(target),
            ],
            text=True,
            capture_output=True,
            check=False,
        )

        if target.exists():
            shutil.rmtree(
                target,
                ignore_errors=True,
            )

    def verify_candidate_scope(
        self,
        *,
        workspace: Path,
        proposal: CandidateProposal,
    ) -> None:
        if (
            len(proposal.files)
            > self.config.max_files_per_candidate
        ):
            raise RecursiveEvolutionError(
                "candidate exceeds file mutation limit"
            )

        for relative in proposal.files:
            resolve_candidate_path(
                workspace,
                relative,
            )

    # SOPHYANE_MODE3_RSI_VERIFICATION_COMMAND_POLICY_V1
    @staticmethod
    def validate_verification_command(
        command: str,
    ) -> str:
        """Allow verification only; reject mutation/publication commands."""

        import shlex

        text = str(
            command
            or ""
        ).strip()

        if not text:
            raise RecursiveEvolutionError(
                "verification command is empty"
            )

        lowered = (
            " ".join(
                text.casefold().split()
            )
        )

        # Verification is not an execution-authority escape hatch.
        # Candidate generation may suggest these operations, but the
        # controller must never execute them.
        forbidden_fragments = (
            "git add ",
            "git commit",
            "git push",
            "git merge",
            "git rebase",
            "git cherry-pick",
            "git reset",
            "git checkout",
            "git restore",
            "git clean",
            "git switch",
            "git tag",
            "git branch -d",
            "git branch -D",
            "rm -",
            "rm ",
            "mv ",
            "cp ",
            "install ",
            "pip install",
            "pkg install",
            "apt install",
            "apt-get install",
            "npm install",
            "pnpm install",
            "yarn add",
            "curl ",
            "wget ",
            "scp ",
            "rsync ",
        )

        if any(
            fragment.casefold()
            in lowered
            for fragment in forbidden_fragments
        ):
            raise RecursiveEvolutionError(
                "verification command requests mutation, "
                "publication, installation, or external transfer: "
                + text
            )

        # Reject shell chaining/redirection for V1 verification authority.
        # This intentionally favors a narrow false-negative surface over
        # permitting a second command hidden after a harmless test.
        forbidden_shell = (
            ";",
            "&&",
            "||",
            ">",
            "<",
            "`",
            "$(",
        )

        if any(
            token in text
            for token in forbidden_shell
        ):
            raise RecursiveEvolutionError(
                "verification command contains unsupported shell "
                "composition or redirection: "
                + text
            )

        try:
            argv = shlex.split(
                text
            )
        except ValueError as error:
            raise RecursiveEvolutionError(
                "verification command could not be parsed"
            ) from error

        if not argv:
            raise RecursiveEvolutionError(
                "verification command is empty"
            )

        # Explicitly permit common read-only git inspection.
        if argv[0] == "git":
            allowed_git = {
                "status",
                "diff",
                "show",
                "log",
                "rev-parse",
            }

            if (
                len(argv) < 2
                or argv[1]
                not in allowed_git
            ):
                raise RecursiveEvolutionError(
                    "git verification subcommand is not read-only: "
                    + text
                )

        return text

    # SOPHYANE_MODE3_VERIFICATION_PYTHON_AUTHORITY_V1
    @staticmethod
    def authoritative_verification_command(
        command: str,
    ) -> str:
        """Bind leading Python verification to Sophyane's active interpreter.

        Candidate verification is controller-owned deterministic execution.
        A model-written bare ``python`` or ``python3`` must not accidentally
        resolve to an unrelated system interpreter outside Sophyane's venv.

        Only the leading executable token is normalized. All remaining
        arguments stay byte-for-byte shell-quoted through shlex.join().
        """
        import shlex
        import sys

        text = str(
            command
            or ""
        ).strip()

        argv = shlex.split(
            text
        )

        if not argv:
            return text

        if argv[0] not in {
            "python",
            "python3",
        }:
            return text

        argv[0] = sys.executable

        return shlex.join(
            argv
        )


    def run_verification(
        self,
        *,
        workspace: Path,
        commands: tuple[str, ...],
        runner: Callable[..., subprocess.CompletedProcess] = subprocess.run,
    ) -> tuple[bool, str]:
        evidence: list[str] = []

        for command in commands:
            command = self.validate_verification_command(
                command
            )

            command = self.authoritative_verification_command(
                command
            )

            result = runner(
                [
                    "/bin/sh",
                    "-c",
                    command,
                ],
                cwd=str(
                    workspace
                ),
                text=True,
                capture_output=True,
                check=False,
            )

            evidence.append(
                "$ "
                + command
                + "\n"
                + result.stdout
                + result.stderr
            )

            if result.returncode != 0:
                return (
                    False,
                    "\n".join(
                        evidence
                    ),
                )

        return (
            True,
            "\n".join(
                evidence
            ),
        )


# SOPHYANE_MODE3_RSI_REAL_CYCLE_V2

def apply_candidate_files(
    *,
    workspace: Path,
    proposal: CandidateProposal,
    contents: dict[str, str | CandidateUpdate],
) -> tuple[Path, ...]:
    """Materialize declared FILE content or exact bounded UPDATE operations."""

    root = Path(
        workspace
    ).resolve()

    declared = set(
        proposal.files
    )

    supplied = set(
        contents
    )

    if supplied != declared:
        missing = sorted(
            declared - supplied
        )
        extra = sorted(
            supplied - declared
        )

        raise RecursiveEvolutionError(
            "candidate content contract mismatch: "
            f"missing={missing!r} extra={extra!r}"
        )

    written: list[Path] = []

    for relative in proposal.files:
        target = resolve_candidate_path(
            root,
            relative,
        )

        materialization = contents[
            relative
        ]

        if isinstance(
            materialization,
            CandidateUpdate,
        ):
            if (
                not target.exists()
                or not target.is_file()
            ):
                raise RecursiveEvolutionError(
                    "candidate UPDATE target must be an "
                    "existing regular file: "
                    + relative
                )

            old = str(
                materialization.old
            )

            if not old:
                raise RecursiveEvolutionError(
                    "candidate UPDATE old text is empty: "
                    + relative
                )

            current = target.read_text(
                encoding="utf-8"
            )

            matches = current.count(
                old
            )

            if matches == 0:
                raise RecursiveEvolutionError(
                    "candidate UPDATE old text was not found: "
                    + relative
                )

            if matches != 1:
                raise RecursiveEvolutionError(
                    "candidate UPDATE old text is ambiguous: "
                    + relative
                )

            updated = current.replace(
                old,
                str(
                    materialization.new
                ),
                1,
            )

            target.write_text(
                updated,
                encoding="utf-8",
            )

        else:
            target.parent.mkdir(
                parents=True,
                exist_ok=True,
            )

            target.write_text(
                str(
                    materialization
                ),
                encoding="utf-8",
            )

        written.append(
            target
        )

    return tuple(
        written
    )



# SOPHYANE_RSI_COMPLETE_CANDIDATE_DIFF_V1
def candidate_diff(
    workspace: Path,
) -> str:
    """Return a read-only diff covering tracked and untracked candidate files.

    ``git diff`` alone omits untracked files. RSI candidates are explicitly
    allowed to create bounded new files, so review evidence must synthesize a
    /dev/null diff for each untracked regular file without staging it.
    """

    root = Path(
        workspace
    ).resolve()

    tracked = subprocess.run(
        [
            "git",
            "-C",
            str(root),
            "diff",
            "--no-ext-diff",
            "--binary",
            "--",
        ],
        text=True,
        capture_output=True,
        check=False,
    )

    if tracked.returncode != 0:
        raise RecursiveEvolutionError(
            "unable to obtain tracked candidate diff: "
            + tracked.stderr.strip()
        )

    untracked = subprocess.run(
        [
            "git",
            "-C",
            str(root),
            "ls-files",
            "--others",
            "--exclude-standard",
            "-z",
        ],
        capture_output=True,
        check=False,
    )

    if untracked.returncode != 0:
        raise RecursiveEvolutionError(
            "unable to enumerate untracked candidate files: "
            + untracked.stderr.decode(
                "utf-8",
                errors="replace",
            ).strip()
        )

    parts = []

    if tracked.stdout:
        parts.append(
            tracked.stdout.rstrip(
                "\n"
            )
        )

    raw_paths = [
        value
        for value in untracked.stdout.split(
            b"\0"
        )
        if value
    ]

    for raw_relative in raw_paths:
        relative = raw_relative.decode(
            "utf-8",
            errors="surrogateescape",
        )

        target = resolve_candidate_path(
            root,
            relative,
        )

        if not target.is_file():
            continue

        generated = subprocess.run(
            [
                "git",
                "-C",
                str(root),
                "diff",
                "--no-ext-diff",
                "--binary",
                "--no-index",
                "--",
                "/dev/null",
                relative,
            ],
            text=True,
            capture_output=True,
            check=False,
        )

        # git diff --no-index returns:
        #   0 -> no difference
        #   1 -> differences found
        #  >1 -> actual error
        if generated.returncode not in {
            0,
            1,
        }:
            raise RecursiveEvolutionError(
                "unable to obtain untracked candidate diff for "
                + relative
                + ": "
                + generated.stderr.strip()
            )

        if generated.stdout:
            parts.append(
                generated.stdout.rstrip(
                    "\n"
                )
            )

    if not parts:
        return ""

    return (
        "\n".join(
            parts
        )
        + "\n"
    )


def parse_nifdu_review(
    response: str,
) -> tuple[bool, str]:
    text = str(
        response
        or ""
    ).strip()

    if text == "APPROVE":
        return (
            True,
            "APPROVE",
        )

    if text.startswith(
        "REJECT:"
    ):
        reason = text[
            len("REJECT:"):
        ].strip()

        if not reason:
            raise RecursiveEvolutionError(
                "NIFDU rejection reason is empty"
            )

        return (
            False,
            reason,
        )

    raise RecursiveEvolutionError(
        "NIFDU review did not satisfy APPROVE/REJECT contract"
    )


# SOPHYANE_MODE3_RSI_LOCAL_LLM_V3


# SOPHYANE_MODE3_DERIVED_VERIFICATION_AUTHORITY_V1
def derive_candidate_verification(
    files: tuple[str, ...],
) -> tuple[str, ...]:
    """Derive bounded deterministic verification from candidate paths.

    Mode 3 supplies implementation material only. Verification authority
    belongs to Sophyane, not to the local model.

    Python test files receive one focused pytest command.
    Other Python-only candidates receive one py_compile command.
    Non-Python candidates retain the universal read-only diff check.
    """
    normalized = tuple(
        str(item).strip()
        for item in files
        if str(item).strip()
    )

    if not normalized:
        raise RecursiveEvolutionError(
            "cannot derive verification without candidate files"
        )

    python_tests = tuple(
        item
        for item in normalized
        if (
            item.endswith(".py")
            and (
                item.startswith("tests/")
                or "/tests/" in item
                or Path(item).name.startswith("test_")
            )
        )
    )

    if (
        python_tests
        and len(python_tests) == len(normalized)
    ):
        return (
            "python -m pytest "
            + " ".join(
                python_tests
            )
            + " -q",
        )

    python_files = tuple(
        item
        for item in normalized
        if item.endswith(".py")
    )

    if len(python_files) == len(normalized):
        return (
            "python -m py_compile "
            + " ".join(
                python_files
            ),
        )

    return (
        "git diff --check",
    )

def build_real_local_llm_candidate_prompt(
    *,
    objective: str,
    repository_summary: str,
) -> str:
    return (
        "You are Sophyane's Mode-3 RSI operations worker.\n\n"
        "The OBJECTIVE below is an authoritative bounded instruction "
        "issued by Mode 4 / NIFDU.\n"
        "Do not choose a different improvement.\n"
        "Do not broaden the requested scope.\n"
        "Implement only that ONE bounded instruction inside the isolated "
        "candidate worktree.\n"
        "Return the exact bounded candidate materialization contract.\n\n"

        # Keep authoritative grammar before truncatable repository context.
        "OUTPUT CONTRACT — FOLLOW EXACTLY.\n"
        "Your first line MUST be CANDIDATE.\n"
        "The second line MUST begin with reason:.\n"
        "Do not use markdown fences or triple backticks anywhere.\n"
        "For an EXISTING file, emit UPDATE with exact old and new text.\n"
        "For a genuinely NEW file, emit FILE with complete content.\n"
        "FILE and UPDATE blocks may coexist.\n"
        "Do NOT emit files:, verification:, unified diffs, commands, or JSON.\n"
        "Use relative repository paths only.\n"
        "Do not emit commentary, policy metadata, memory actions, "
        "or text outside this contract.\n\n"

        "Return exactly this structural shape:\n"
        "Existing-file UPDATE:\n"
        "CANDIDATE\n"
        "reason: <short bounded reason>\n"
        "UPDATE\n"
        "path: <relative path from OBJECTIVE>\n"
        "old:\n"
        "<exact existing text occurring once>\n"
        "new:\n"
        "<replacement text>\n"
        "END_UPDATE\n"
        "END_CANDIDATE\n\n"

        "New-file structural shape:\n"
        "CANDIDATE\n"
        "reason: <short bounded reason>\n"
        "FILE\n"
        "path: <relative path from OBJECTIVE>\n"
        "content:\n"
        "<complete requested file contents>\n"
        "END_FILE\n"
        "END_CANDIDATE\n\n"

        "Repeat complete FILE/END_FILE or UPDATE/END_UPDATE blocks "
        "only when the OBJECTIVE requires another file.\n"
        "Never reproduce an entire existing file when UPDATE can express "
        "the bounded change.\n"
        "Replace every placeholder using only the OBJECTIVE and repository "
        "evidence.\n"
        "Never invent an example path, test name, or unrelated file.\n\n"

        "OBJECTIVE:\n"
        + str(objective).strip()
        + "\n\n"

        "Produce ONE small bounded candidate only.\n"
        "Do not execute commands.\n"
        "Do not commit.\n"
        "Do not push.\n"
        "Do not merge.\n"
        "Do not modify files outside the candidate contract.\n\n"

        "REPOSITORY CONTEXT:\n"
        + str(repository_summary).strip()
        + "\n"
    )




# SOPHYANE_MODE3_FINAL_TERMINATOR_RECOVERY_V1
def normalize_complete_candidate_terminator(
    response: str,
) -> str:
    """Recover only a structurally complete candidate missing its terminator."""

    text = str(response or "").replace("\r\n", "\n").strip()

    if text.endswith("\nEND_CANDIDATE"):
        return text

    if not text.startswith("CANDIDATE\n"):
        return text

    lines = text.splitlines()
    if len(lines) < 2 or not lines[1].startswith("reason:"):
        return text

    if not (
        text.endswith("\nEND_FILE")
        or text.endswith("\nEND_UPDATE")
    ):
        return text

    body = text[len("CANDIDATE\n"):]
    first = re.search(r"\n(?:FILE|UPDATE)\n", body)

    if first is None:
        return text

    block_text = body[first.start() + 1:]
    blocks = re.split(r"\n(?=(?:FILE|UPDATE)\n)", block_text)

    if not blocks:
        return text

    for block in blocks:
        if block.startswith("FILE\n"):
            if not block.endswith("\nEND_FILE"):
                return text

            payload = block[len("FILE\n"):-len("\nEND_FILE")]
            payload_lines = payload.splitlines()

            if (
                len(payload_lines) < 2
                or not payload_lines[0].startswith("path:")
                or payload_lines[1].strip() != "content:"
            ):
                return text

        elif block.startswith("UPDATE\n"):
            if not block.endswith("\nEND_UPDATE"):
                return text

            payload = block[len("UPDATE\n"):-len("\nEND_UPDATE")]

            if (
                not payload.startswith("path:")
                or "\nold:\n" not in payload
                or "\nnew:\n" not in payload
            ):
                return text

            path_part, remainder = payload.split("\nold:\n", 1)

            if not path_part[len("path:"):].strip():
                return text

            old, _new = remainder.split("\nnew:\n", 1)

            if not old:
                return text

        else:
            return text

    return text + "\nEND_CANDIDATE"


def extract_candidate_contents(
    response: str,
) -> tuple[
    CandidateProposal,
    dict[str, str | CandidateUpdate],
]:
    text = normalize_complete_candidate_terminator(response)

    if not text.startswith("CANDIDATE\n"):
        raise RecursiveEvolutionError(
            "local LLM candidate must begin with CANDIDATE"
        )

    if not text.endswith("\nEND_CANDIDATE"):
        raise RecursiveEvolutionError(
            "local LLM candidate must end with END_CANDIDATE"
        )

    body = text[
        len("CANDIDATE\n"):
        -len("\nEND_CANDIDATE")
    ]

    first = re.search(r"\n(?:FILE|UPDATE)\n", body)

    if first is None:
        raise RecursiveEvolutionError(
            "candidate contains no FILE blocks"
        )

    header = body[:first.start()]
    block_text = body[first.start() + 1:]
    reason = ""

    for raw_line in header.splitlines():
        line = raw_line.rstrip()

        if line.startswith("reason:"):
            reason = line[len("reason:"):].strip()
            break

    if not reason:
        raise RecursiveEvolutionError(
            "candidate reason is missing"
        )

    contents: dict[str, str | CandidateUpdate] = {}
    blocks = re.split(
        r"\n(?=(?:FILE|UPDATE)\n)",
        block_text,
    )

    for block in blocks:
        if block.startswith("FILE\n"):
            if not block.endswith("\nEND_FILE"):
                raise RecursiveEvolutionError(
                    "candidate FILE block is incomplete"
                )

            payload = block[len("FILE\n"):-len("\nEND_FILE")]
            lines = payload.splitlines()

            if len(lines) < 2:
                raise RecursiveEvolutionError(
                    "candidate FILE block is incomplete"
                )

            if not lines[0].startswith("path:"):
                raise RecursiveEvolutionError(
                    "candidate FILE block has no path"
                )

            relative = lines[0][len("path:"):].strip()

            if not relative:
                raise RecursiveEvolutionError(
                    "candidate FILE block has empty path"
                )

            if lines[1].strip() != "content:":
                raise RecursiveEvolutionError(
                    "candidate FILE block has no content marker"
                )

            materialization: str | CandidateUpdate = "\n".join(lines[2:])

            if materialization:
                materialization += "\n"

        elif block.startswith("UPDATE\n"):
            if not block.endswith("\nEND_UPDATE"):
                raise RecursiveEvolutionError(
                    "candidate UPDATE block is incomplete"
                )

            payload = block[len("UPDATE\n"):-len("\nEND_UPDATE")]

            if not payload.startswith("path:"):
                raise RecursiveEvolutionError(
                    "candidate UPDATE block has no path"
                )

            if "\nold:\n" not in payload:
                raise RecursiveEvolutionError(
                    "candidate UPDATE block has no old marker"
                )

            path_part, remainder = payload.split("\nold:\n", 1)
            relative = path_part[len("path:"):].strip()

            if not relative:
                raise RecursiveEvolutionError(
                    "candidate UPDATE block has empty path"
                )

            if "\nnew:\n" not in remainder:
                raise RecursiveEvolutionError(
                    "candidate UPDATE block has no new marker"
                )

            old, new = remainder.split("\nnew:\n", 1)

            if not old:
                raise RecursiveEvolutionError(
                    "candidate UPDATE old text is empty"
                )

            materialization = CandidateUpdate(
                old=old,
                new=new,
            )

        else:
            raise RecursiveEvolutionError(
                "candidate contains an unknown materialization block"
            )

        resolve_candidate_path(
            Path("/tmp/rsi-contract-root"),
            relative,
        )

        if relative in contents:
            if block.startswith("FILE\n"):
                message = "candidate contains duplicate FILE block"
            else:
                message = "candidate contains duplicate UPDATE block"

            raise RecursiveEvolutionError(
                message
            )

        contents[relative] = materialization

    files = tuple(contents.keys())
    verification = derive_candidate_verification(files)

    return (
        CandidateProposal(
            reason=reason,
            files=files,
            verification=verification,
        ),
        contents,
    )


def build_nifdu_review_bundle(
    *,
    objective: str,
    diff: str,
    verification_ok: bool,
    verification_evidence: str,
) -> str:
    return (
        "Review this isolated Sophyane RSI candidate.\n\n"
        "You are REVIEW ONLY.\n"
        "Do not execute commands.\n"
        "Do not edit files.\n"
        "Do not commit, merge or push.\n\n"
        "OBJECTIVE:\n"
        + str(objective).strip()
        + "\n\n"
        "VERIFICATION RESULT:\n"
        + (
            "PASS"
            if verification_ok
            else "FAIL"
        )
        + "\n\n"
        "VERIFICATION EVIDENCE:\n"
        + str(
            verification_evidence
        )
        + "\n\n"
        "CANDIDATE DIFF:\n"
        + str(
            diff
        )
        + "\n\n"
        "Return exactly one of:\n"
        "APPROVE\n"
        "REJECT: <specific reason>\n"
    )



# SOPHYANE_MODE3_NIFDU_SUPERVISED_RSI_V4

@dataclass(frozen=True)
class SupervisedNifduReview:
    status: str
    next_instruction: str = ""
    reason: str = ""
    evidence: str = ""


@dataclass(frozen=True)
class SupervisedRsiIteration:
    iteration: int
    instruction: str
    worktree: Path
    mode3_response: str
    proposal: CandidateProposal | None
    verification_ok: bool
    verification_evidence: str
    diff: str
    review_response: str
    review: SupervisedNifduReview
    evidence_record: str = ""
    held_out_attempted: bool = False
    held_out_capability: str = ""
    held_out_baseline_score: float = 1.0
    held_out_candidate_score: float = 1.0
    held_out_not_regressed: bool = True
    held_out_evidence: str = ""


@dataclass(frozen=True)
class SupervisedRsiResult:
    success: bool
    stop_reason: str
    iterations: tuple[SupervisedRsiIteration, ...]


def parse_supervised_nifdu_review(
    response: str,
) -> SupervisedNifduReview:
    """Parse the strict external-review response fail-closed."""

    # SOPHYANE_MODE4_INLINE_REASON_NORMALIZATION_V1
    #
    # Mode-4 reviewers may legally emit either:
    #
    #     REASON:
    #     explanation
    #
    # or the compact equivalent:
    #
    #     REASON: explanation
    #
    # Normalize only the latter representation.  This changes no
    # review authority or status semantics; it merely makes the
    # parser insensitive to harmless field-line formatting.
    import re as _mode4_review_re

    response = _mode4_review_re.sub(
        r"(?mi)^REASON:[ \t]*(?=\S)",
        "REASON:\\n",
        str(
            response
        ),
    )

    raw = str(
        response
        or ""
    ).strip()

    if not raw:
        raise RecursiveEvolutionError(
            "empty NIFDU supervisory response"
        )

    lines = raw.splitlines()

    if not lines:
        raise RecursiveEvolutionError(
            "empty NIFDU supervisory response"
        )

    first = lines[0].strip()

    if not first.startswith(
        "STATUS:"
    ):
        raise RecursiveEvolutionError(
            "NIFDU supervisory response is missing STATUS"
        )

    status = first.split(
        ":",
        1,
    )[1].strip().upper()

    if status not in {
        "CONTINUE",
        "SUCCESS",
        "FAIL",
    }:
        raise RecursiveEvolutionError(
            "unsupported NIFDU supervisory status: "
            + status
        )

    sections: dict[str, list[str]] = {}
    current = ""

    for line in lines[1:]:
        stripped = line.strip()

        if (
            stripped.endswith(":")
            and stripped[:-1]
            in {
                "NEXT_MODE3_INSTRUCTION",
                "REASON",
                "EVIDENCE",
            }
        ):
            current = stripped[:-1]
            sections.setdefault(
                current,
                [],
            )
            continue

        if current:
            sections[
                current
            ].append(
                line
            )

    next_instruction = "\n".join(
        sections.get(
            "NEXT_MODE3_INSTRUCTION",
            [],
        )
    ).strip()

    reason = "\n".join(
        sections.get(
            "REASON",
            [],
        )
    ).strip()

    evidence = "\n".join(
        sections.get(
            "EVIDENCE",
            [],
        )
    ).strip()

    if status == "CONTINUE":
        if not next_instruction:
            raise RecursiveEvolutionError(
                "CONTINUE requires NEXT_MODE3_INSTRUCTION"
            )

        if not reason:
            raise RecursiveEvolutionError(
                "CONTINUE requires REASON"
            )

    elif status == "SUCCESS":
        if not evidence:
            raise RecursiveEvolutionError(
                "SUCCESS requires EVIDENCE"
            )

    elif status == "FAIL":
        if not reason:
            raise RecursiveEvolutionError(
                "FAIL requires REASON"
            )

    return SupervisedNifduReview(
        status=status,
        next_instruction=next_instruction,
        reason=reason,
        evidence=evidence,
    )



# SOPHYANE_MODE4_RSI_INITIAL_INSTRUCTION_AUTHORITY_V1
def build_initial_nifdu_instruction_prompt(
    *,
    original_goal: str,
    evolution_context: str,
    repository_summary: str = "",
) -> str:
    """Require Mode 4 to issue the first bounded Mode-3 operation."""

    return (
        "You are the external NIFDU/ChatGPT Mode-4 RSI controller "
        "for Sophyane.\n\n"
        "AUTHORITY CONTRACT:\n"
        "- You decide the ONE bounded code-change instruction.\n"
        "- Mode 3 is only the operational worker that performs your "
        "instruction inside an isolated worktree.\n"
        "- You do not execute commands or directly edit files.\n"
        "- Sophyane independently performs deterministic verification, "
        "held-out evaluation and acceptance gates.\n"
        "- Do not stage, commit, merge, push, rebase, cherry-pick, "
        "reset, restore, install packages or transfer files.\n\n"
        "ORIGINAL RSI GOAL:\n"
        + str(original_goal).strip()
        + "\n\n"
        "EXISTING SOPHYANE EVOLUTION EVIDENCE:\n"
        + str(evolution_context).strip()
        + "\n\n"
        "REPOSITORY SUMMARY:\n"
        + (
            str(repository_summary).strip()
            or "No additional repository summary supplied."
        )
        + "\n\n"
        "Choose exactly ONE small concrete operation for Mode 3.\n"
        "The instruction must identify a bounded implementation target "
        "and must not delegate architectural choice back to Mode 3.\n"
        "Do not claim success because no candidate has yet been "
        "deterministically verified.\n\n"
        "Return EXACTLY one of:\n\n"
        "STATUS: CONTINUE\n"
        "NEXT_MODE3_INSTRUCTION:\n"
        "<one concise concrete bounded implementation instruction>\n"
        "REASON:\n"
        "<short evidence-grounded reason>\n\n"
        "or:\n\n"
        "STATUS: FAIL\n"
        "REASON:\n"
        "<specific reason a safe bounded instruction cannot be issued>\n"
    )


def build_supervised_nifdu_review_prompt(
    *,
    original_goal: str,
    iteration: int,
    last_mode3_instruction: str,
    mode3_response: str,
    verification_ok: bool,
    verification_evidence: str,
    diff: str,
    failure: str = "",
) -> str:
    """Build the strong-model review packet for one bounded iteration."""

    return (
        "You are the external NIFDU/ChatGPT engineering reviewer "
        "for Sophyane Mode-3 recursive improvement.\n\n"
        "The local Mode-3 model is a small 1.5B worker. "
        "Do not give it a large multi-stage plan. "
        "Your job is to inspect the exact result and produce at most "
        "ONE small concrete next instruction.\n\n"
        "You are REVIEW AND INSTRUCTION-GENERATION ONLY.\n"
        "Do not execute commands.\n"
        "Do not edit files.\n"
        "Do not stage, commit, merge, push, rebase, cherry-pick, "
        "reset, restore, install packages, or transfer files.\n\n"
        "ORIGINAL GOAL:\n"
        + str(original_goal).strip()
        + "\n\nCURRENT ITERATION:\n"
        + str(iteration)
        + "\n\nLAST MODE3 INSTRUCTION:\n"
        + str(last_mode3_instruction).strip()
        + "\n\nMODE3 RESPONSE:\n"
        + str(mode3_response)
        + "\n\nDETERMINISTIC VERIFICATION:\n"
        + (
            "PASS"
            if verification_ok
            else "FAIL"
        )
        + "\n\nVERIFICATION EVIDENCE:\n"
        + str(verification_evidence)
        + "\n\nFAILURE / EXCEPTION:\n"
        + (
            str(failure)
            if failure
            else "None"
        )
        + "\n\nCANDIDATE DIFF:\n"
        + (
            str(diff)
            if diff
            else "(no usable diff)"
        )
        + "\n\nDECISION RULES:\n"
        "1. STATUS: SUCCESS is allowed only when deterministic "
        "verification passed and the supplied evidence proves the "
        "requested bounded step succeeded.\n"
        "2. Otherwise use STATUS: CONTINUE with exactly ONE small "
        "Mode-3-compatible instruction when safe recovery remains.\n"
        "3. Use STATUS: FAIL when bounded safe recovery should stop.\n"
        "4. Never invent successful execution evidence.\n"
        "5. Do not repeat already completed work.\n\n"
        "Return EXACTLY one of these contracts:\n\n"
        "STATUS: CONTINUE\n"
        "NEXT_MODE3_INSTRUCTION:\n"
        "<one concise concrete instruction>\n"
        "REASON:\n"
        "<short evidence-grounded reason>\n\n"
        "or:\n\n"
        "STATUS: SUCCESS\n"
        "EVIDENCE:\n"
        "<specific supplied passing evidence>\n\n"
        "or:\n\n"
        "STATUS: FAIL\n"
        "REASON:\n"
        "<specific reason>\n"
    )


def assert_mode3_local_provider(
    provider,
) -> None:
    """Prove candidate-generation authority is singleton local_gguf."""

    primary = str(
        getattr(
            provider,
            "primary",
            "",
        )
        or ""
    ).strip().lower()

    if primary != "local_gguf":
        raise RecursiveEvolutionError(
            "Mode-3 RSI provider primary is not local_gguf"
        )

    chain = list(
        getattr(
            provider,
            "_providers",
            [],
        )
        or []
    )

    if len(chain) != 1:
        raise RecursiveEvolutionError(
            "Mode-3 RSI provider chain must contain exactly "
            "one provider"
        )

    item = chain[0]

    if (
        not isinstance(
            item,
            tuple,
        )
        or len(item) != 2
        or str(
            item[0]
        ).strip().lower()
        != "local_gguf"
    ):
        raise RecursiveEvolutionError(
            "Mode-3 RSI provider chain is not singleton local_gguf"
        )


def create_mode3_local_provider():
    """Construct the real local-only provider without cloud fallback."""

    import os

    from sophyane.config import load_config
    from sophyane.main import create_provider

    keys = (
        "SOPHYANE_SESSION_MODE",
        "SOPHYANE_SESSION_PROVIDER",
        "SOPHYANE_LOCAL_ONLY",
        "SOPHYANE_DISABLE_CLOUD_FALLBACK",
    )

    previous = {
        key: os.environ.get(
            key
        )
        for key in keys
    }

    try:
        os.environ[
            "SOPHYANE_SESSION_MODE"
        ] = "local_llm"

        os.environ[
            "SOPHYANE_SESSION_PROVIDER"
        ] = "local_gguf"

        os.environ[
            "SOPHYANE_LOCAL_ONLY"
        ] = "1"

        os.environ[
            "SOPHYANE_DISABLE_CLOUD_FALLBACK"
        ] = "1"

        provider = create_provider(
            load_config()
        )

        assert_mode3_local_provider(
            provider
        )

        return provider

    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(
                    key,
                    None,
                )
            else:
                os.environ[
                    key
                ] = value


# SOPHYANE_MODE4_CODEX_CANDIDATE_WORKER_AUTHORITY_V1
def create_mode4_codex_candidate_provider(
    repository: Path,
):
    """Create the read-only Codex worker for an explicit Mode-4.3 session."""

    import os

    from sophyane.providers.codex_cli import (
        CodexCliProvider,
    )

    return CodexCliProvider(
        workspace=Path(
            repository
        ).expanduser().resolve(),
        model=(
            os.environ.get(
                "SOPHYANE_SESSION_MODEL"
            )
            or "codex-default"
        ),
        timeout=int(
            os.environ.get(
                "SOPHYANE_SESSION_TIMEOUT"
            )
            or "300"
        ),
    )


def load_nifdu_supervisory_reviewer(
    selection_path: Path | None = None,
):
    """Load the already-discovered ChatGPT CDP callable for review."""

    import asyncio
    import importlib.util
    import inspect
    import json

    selected = (
        Path(selection_path)
        if selection_path is not None
        else (
            Path.home()
            / ".local/share/sophyane-chatgpt-loop"
            / "sophyane-nifdu-callable.json"
        )
    ).expanduser().resolve()

    if not selected.is_file():
        raise RecursiveEvolutionError(
            "NIFDU callable selection file does not exist: "
            + str(selected)
        )

    payload = json.loads(
        selected.read_text(
            encoding="utf-8",
        )
    )

    module_path = Path(
        payload.get(
            "module",
            "",
        )
    ).expanduser().resolve()

    # SOPHYANE_NIFDU_CANONICAL_TRACKED_BRIDGE_AUTHORITY_V1
    #
    # Historical NIFDU discovery persisted a copied ChatGPT bridge under
    # ~/.local/share/sophyane-chatgpt-loop/chatgpt_cdp.py.
    #
    # That copy can become stale after the packaged bridge receives response
    # freshness, timeout, safety or authority fixes.  The selection record is
    # therefore treated as discovery metadata, not source-code authority, for
    # this one known legacy bridge location.
    #
    # Genuine custom NIFDU modules remain untouched.
    legacy_bridge = (
        Path.home()
        / ".local"
        / "share"
        / "sophyane-chatgpt-loop"
        / "chatgpt_cdp.py"
    ).expanduser().resolve()

    if module_path == legacy_bridge:
        module_path = (
            Path(__file__).resolve().parent
            / "providers"
            / "nifdu_cdp_bridge.py"
        ).resolve()

    if not module_path.is_file():
        raise RecursiveEvolutionError(
            "NIFDU callable module does not exist: "
            + str(module_path)
        )

    spec = importlib.util.spec_from_file_location(
        "_sophyane_rsi_nifdu_supervisor",
        module_path,
    )

    if (
        spec is None
        or spec.loader is None
    ):
        raise RecursiveEvolutionError(
            "unable to load NIFDU supervisory module"
        )

    module = importlib.util.module_from_spec(
        spec
    )

    spec.loader.exec_module(
        module
    )

    kind = str(
        payload.get(
            "kind",
            "",
        )
    )

    if kind == "function":
        target = getattr(
            module,
            payload["name"],
        )

    elif kind == "method":
        cls = getattr(
            module,
            payload["class"],
        )

        target = getattr(
            cls(),
            payload["name"],
        )

    else:
        raise RecursiveEvolutionError(
            "unsupported NIFDU callable kind: "
            + kind
        )

    args = list(
        payload.get(
            "args",
            [],
        )
        or []
    )

    def review(
        prompt: str,
    ) -> str:
        if len(args) == 1:
            result = target(
                prompt
            )

        elif (
            len(args) == 2
            and args[1]
            in {
                "image",
                "screenshot",
                "image_path",
                "screenshot_path",
            }
        ):
            result = target(
                prompt,
                None,
            )

        else:
            raise RecursiveEvolutionError(
                "unsupported NIFDU callable arguments: "
                + repr(args)
            )

        if inspect.isawaitable(
            result
        ):
            result = asyncio.run(
                result
            )

        return str(
            result
        )

    return review


# SOPHYANE_MODE4_SUPERVISORY_PROVIDER_AUTHORITY_V1
def load_mode4_supervisory_reviewer(
    *,
    repository: Path,
):
    """Load the reviewer selected by the explicit Mode-4 submode."""

    import os

    mode = str(
        os.environ.get(
            "SOPHYANE_SESSION_MODE"
        )
        or ""
    ).strip().lower()

    if mode in {
        "codex",
        "codex_cli",
    }:
        from sophyane.providers.codex_cli import (
            CodexCliProvider,
        )

        provider = CodexCliProvider(
            workspace=repository,
            model=(
                os.environ.get(
                    "SOPHYANE_SESSION_MODEL"
                )
                or "codex-default"
            ),
            timeout=int(
                os.environ.get(
                    "SOPHYANE_SESSION_TIMEOUT"
                )
                or "300"
            ),
        )

        def review(
            prompt: str,
        ) -> str:
            return provider.generate(
                prompt,
                (
                    "You are Sophyane's external Mode-4 "
                    "supervisory reviewer. Select or review "
                    "exactly one bounded operation. Remain "
                    "read-only; Sophyane owns mutation and "
                    "deterministic verification."
                ),
            )

        return review

    return load_nifdu_supervisory_reviewer()


def _safe_git_head(
    repository: Path,
) -> str:
    result = subprocess.run(
        [
            "git",
            "-C",
            str(
                Path(repository).resolve()
            ),
            "rev-parse",
            "HEAD",
        ],
        text=True,
        capture_output=True,
        check=False,
    )

    if result.returncode != 0:
        raise RecursiveEvolutionError(
            "unable to read authoritative repository HEAD: "
            + result.stderr.strip()
        )

    return result.stdout.strip()



# SOPHYANE_MODE4_RSI_REPOSITORY_GROUNDING_V1
def _bounded_mode4_repository_summary(
    repository: Path,
    objective: str,
    *,
    maximum_files: int = 12,
    maximum_chars: int = 12000,
) -> str:
    """Build bounded read-only source evidence for Mode-4 RSI selection.

    Mode 4 owns code-change selection. Therefore it must receive enough real
    repository evidence to identify a concrete bounded target instead of
    guessing from the objective alone.

    This helper is deliberately read-only and bounded. It does not give Mode 3
    architectural authority and does not mutate the authoritative repository.
    """

    import re
    import subprocess

    root = Path(
        repository
    ).expanduser().resolve()

    objective_text = str(
        objective
        or ""
    ).casefold()

    tokens = {
        item
        for item in re.findall(
            r"[a-z0-9_]{3,}",
            objective_text,
        )
        if item
        not in {
            "the",
            "and",
            "for",
            "with",
            "only",
            "one",
            "current",
            "existing",
            "small",
            "tiny",
            "change",
            "improvement",
            "source",
        }
    }

    tokens.update(
        {
            "mode3",
            "mode4",
            "rsi",
            "recursive",
            "evolution",
            "nifdu",
        }
    )

    try:
        listed = subprocess.run(
            [
                "git",
                "-C",
                str(root),
                "ls-files",
                "src/sophyane",
                "tests",
            ],
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
        ).stdout.splitlines()

    except Exception:
        listed = []

    candidates = []

    for relative in listed:
        relative = str(
            relative
        ).strip()

        if not relative.endswith(
            ".py"
        ):
            continue

        candidate = (
            root
            / relative
        )

        if not candidate.is_file():
            continue

        try:
            text = candidate.read_text(
                encoding="utf-8",
                errors="replace",
            )

        except OSError:
            continue

        lower_path = (
            relative.casefold()
        )

        lower_text = (
            text.casefold()
        )

        score = 0

        for token in tokens:
            if token in lower_path:
                score += 20

            occurrences = lower_text.count(
                token
            )

            score += min(
                occurrences,
                20,
            )

        if score <= 0:
            continue

        evidence_lines = []

        for number, line in enumerate(
            text.splitlines(),
            start=1,
        ):
            lower_line = line.casefold()

            if any(
                token in lower_line
                for token in tokens
            ):
                evidence_lines.append(
                    f"{number}: {line[:260]}"
                )

            if len(
                evidence_lines
            ) >= 14:
                break

        candidates.append(
            (
                score,
                relative,
                evidence_lines,
            )
        )

    candidates.sort(
        key=lambda item: (
            -item[0],
            item[1],
        )
    )

    lines = [
        "MODE4_BOUNDED_REPOSITORY_EVIDENCE",
        (
            "repository="
            + str(root)
        ),
    ]

    for score, relative, evidence_lines in candidates[
        : max(
            1,
            int(maximum_files),
        )
    ]:
        lines.append(
            (
                "FILE="
                + relative
                + " SCORE="
                + str(score)
            )
        )

        lines.extend(
            evidence_lines
        )

    if len(lines) == 2:
        lines.append(
            "No relevant tracked Python source evidence was discovered."
        )

    lines.append(
        "END_MODE4_BOUNDED_REPOSITORY_EVIDENCE"
    )

    result = "\n".join(
        lines
    )

    return result[
        : max(
            1000,
            int(maximum_chars),
        )
    ]


def _existing_evolution_context(
    repository: Path,
    *,
    maximum_principles: int = 8,
) -> str:
    """Read Sophyane's existing learning state for one RSI iteration.

    This is intentionally read-side integration only.

    Authority remains with the existing evolution subsystem:
    - focused_capability() owns curriculum selection;
    - PrincipleStore owns learned/recurrent principles;
    - this controller does not manufacture recurrent status;
    - this controller does not promote, commit, or mutate Git state.
    """

    from sophyane.evolution.curriculum import (
        focused_capability,
    )
    from sophyane.evolution.principles import (
        PrincipleStore,
    )

    root = Path(
        repository
    ).expanduser().resolve()

    limit = max(
        0,
        min(
            int(maximum_principles),
            32,
        ),
    )

    try:
        capability = (
            focused_capability(
                root
            )
            or ""
        )
    except Exception as error:
        capability = (
            "unavailable:"
            + type(error).__name__
        )

    try:
        recurrent = list(
            PrincipleStore(
                root
            ).recurrent_principles()
        )
    except Exception as error:
        recurrent = [
            {
                "status": "unavailable",
                "principle": (
                    type(error).__name__
                ),
            }
        ]

    lines = [
        "EXISTING_SOPHYANE_EVOLUTION_STATE",
        (
            "focused_capability="
            + str(capability or "none")
        ),
        (
            "recurrent_principle_count="
            + str(len(recurrent))
        ),
    ]

    for index, item in enumerate(
        recurrent[:limit],
        start=1,
    ):
        if isinstance(
            item,
            dict,
        ):
            component = str(
                item.get("component")
                or ""
            ).strip()

            principle_capability = str(
                item.get("capability")
                or ""
            ).strip()

            principle = str(
                item.get("principle")
                or item.get("general_principle")
                or item.get("description")
                or ""
            ).strip()

            status = str(
                item.get("status")
                or ""
            ).strip()

            confidence = str(
                item.get("confidence")
                or ""
            ).strip()
        else:
            component = ""
            principle_capability = ""
            principle = str(
                item
            ).strip()
            status = ""
            confidence = ""

        fields = [
            (
                "index="
                + str(index)
            ),
        ]

        if component:
            fields.append(
                "component="
                + component
            )

        if principle_capability:
            fields.append(
                "capability="
                + principle_capability
            )

        if status:
            fields.append(
                "status="
                + status
            )

        if confidence:
            fields.append(
                "confidence="
                + confidence
            )

        if principle:
            fields.append(
                "principle="
                + principle
            )

        lines.append(
            " | ".join(
                fields
            )
        )

    lines.append(
        "END_EXISTING_SOPHYANE_EVOLUTION_STATE"
    )

    return "\n".join(
        lines
    )


def _ground_supervised_rsi_instruction(
    instruction: str,
    evolution_context: str,
) -> str:
    """Ground one NIFDU-supervised instruction in existing RSI learning."""

    objective = str(
        instruction
        or ""
    ).strip()

    context = str(
        evolution_context
        or ""
    ).strip()

    if not objective:
        raise RecursiveEvolutionError(
            "RSI instruction is empty"
        )

    if not context:
        return objective

    return (
        objective
        + "\n\n"
        + context
        + "\n\n"
        + (
            "Use this existing Sophyane evolution state "
            "as evidence and prioritization context. "
            "Do not treat it as permission to bypass "
            "candidate scope, deterministic verification, "
            "held-out validation, trusted vetoes, or "
            "repository mutation boundaries."
        )
    )



def _evolution_context_capability(
    evolution_context: str,
) -> str:
    """Recover the exact focused capability used to ground this iteration."""

    prefix = "focused_capability="

    for raw in str(
        evolution_context
        or ""
    ).splitlines():
        line = raw.strip()

        if not line.startswith(
            prefix
        ):
            continue

        value = line[
            len(prefix):
        ].strip()

        if (
            not value
            or value == "none"
            or value.startswith(
                "unavailable:"
            )
        ):
            return ""

        return value

    return ""



def _supervised_rsi_evidence_identity(
    *,
    instruction: str,
    evolution_context: str,
    diff: str,
    verification_commands: tuple[str, ...],
    candidate_files: tuple[str, ...] = (),
) -> str:
    """Return a deterministic identity for one logical verified candidate.

    Worktree names are deliberately excluded. A crash/retry of identical
    candidate source and verification contract must address the same native
    evidence record.

    A materially different diff, instruction, focused capability, command
    contract, or candidate file set produces a different identity.
    """

    import hashlib
    import json

    payload = {
        "instruction": str(
            instruction
            or ""
        ).strip(),
        "evolution_context": str(
            evolution_context
            or ""
        ).strip(),
        "diff": str(
            diff
            or ""
        ),
        "verification_commands": [
            str(item)
            for item in verification_commands
        ],
        "candidate_files": sorted(
            str(item)
            for item in candidate_files
        ),
    }

    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(
            ",",
            ":",
        ),
        ensure_ascii=False,
    ).encode(
        "utf-8"
    )

    digest = hashlib.sha256(
        encoded
    ).hexdigest()[:24]

    return (
        "supervised-rsi-"
        + digest
    )


def _persist_supervised_rsi_evidence(
    *,
    repository: Path,
    iteration: int,
    instruction: str,
    workspace: Path,
    evolution_context: str,
    verification_completed: bool,
    verification_ok: bool,
    verification_commands: tuple[str, ...],
    verification_evidence: str,
    failure: str,
    candidate_diff: str = "",
    candidate_files: tuple[str, ...] = (),
) -> Path | None:
    """Persist one real V4 verification as native Sophyane evidence.

    This function deliberately has no source-promotion authority.

    In particular:
    - pre-verification failures are not persisted as validation evidence;
    - no GateResult is created;
    - no targeted/regression/held-out/security result is fabricated;
    - failed completed verification is analyzed offline only;
    - AnalysisPipeline / PrincipleStore remain the learning authority.
    """

    if not verification_completed:
        return None

    from sophyane.evolution.curriculum import (
        CAPABILITIES,
        update_score,
    )
    from sophyane.evolution.evidence_pipeline import (
        AnalysisPipeline,
        EvidenceStore,
    )
    from sophyane.evolution.models import (
        EvolutionRecord,
        ExecutionTrace,
        TaskSpec,
        ValidationResult,
    )

    root = Path(
        repository
    ).expanduser().resolve()

    worktree = Path(
        workspace
    ).expanduser().resolve()

    capability = (
        _evolution_context_capability(
            evolution_context
        )
    )

    task_id = (
        _supervised_rsi_evidence_identity(
            instruction=instruction,
            evolution_context=(
                evolution_context
            ),
            diff=candidate_diff,
            verification_commands=(
                verification_commands
            ),
            candidate_files=(
                candidate_files
            ),
        )
    )

    passed = bool(
        verification_ok
    )

    evidence = str(
        verification_evidence
        or ""
    )

    failure_text = str(
        failure
        or ""
    ).strip()

    errors: list[str] = []

    if not passed:
        errors.append(
            failure_text
            or "supervised_rsi_verification_failed"
        )

    task = TaskSpec(
        task_id=task_id,
        prompt=str(
            instruction
            or ""
        ),
        capability=capability,
        validator="supervised_rsi_verification",
        expected={
            "verification_completed": True,
            "verification_commands": list(
                verification_commands
            ),
            "candidate_files": list(
                candidate_files
            ),
            "source": "mode3_nifdu_rsi_v4",
            "evidence_identity": task_id,
        },
        held_out=False,
    )

    trace = ExecutionTrace(
        task_id=task_id,
        workspace=str(
            worktree
        ),
        command=list(
            verification_commands
        ),
        # This is the normalized V4 verification result, not a claim
        # about any particular underlying subprocess return code.
        exit_code=(
            0
            if passed
            else 1
        ),
        stdout=evidence,
        stderr=failure_text,
        elapsed_seconds=0.0,
        files=[
            str(item)
            for item in candidate_files
        ],
    )

    validation = ValidationResult(
        passed=passed,
        validator="supervised_rsi_verification",
        checks={
            "supervised_rsi_verification": passed,
        },
        errors=errors,
    )

    record = EvolutionRecord(
        run_id=task_id,
        cycle=int(
            iteration
        ),
        task=task,
        trace=trace,
        validation=validation,
        gate=None,
        status=(
            "reinforced"
            if passed
            else "failure_observed"
        ),
    )

    store = EvidenceStore(
        root
    )

    expected_record_path = (
        store.records
        / f"{task_id}.json"
    )

    score_observation_new = (
        not expected_record_path.exists()
    )

    record_path = record.write(
        store.records
    )

    assert (
        record_path
        == expected_record_path
    )

    #
    # Quantitative curriculum feedback uses the same native authority as
    # EvolutionEngine.cycle(). The native evidence record is the durable
    # at-most-once receipt: retries may refresh the same record, but they
    # cannot increment capability-scores.json again.
    #
    if (
        score_observation_new
        and capability in CAPABILITIES
    ):
        update_score(
            root,
            capability,
            passed,
        )

    if not passed:
        AnalysisPipeline(
            root
        ).analyze_path(
            record_path,
            use_local=False,
            use_cloud=False,
        )

    return record_path



def _run_supervised_rsi_held_out(
    *,
    repository: Path,
    workspace: Path,
    evolution_context: str,
    verification_completed: bool,
    verification_ok: bool,
) -> dict[str, object]:
    """Run native held-out replay without acquiring promotion authority.

    V4 deliberately reuses only CandidateEvolver's public, non-promoting
    held-out/replay APIs.

    Baseline and candidate executions both occur in the replay subsystem's
    disposable temporary workspaces. ``source_repo`` selects which Sophyane
    source tree supplies the runtime; it is not the execution cwd.

    This function cannot create GateResult, commit, promote, or invoke
    Red Queen lifecycle methods.
    """

    capability = (
        _evolution_context_capability(
            evolution_context
        )
    )

    result: dict[str, object] = {
        "attempted": False,
        "capability": capability,
        "baseline_score": 1.0,
        "candidate_score": 1.0,
        "not_regressed": True,
        "evidence": "",
    }

    if (
        not verification_completed
        or not verification_ok
        or not capability
    ):
        return result

    root = Path(
        repository
    ).expanduser().resolve()

    candidate = Path(
        workspace
    ).expanduser().resolve()

    if not candidate.is_dir():
        result["attempted"] = True
        result["not_regressed"] = False
        result["evidence"] = (
            "held_out_candidate_worktree_missing="
            + str(candidate)
        )
        return result

    if candidate == root:
        result["attempted"] = True
        result["not_regressed"] = False
        result["evidence"] = (
            "held_out_candidate_must_not_be_authoritative_repo"
        )
        return result

    from sophyane.evolution.candidate_evolution import (
        CandidateEvolver,
    )

    try:
        evolver = CandidateEvolver(
            root
        )

        tasks = evolver.held_out_tasks(
            capability=capability,
        )

        #
        # An empty task family has the same neutral semantics as native
        # CandidateEvolver.score([]) == 1.0.
        #
        if not tasks:
            result["evidence"] = (
                "held_out_tasks=0; "
                "native_neutral_score=1.0"
            )
            return result

        if not all(
            bool(task.held_out)
            for task in tasks
        ):
            result["attempted"] = True
            result["not_regressed"] = False
            result["evidence"] = (
                "native held-out authority returned "
                "a non-held-out task"
            )
            return result

        result["attempted"] = True

        baseline = evolver.replay_tasks(
            source_repo=root,
            tasks=tasks,
        )

        candidate_results = (
            evolver.replay_tasks(
                source_repo=candidate,
                tasks=tasks,
            )
        )

        baseline_score = float(
            evolver.score(
                baseline
            )
        )

        candidate_score = float(
            evolver.score(
                candidate_results
            )
        )

        not_regressed = (
            candidate_score
            >= baseline_score
        )

        result[
            "baseline_score"
        ] = baseline_score

        result[
            "candidate_score"
        ] = candidate_score

        result[
            "not_regressed"
        ] = not_regressed

        pairs = []

        for baseline_item, candidate_item in zip(
            baseline,
            candidate_results,
        ):
            pairs.append(
                (
                    str(
                        baseline_item.task_id
                    )
                    + ":baseline="
                    + (
                        "PASS"
                        if baseline_item.passed
                        else "FAIL"
                    )
                    + ",candidate="
                    + (
                        "PASS"
                        if candidate_item.passed
                        else "FAIL"
                    )
                )
            )

        result["evidence"] = (
            "native_held_out_capability="
            + capability
            + "\n"
            + "baseline_score="
            + str(baseline_score)
            + "\n"
            + "candidate_score="
            + str(candidate_score)
            + "\n"
            + "not_regressed="
            + str(not_regressed)
            + "\n"
            + "\n".join(
                pairs
            )
        )

        return result

    except Exception as error:
        #
        # Failure to establish trusted held-out evidence fails closed for
        # held-out acceptance, but does not rewrite deterministic verification.
        #
        result["attempted"] = True
        result["not_regressed"] = False
        result["evidence"] = (
            "native_held_out_error="
            + type(error).__name__
            + ": "
            + str(error)
        )

        return result


def run_supervised_mode3_nifdu_rsi(
    *,
    objective: str,
    repository: Path,
    max_iterations: int = 3,
    local_provider=None,
    nifdu_reviewer=None,
    controller=None,
    repository_summary: str = "",
    authoritative_head_check: bool = True,
) -> SupervisedRsiResult:
    """Run bounded Mode3 -> evidence -> NIFDU -> next-instruction RSI."""

    import uuid

    root = Path(
        repository
    ).expanduser().resolve()

    limit = int(
        max_iterations
    )

    if (
        limit < 1
        or limit > 20
    ):
        raise RecursiveEvolutionError(
            "max_iterations must be between 1 and 20"
        )

    if not str(
        objective
        or ""
    ).strip():
        raise RecursiveEvolutionError(
            "RSI objective is empty"
        )

    engine = (
        controller
        if controller is not None
        else RecursiveEvolutionController(
            repository=root
        )
    )

    # SOPHYANE_RSI_CANDIDATE_PROVIDER_SELECTION_V1
    #
    # Mode 3 remains the operational apply/verify authority. In an explicit
    # Mode-4.3 session, Codex may produce the strict candidate text while
    # remaining read-only. Sophyane alone applies and verifies that text in
    # the isolated worktree.
    import os

    session_mode = str(
        os.environ.get(
            "SOPHYANE_SESSION_MODE"
        )
        or ""
    ).strip().lower()

    use_codex_candidate_worker = (
        local_provider is None
        and session_mode in {
            "codex",
            "codex_cli",
        }
    )

    if use_codex_candidate_worker:
        provider = create_mode4_codex_candidate_provider(
            root
        )
        candidate_provider_id = "codex_cli"

    else:
        provider = (
            local_provider
            if local_provider is not None
            else create_mode3_local_provider()
        )

        assert_mode3_local_provider(
            provider
        )

        candidate_provider_id = "local_gguf"

    reviewer = (
        nifdu_reviewer
        if nifdu_reviewer is not None
        else load_mode4_supervisory_reviewer(
            repository=root,
        )
    )

    if not callable(
        reviewer
    ):
        raise RecursiveEvolutionError(
            "Mode-4 reviewer is not callable"
        )

    baseline_head = (
        _safe_git_head(
            root
        )
        if authoritative_head_check
        else ""
    )

    # SOPHYANE_MODE4_RSI_FIRST_INSTRUCTION_GATE_V1
    #
    # Mode 3 must never originate the first source-code improvement.
    # Before any local candidate generation, Mode 4 receives the original
    # goal plus Sophyane's existing evolution evidence and chooses exactly
    # one bounded operation for the Mode-3 worker.
    initial_evolution_context = (
        _existing_evolution_context(
            root
        )
    )

    # SOPHYANE_MODE4_RSI_INITIAL_GROUNDED_SELECTION_V1
    #
    # Mode 4 is the source-change selection authority. When its caller does
    # not provide an explicit repository summary, supply bounded real source
    # evidence automatically before asking it to choose the first operation.
    # Mode 3 remains only the worker that executes the resulting instruction.
    effective_repository_summary = str(
        repository_summary
        or ""
    ).strip()

    if not effective_repository_summary:
        effective_repository_summary = (
            _bounded_mode4_repository_summary(
                root,
                objective,
            )
        )

    # SOPHYANE_GLOBAL_TXQ_MODE4_INITIAL_V1
    #
    # Global TXQ governs resource/latency/context policy only.
    # Mode 4 retains first source-change selection authority.
    from sophyane.global_txq import (
        mode4_txq_context,
    )

    (
        mode4_initial_txq_policy,
        mode4_initial_txq_context,
    ) = mode4_txq_context(
        objective
    )

    # SOPHYANE_MODE4_MODE3_LATENCY_OVERLAP_V2
    #
    # While the external Mode-4 reviewer is waiting on browser/API latency,
    # Mode 3 may spend otherwise-idle local inference time collecting
    # READ-ONLY repository evidence.
    #
    # This worker cannot select or materialize a change.
    # Mode 4 remains the first source-change selection authority.
    #
    from sophyane.global_txq import (
        readonly_speculation_contract,
    )

    from sophyane.global_txq_speculation import (
        matching_speculative_context,
        start_readonly_speculation,
    )

    # SOPHYANE_MODE3_SPECULATION_SINGLE_FLIGHT_ADMISSION_V1
    #
    # Read-only speculation is optional latency overlap. It may borrow the
    # local llama lane only when that lane is already idle.
    #
    # Never queue a short speculative request behind an authorized local
    # generation. On a one-slot mobile llama-server that produces timeout /
    # cancellation churn without useful overlap.
    #
    # Reuse local_server's existing /slots interpretation. A zero-duration
    # wait performs one admission probe; it does not wait for a busy lane to
    # become idle. Failure to prove idleness fails closed by skipping optional
    # speculation while Mode 4 continues normally.
    from sophyane.local_server import (
        wait_until_idle as _mode3_speculation_slot_idle,
    )

    speculative_slot_available = False

    if (
        candidate_provider_id == "local_gguf"
        and mode4_initial_txq_policy.allow_speculative_readonly
        and mode4_initial_txq_policy.max_speculative_loops > 0
    ):
        try:
            speculative_slot_available = (
                _mode3_speculation_slot_idle(
                    timeout=0.0,
                    poll_interval=0.05,
                )
            )
        except Exception:
            speculative_slot_available = False

    speculative_worker = (
        start_readonly_speculation(
            provider=provider,
            prompt=(
                readonly_speculation_contract(
                    objective,
                    maximum_items=8,
                )
                + "\n\n"
                + effective_repository_summary[
                    :mode4_initial_txq_policy.context_budget_chars
                ]
            ),
            max_loops=(
                mode4_initial_txq_policy.max_speculative_loops
            ),
            context_budget_chars=(
                mode4_initial_txq_policy.context_budget_chars
            ),
            speculative_timeout_sec=(
                mode4_initial_txq_policy.speculative_timeout_sec
            ),
            speculative_max_tokens=(
                mode4_initial_txq_policy.speculative_max_tokens
            ),
        )
        if speculative_slot_available
        else None
    )

    try:
        initial_review_response = str(
            reviewer(
                build_initial_nifdu_instruction_prompt(
                    original_goal=objective,
                    evolution_context=(
                        initial_evolution_context
                        + "\n\n"
                        + mode4_initial_txq_context
                    ),
                    repository_summary=(
                        effective_repository_summary[
                            :mode4_initial_txq_policy.context_budget_chars
                        ]
                    ),
                )
            )
        )

    finally:
        #
        # Mode 4 has returned (or failed). Stop future speculative loops.
        #
        if speculative_worker is not None:
            speculative_worker.cancel()

    initial_review = (
        parse_supervised_nifdu_review(
            initial_review_response
        )
    )

    if initial_review.status == "SUCCESS":
        raise RecursiveEvolutionError(
            "Mode-4 initial RSI review cannot declare SUCCESS "
            "before deterministic candidate verification"
        )

    if initial_review.status == "FAIL":
        return SupervisedRsiResult(
            success=False,
            stop_reason=(
                "mode4_initial_fail: "
                + initial_review.reason
            ),
            iterations=(),
        )

    if initial_review.status != "CONTINUE":
        raise RecursiveEvolutionError(
            "Mode-4 initial RSI review did not provide "
            "a bounded Mode-3 instruction"
        )

    instruction = str(
        initial_review.next_instruction
    ).strip()

    if not instruction:
        raise RecursiveEvolutionError(
            "Mode-4 initial RSI instruction is empty"
        )

    # SOPHYANE_MODE3_SPECULATION_DRAIN_BEFORE_MUTATION_V2
    #
    # The local llama server is commonly single-flight. An in-flight
    # speculative call must leave that lane before authoritative Mode-3
    # candidate generation begins.
    #
    speculative_evidence = ()

    if speculative_worker is not None:
        drained = speculative_worker.drain(
            timeout_sec=(
                max(
                    5.0,
                    min(
                        60.0,
                        float(
                            mode4_initial_txq_policy.wall_time_budget_sec
                        )
                        * 0.5,
                    ),
                )
            )
        )

        if not drained:
            raise RecursiveEvolutionError(
                "Mode-3 speculative read-only worker did not drain "
                "before authorized candidate generation"
            )

        speculative_evidence = (
            speculative_worker.evidence()
        )

    matched_speculative_context = (
        matching_speculative_context(
            evidence=speculative_evidence,
            instruction=instruction,
            maximum_chars=(
                max(
                    1000,
                    int(
                        mode4_initial_txq_policy.context_budget_chars
                        * 0.35
                    ),
                )
            ),
        )
    )

    history: list[
        SupervisedRsiIteration
    ] = []

    try:
        for iteration in range(
            1,
            limit + 1,
        ):
            workspace = engine.create_worktree(
                name=(
                    "supervised-rsi-"
                    + str(iteration)
                    + "-"
                    + uuid.uuid4().hex[:8]
                ),
            )

            mode3_response = ""
            proposal = None
            verification_ok = False
            verification_completed = False
            verification_commands: tuple[str, ...] = ()
            verification_evidence = ""
            diff = ""
            failure = ""
            review_response = ""
            review = None
            evidence_record_path = None
            held_out_result: dict[str, object] = {
                "attempted": False,
                "capability": "",
                "baseline_score": 1.0,
                "candidate_score": 1.0,
                "not_regressed": True,
                "evidence": "",
            }

            try:
                evolution_context = (
                    _existing_evolution_context(
                        root
                    )
                )

                grounded_instruction = (
                    _ground_supervised_rsi_instruction(
                        instruction,
                        evolution_context,
                    )
                )
                # SOPHYANE_MODE3_META_RSI_TXQ_V3
                #
                # Local GGUF remains the candidate worker.
                # TXQ only shapes bounded effort/context/decomposition.
                #
                import time as _mode3_txq_time

                from sophyane.mode3_meta_rsi import (
                    apply_txq_to_instruction,
                )

                (
                    txq_augmented_instruction,
                    txq_policy,
                ) = apply_txq_to_instruction(
                    grounded_instruction,
                    objective=objective,
                    evolution_context=(
                        evolution_context
                    ),
                )

                # SOPHYANE_MODE3_CANDIDATE_CONTRACT_ISOLATION_V1
                #
                # TXQ is controller-side policy/evidence. The local candidate
                # worker must receive the bounded implementation instruction,
                # not the rendered MODE3_TXQ_POLICY grammar, because its output
                # has exactly one authoritative format:
                #
                #     CANDIDATE ... END_CANDIDATE
                #
                # Keep the rendered TXQ instruction available for controller
                # accounting without feeding that competing format into the
                # candidate materialization prompt.
                candidate_instruction = grounded_instruction

                # SOPHYANE_MODE3_AGENTIC_MEMORY_RETRIEVAL_V1
                #
                # Retrieve only compact VERIFIED cross-session memories.
                # TXQ owns the historical-context budget.
                # Current deterministic evidence always remains authoritative.
                #
                from sophyane.agentic_memory import (
                    augment_instruction_with_memory,
                )

                (
                    memory_augmented_instruction,
                    mode3_retrieved_memories,
                ) = augment_instruction_with_memory(
                    candidate_instruction,
                    objective=objective,
                    difficulty=(
                        txq_policy.difficulty
                    ),
                    quality_target=(
                        txq_policy.quality_target
                    ),
                    context_budget_chars=(
                        txq_policy.context_budget_chars
                    ),
                )

                # Verified historical memory remains available to the
                # controller, but candidate generation stays grammar-pure.
                # A small local worker must not choose between repository
                # memory prose and the strict CANDIDATE materialization form.

                txq_iteration_started = (
                    _mode3_txq_time.monotonic()
                )

                candidate_prompt = (
                    build_real_local_llm_candidate_prompt(
                        objective=candidate_instruction,
                        repository_summary=(
                            (
    (
        effective_repository_summary
    )
    + (
        (
            "\n\n"
            + matched_speculative_context
        )
        if matched_speculative_context
        else ""
    )
)
                        ),
                    )
                )

                worker_identity = (
                    "You are Sophyane's read-only Codex candidate worker. "
                    if candidate_provider_id == "codex_cli"
                    else
                    "You are Sophyane Mode-3 local operations worker. "
                )

                system_prompt = (
                    worker_identity
                    + "Mode 4 is the code-change instruction authority. "
                    "You may implement only the ONE bounded instruction supplied. "
                    "Do not select a different improvement or broaden scope. "
                    "Return only the strict bounded FILE/UPDATE contract. "
                    "Your first line must be CANDIDATE and your final line "
                    "must be END_CANDIDATE. "
                    "The second line must start with reason:. "
                    "Use UPDATE with path, old, new, and END_UPDATE for "
                    "existing files. Use FILE with path, content, and "
                    "END_FILE only for genuinely new files. "
                    "Do not emit files:, verification:, commands, or JSON. "
                    "Never use triple-backtick code fences, including inside "
                    "the candidate contract. "
                    "Do not emit JSON, markdown commentary, policy metadata, "
                    "memory actions, or text outside that contract. "
                    "Do not claim execution. "
                    "Do not stage, commit, merge, push, rebase, "
                    "cherry-pick, reset, restore, install packages, "
                    "or transfer files externally."
                )

                try:
                    raw = provider.generate(
                        candidate_prompt,
                        system_prompt,
                    )

                    mode3_response = str(
                        getattr(
                            raw,
                            "text",
                            raw,
                        )
                    )

                    observed_candidate_provider = str(
                        getattr(
                            provider,
                            "last_provider",
                            "",
                        )
                        or getattr(
                            provider,
                            "provider_id",
                            "",
                        )
                        or ""
                    ).strip().lower()

                    if (
                        observed_candidate_provider
                        != candidate_provider_id
                    ):
                        raise RecursiveEvolutionError(
                            "candidate provider authority mismatch: "
                            f"expected {candidate_provider_id}, "
                            f"observed {observed_candidate_provider or 'unknown'}"
                        )

                    proposal, contents = (
                        extract_candidate_contents(
                            mode3_response
                        )
                    )

                    engine.verify_candidate_scope(
                        workspace=workspace,
                        proposal=proposal,
                    )

                    apply_candidate_files(
                        workspace=workspace,
                        proposal=proposal,
                        contents=contents,
                    )

                    commands = tuple(
                        proposal.verification
                    )

                    if not commands:
                        commands = (
                            "git diff --check",
                        )

                    verification_commands = (
                        tuple(commands)
                    )

                    (
                        verification_ok,
                        verification_evidence,
                    ) = engine.run_verification(
                        workspace=workspace,
                        commands=commands,
                    )

                    verification_completed = True

                    diff = candidate_diff(
                        workspace
                    )

                except Exception as error:
                    failure = (
                        type(error).__name__
                        + ": "
                        + str(error)
                    )

                    verification_ok = False

                    if not verification_evidence:
                        verification_evidence = (
                            "Mode-3 candidate stage failed before "
                            "deterministic verification completed.\n"
                            + failure
                        )

                    try:
                        diff = candidate_diff(
                            workspace
                        )
                    except Exception:
                        diff = ""

                native_held_out_authority = (
                    root
                    / "src"
                    / "sophyane"
                    / "evolution"
                    / "candidate_evolution.py"
                )

                if native_held_out_authority.is_file():
                    held_out_result = (
                        _run_supervised_rsi_held_out(
                            repository=root,
                            workspace=workspace,
                            evolution_context=(
                                evolution_context
                            ),
                            verification_completed=(
                                verification_completed
                            ),
                            verification_ok=(
                                verification_ok
                            ),
                        )
                    )
                else:
                    #
                    # Synthetic/unit-test repositories do not contain
                    # Sophyane's native CandidateEvolver authority.
                    #
                    # This is "not attempted", not "passed":
                    # no held-out result is fabricated and therefore
                    # no held-out veto is asserted.
                    #
                    held_out_result["evidence"] = (
                        "native_held_out_unavailable="
                        "candidate_evolution_authority_absent"
                    )

                review_verification_evidence = str(
                    verification_evidence
                    or ""
                )

                held_out_evidence = str(
                    held_out_result.get(
                        "evidence"
                    )
                    or ""
                )

                if held_out_evidence:
                    review_verification_evidence += (
                        "\n\n"
                        "NATIVE_SOPHYANE_HELD_OUT\n"
                        + held_out_evidence
                        + "\n"
                        "END_NATIVE_SOPHYANE_HELD_OUT"
                    )

                # SOPHYANE_MODE3_NIFDU_META_SUPERVISION_V3
                #
                # NIFDU receives deterministic measurements as evidence.
                # It remains advisory and cannot manufacture success.
                #
                from sophyane.mode3_meta_rsi import (
                    build_nifdu_meta_context,
                )

                txq_elapsed_sec = max(
                    0.0,
                    (
                        _mode3_txq_time.monotonic()
                        - txq_iteration_started
                    ),
                )

                txq_meta_context = (
                    build_nifdu_meta_context(
                        objective=objective,
                        policy=txq_policy,
                        elapsed_sec=(
                            txq_elapsed_sec
                        ),
                        verification_ok=(
                            verification_ok
                        ),
                        held_out_attempted=bool(
                            held_out_result.get(
                                "attempted"
                            )
                        ),
                        held_out_not_regressed=bool(
                            held_out_result.get(
                                "not_regressed"
                            )
                        ),
                        failure=failure,
                    )
                )

                review_verification_evidence += (
                    "\n\n"
                    + txq_meta_context
                )
                # SOPHYANE_GLOBAL_TXQ_MODE4_FINAL_V1
                (
                    mode4_final_txq_policy,
                    mode4_final_txq_context,
                ) = mode4_txq_context(
                    objective,
                    observed_latency_sec=(
                        txq_elapsed_sec
                    ),
                )

                review_verification_evidence += (
                    "\n\n"
                    + mode4_final_txq_context
                )

                review_verification_evidence = (
                    review_verification_evidence[
                        -mode4_final_txq_policy.context_budget_chars:
                    ]
                )

                review_prompt = (
                    build_supervised_nifdu_review_prompt(
                        original_goal=objective,
                        iteration=iteration,
                        last_mode3_instruction=(
                            grounded_instruction
                        ),
                        mode3_response=mode3_response,
                        verification_ok=verification_ok,
                        verification_evidence=(
                            review_verification_evidence
                        ),
                        diff=diff,
                        failure=failure,
                    )
                )

                review_response = str(
                    reviewer(
                        review_prompt
                    )
                )

                # SOPHYANE_MODE4_RAW_REVIEW_EVIDENCE_V1
                #
                # Preserve the exact external reviewer response before strict
                # parsing. A malformed or prematurely captured NIFDU response
                # must remain observable rather than disappearing behind the
                # parser exception.
                raw_review_path = (
                    Path(
                        workspace
                    )
                    / ".sophyane-mode4-review-response.txt"
                )

                raw_review_path.write_text(
                    review_response,
                    encoding="utf-8",
                )

                try:
                    review = (
                        parse_supervised_nifdu_review(
                            review_response
                        )
                    )

                except Exception as review_error:
                    raise RecursiveEvolutionError(
                        "Mode-4 supervisory response failed strict parsing. "
                        "RAW_RESPONSE_BEGIN\n"
                        + review_response
                        + "\nRAW_RESPONSE_END\n"
                        + type(
                            review_error
                        ).__name__
                        + ": "
                        + str(
                            review_error
                        )
                    ) from review_error
                # SOPHYANE_MODE3_TXQ_OBSERVATION_V3
                #
                # Learn from the actual candidate identity.
                # Same candidate + same verification commands are idempotent.
                #
                from sophyane.mode3_meta_rsi import (
                    accept_meta_proposal,
                    parse_meta_proposal,
                    record_observation,
                )

                (
                    txq_observation,
                    txq_observation_new,
                ) = record_observation(
                    objective=objective,
                    policy=txq_policy,
                    candidate_diff=diff,
                    verification_commands=(
                        verification_commands
                    ),
                    elapsed_sec=(
                        txq_elapsed_sec
                    ),
                    verification_ok=(
                        verification_ok
                    ),
                    held_out_attempted=bool(
                        held_out_result.get(
                            "attempted"
                        )
                    ),
                    held_out_not_regressed=bool(
                        held_out_result.get(
                            "not_regressed"
                        )
                    ),
                    nifdu_status=(
                        review.status
                    ),
                    retry_index=iteration,
                )

                txq_meta_proposal = (
                    parse_meta_proposal(
                        review_response
                    )
                )

                txq_meta_proposal_accepted = False

                if txq_meta_proposal is not None:
                    txq_meta_proposal_accepted = (
                        accept_meta_proposal(
                            txq_meta_proposal,
                            deterministic_verification_ok=(
                                verification_ok
                            ),
                            held_out_attempted=bool(
                                held_out_result.get(
                                    "attempted"
                                )
                            ),
                            held_out_not_regressed=bool(
                                held_out_result.get(
                                    "not_regressed"
                                )
                            ),
                        )
                    )

                # SOPHYANE_MODE3_AGENTIC_MEMORY_LEARNING_V1
                #
                # Durable memory learns only after:
                #   1. deterministic verification,
                #   2. held-out non-regression when attempted,
                #   3. parsed NIFDU supervisory status.
                #
                # Neither the local LLM nor NIFDU can independently establish
                # durable truth.
                #
                from sophyane.agentic_memory import (
                    MemoryProvenance,
                    apply_verified_memory_action,
                    learn_verified_mode3_experience,
                    parse_memory_action,
                )
                from sophyane.mode3_meta_rsi import (
                    estimate_task_family,
                    observation_identity,
                )

                mode3_memory_candidate_identity = (
                    observation_identity(
                        objective=objective,
                        candidate_diff=diff,
                        verification_commands=(
                            verification_commands
                        ),
                    )
                )

                (
                    mode3_learned_memory,
                    mode3_memory_new,
                ) = learn_verified_mode3_experience(
                    objective=objective,
                    candidate_identity=(
                        mode3_memory_candidate_identity
                    ),
                    candidate_diff=diff,
                    task_family=(
                        estimate_task_family(
                            objective
                        )
                    ),
                    verification_ok=(
                        verification_ok
                    ),
                    held_out_attempted=bool(
                        held_out_result.get(
                            "attempted"
                        )
                    ),
                    held_out_not_regressed=bool(
                        held_out_result.get(
                            "not_regressed"
                        )
                    ),
                    review_status=(
                        review.status
                    ),
                )

                mode3_memory_action = (
                    parse_memory_action(
                        (
                            str(
                                mode3_response
                                or ""
                            )
                            + "\n"
                            + str(
                                review_response
                                or ""
                            )
                        )
                    )
                )

                mode3_memory_action_accepted = False

                if mode3_memory_action is not None:
                    mode3_memory_action_accepted = (
                        apply_verified_memory_action(
                            mode3_memory_action,
                            provenance=(
                                MemoryProvenance(
                                    source=(
                                        "mode3-proposed-action"
                                    ),
                                    task_family=(
                                        estimate_task_family(
                                            objective
                                        )
                                    ),
                                    candidate_identity=(
                                        mode3_memory_candidate_identity
                                    ),
                                    verification_ok=(
                                        verification_ok
                                    ),
                                    held_out_attempted=bool(
                                        held_out_result.get(
                                            "attempted"
                                        )
                                    ),
                                    held_out_not_regressed=bool(
                                        held_out_result.get(
                                            "not_regressed"
                                        )
                                    ),
                                )
                            ),
                        )
                    )

                evidence_record_path = (
                    _persist_supervised_rsi_evidence(
                        repository=root,
                        iteration=iteration,
                        instruction=instruction,
                        workspace=workspace,
                        evolution_context=(
                            evolution_context
                        ),
                        verification_completed=(
                            verification_completed
                        ),
                        verification_ok=(
                            verification_ok
                        ),
                        verification_commands=(
                            verification_commands
                        ),
                        verification_evidence=(
                            verification_evidence
                        ),
                        failure=failure,
                        candidate_diff=diff,
                        candidate_files=(
                            tuple(proposal.files)
                            if proposal is not None
                            else ()
                        ),
                    )
                )

                if (
                    review.status == "SUCCESS"
                    and (
                        not verification_ok
                        or (
                            bool(
                                held_out_result.get(
                                    "attempted"
                                )
                            )
                            and not bool(
                                held_out_result.get(
                                    "not_regressed"
                                )
                            )
                        )
                    )
                ):
                    raise RecursiveEvolutionError(
                        "NIFDU attempted SUCCESS without "
                        "passing deterministic verification "
                        "and native held-out non-regression"
                    )

                item = SupervisedRsiIteration(
                    iteration=iteration,
                    instruction=instruction,
                    worktree=Path(
                        workspace
                    ).resolve(),
                    mode3_response=mode3_response,
                    proposal=proposal,
                    verification_ok=verification_ok,
                    verification_evidence=(
                        verification_evidence
                    ),
                    diff=diff,
                    review_response=review_response,
                    review=review,
                    evidence_record=(
                        str(evidence_record_path)
                        if evidence_record_path
                        else ""
                    ),
                    held_out_attempted=(
                        bool(
                            held_out_result.get(
                                "attempted"
                            )
                        )
                    ),
                    held_out_capability=(
                        str(
                            held_out_result.get(
                                "capability"
                            )
                            or ""
                        )
                    ),
                    held_out_baseline_score=(
                        float(
                            held_out_result.get(
                                "baseline_score",
                                1.0,
                            )
                        )
                    ),
                    held_out_candidate_score=(
                        float(
                            held_out_result.get(
                                "candidate_score",
                                1.0,
                            )
                        )
                    ),
                    held_out_not_regressed=(
                        bool(
                            held_out_result.get(
                                "not_regressed",
                                True,
                            )
                        )
                    ),
                    held_out_evidence=(
                        str(
                            held_out_result.get(
                                "evidence"
                            )
                            or ""
                        )
                    ),
                )

                history.append(
                    item
                )

                if review.status == "SUCCESS":
                    return SupervisedRsiResult(
                        success=True,
                        stop_reason="approved",
                        iterations=tuple(
                            history
                        ),
                    )

                if review.status == "FAIL":
                    return SupervisedRsiResult(
                        success=False,
                        stop_reason=(
                            "nifdu_fail: "
                            + review.reason
                        ),
                        iterations=tuple(
                            history
                        ),
                    )

                instruction = (
                    review.next_instruction
                )

            finally:
                engine.remove_worktree(
                    workspace
                )

        return SupervisedRsiResult(
            success=False,
            stop_reason="max_iterations",
            iterations=tuple(
                history
            ),
        )

    finally:
        if authoritative_head_check:
            final_head = _safe_git_head(
                root
            )

            if final_head != baseline_head:
                raise RecursiveEvolutionError(
                    "authoritative repository HEAD changed "
                    "during supervised RSI"
                )
