"""Bounded recursive self-improvement controller for Sophyane Mode 3.

Design authority:

- Local LLM proposes intelligence.
- Candidate mutation happens only in an isolated Git worktree.
- Sophyane owns validation, testing, fitness and acceptance.
- NIFDU may review a verified diff but never executes mutations.
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
    contents: dict[str, str],
) -> tuple[Path, ...]:
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

        target.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        target.write_text(
            str(
                contents[relative]
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

def build_real_local_llm_candidate_prompt(
    *,
    objective: str,
    repository_summary: str,
) -> str:
    return (
        "You are Sophyane's local Mode-3 RSI candidate generator.\n\n"
        "Produce ONE small bounded candidate only.\n"
        "Do not execute commands.\n"
        "Do not commit.\n"
        "Do not push.\n"
        "Do not merge.\n"
        "Do not modify files outside the candidate contract.\n\n"
        "OBJECTIVE:\n"
        + str(objective).strip()
        + "\n\n"
        "REPOSITORY CONTEXT:\n"
        + str(repository_summary).strip()
        + "\n\n"
        "Return exactly:\n"
        "CANDIDATE\n"
        "reason: <short reason>\n"
        "files:\n"
        "- <relative path>\n"
        "verification:\n"
        "- <deterministic verification command>\n"
        "FILE\n"
        "path: <same declared relative path>\n"
        "content:\n"
        "<complete file contents>\n"
        "END_FILE\n"
        "END_CANDIDATE\n"
    )


def extract_candidate_contents(
    response: str,
) -> tuple[CandidateProposal, dict[str, str]]:
    text = str(
        response
        or ""
    ).replace(
        "\r\n",
        "\n",
    ).strip()

    if not text.startswith(
        "CANDIDATE\n"
    ):
        raise RecursiveEvolutionError(
            "local LLM candidate must begin with CANDIDATE"
        )

    if not text.endswith(
        "\nEND_CANDIDATE"
    ):
        raise RecursiveEvolutionError(
            "local LLM candidate must end with END_CANDIDATE"
        )

    body = text[
        len("CANDIDATE\n"):
        -len("\nEND_CANDIDATE")
    ]

    parts = body.split(
        "\nFILE\n"
    )

    header = parts[0]

    reason = ""
    files: list[str] = []
    verification: list[str] = []

    mode = ""

    for raw_line in header.splitlines():
        line = raw_line.rstrip()

        if line.startswith(
            "reason:"
        ):
            reason = line[
                len("reason:"):
            ].strip()
            mode = ""
            continue

        if line.strip() == "files:":
            mode = "files"
            continue

        if line.strip() == "verification:":
            mode = "verification"
            continue

        if line.startswith("- "):
            value = line[2:].strip()

            if mode == "files":
                files.append(
                    value
                )

            elif mode == "verification":
                verification.append(
                    value
                )

    if not reason:
        raise RecursiveEvolutionError(
            "candidate reason is missing"
        )

    if not files:
        raise RecursiveEvolutionError(
            "candidate files are missing"
        )

    if not verification:
        raise RecursiveEvolutionError(
            "candidate verification commands are missing"
        )

    proposal = CandidateProposal(
        reason=reason,
        files=tuple(
            files
        ),
        verification=tuple(
            verification
        ),
    )

    contents: dict[str, str] = {}

    for block in parts[1:]:
        if "\nEND_FILE" not in block:
            raise RecursiveEvolutionError(
                "candidate FILE block is incomplete"
            )

        file_body, trailing = block.split(
            "\nEND_FILE",
            1,
        )

        if trailing.strip():
            raise RecursiveEvolutionError(
                "unexpected content after END_FILE"
            )

        lines = file_body.splitlines()

        if len(lines) < 3:
            raise RecursiveEvolutionError(
                "candidate FILE block is incomplete"
            )

        if not lines[0].startswith(
            "path:"
        ):
            raise RecursiveEvolutionError(
                "candidate FILE block has no path"
            )

        relative = lines[0][
            len("path:"):
        ].strip()

        if lines[1].strip() != "content:":
            raise RecursiveEvolutionError(
                "candidate FILE block has no content marker"
            )

        content = "\n".join(
            lines[2:]
        )

        if content:
            content += "\n"

        if relative in contents:
            raise RecursiveEvolutionError(
                "candidate contains duplicate FILE block"
            )

        contents[
            relative
        ] = content

    declared = set(
        proposal.files
    )

    supplied = set(
        contents
    )

    if supplied != declared:
        raise RecursiveEvolutionError(
            "candidate FILE blocks do not match declared files"
        )

    return (
        proposal,
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

    provider = (
        local_provider
        if local_provider is not None
        else create_mode3_local_provider()
    )

    assert_mode3_local_provider(
        provider
    )

    reviewer = (
        nifdu_reviewer
        if nifdu_reviewer is not None
        else load_nifdu_supervisory_reviewer()
    )

    if not callable(
        reviewer
    ):
        raise RecursiveEvolutionError(
            "NIFDU reviewer is not callable"
        )

    baseline_head = (
        _safe_git_head(
            root
        )
        if authoritative_head_check
        else ""
    )

    instruction = str(
        objective
    ).strip()

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
                    grounded_instruction,
                    txq_policy,
                ) = apply_txq_to_instruction(
                    grounded_instruction,
                    objective=objective,
                    evolution_context=(
                        evolution_context
                    ),
                )

                txq_iteration_started = (
                    _mode3_txq_time.monotonic()
                )

                candidate_prompt = (
                    build_real_local_llm_candidate_prompt(
                        objective=grounded_instruction,
                        repository_summary=(
                            str(
                                repository_summary
                            ).strip()
                            or (
                                "Sophyane bounded recursive improvement. "
                                "Operate only inside the supplied detached "
                                "candidate worktree."
                            )
                        ),
                    )
                )

                system_prompt = (
                    "You are Sophyane Mode-3 local candidate worker. "
                    "Perform only the ONE bounded instruction supplied. "
                    "Return only the existing strict candidate contract. "
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

                    if str(
                        getattr(
                            provider,
                            "last_provider",
                            "",
                        )
                        or ""
                    ).strip().lower() != "local_gguf":
                        raise RecursiveEvolutionError(
                            "candidate was not generated by local_gguf"
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

                review = (
                    parse_supervised_nifdu_review(
                        review_response
                    )
                )
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
