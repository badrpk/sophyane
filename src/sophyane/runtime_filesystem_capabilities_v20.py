
from __future__ import annotations

# SOPHYANE_FILESYSTEM_CAPABILITIES_V20

from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any, Callable
import hashlib
import json
import os
import re
import shutil
import subprocess


IGNORED_DIRECTORIES = {
    ".git",
    ".hg",
    ".svn",
    ".sophyane",
    "__pycache__",
    "node_modules",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    ".tox",
    ".nox",
    ".venv",
    "venv",
    "build",
    "dist",
}

IGNORED_SUFFIXES = {
    ".pyc",
    ".pyo",
}

PROJECT_WORDS = {
    "build",
    "create",
    "develop",
    "implement",
    "code",
    "website",
    "application",
    "app",
    "game",
    "calculator",
    "project",
    "fix",
    "improve",
    "update",
    "continue",
    "modify",
}

_INSTALLED = False


def normalize(text: str) -> str:
    return " ".join(str(text or "").lower().split())


def select_scope(
    request: str,
    workspace: Path,
) -> tuple[Path, str]:
    text = normalize(request)

    if any(
        phrase in text
        for phrase in (
            "my computer",
            "whole computer",
            "home directory",
            "home folder",
            "my home",
        )
    ):
        return Path.home().resolve(), "user_home"

    return workspace.expanduser().resolve(), "active_workspace"


def iter_files(root: Path):
    root = root.expanduser().resolve()

    for current, directories, filenames in os.walk(root):
        directories[:] = [
            name
            for name in directories
            if name not in IGNORED_DIRECTORIES
        ]

        current_path = Path(current)

        for filename in filenames:
            path = current_path / filename

            if path.suffix.lower() in IGNORED_SUFFIXES:
                continue

            try:
                if path.is_file() and not path.is_symlink():
                    yield path, path.stat()
            except OSError:
                continue


def classify_request(request: str) -> dict[str, Any] | None:
    text = normalize(request)
    words = set(text.split())

    # Existing project builder remains the owner of software tasks.
    if words.intersection(PROJECT_WORDS):
        launcher_request = (
            "desktop icon" in text
            or "home screen" in text
            or "homescreen" in text
            or "desktop launcher" in text
        )

        if not launcher_request:
            return None

    if (
        (
            "desktop icon" in text
            or "home screen" in text
            or "homescreen" in text
            or "desktop launcher" in text
        )
        and (
            "sophyane" in text
            or "launcher" in text
            or "icon" in text
        )
    ):
        return {
            "type": "platform.install_launcher",
            "name": "Sophyane",
        }

    # Preserve the already working latest-modified capability.
    if (
        any(
            phrase in text
            for phrase in (
                "latest modified",
                "last modified",
                "last file",
                "newest file",
                "most recently",
                "last edited",
                "last amended",
            )
        )
        and "file" in text
    ):
        return None

    if (
        "duplicate" in text
        and ("file" in text or "files" in text)
    ):
        return {"type": "filesystem.duplicate_files"}

    if (
        "empty" in text
        and (
            "folder" in text
            or "folders" in text
            or "directory" in text
            or "directories" in text
        )
    ):
        return {"type": "filesystem.empty_directories"}

    if any(
        phrase in text
        for phrase in (
            "modified today",
            "changed today",
            "edited today",
            "amended today",
        )
    ):
        return {"type": "filesystem.modified_today"}

    if (
        ("largest" in text or "biggest" in text)
        and (
            "folder contains" in text
            or "directory contains" in text
            or "which folder" in text
            or "which directory" in text
        )
        and "file" in text
    ):
        return {"type": "filesystem.largest_file_parent"}

    if (
        (
            "largest files" in text
            or "biggest files" in text
            or "top files" in text
        )
        and ("file" in text or "files" in text)
    ):
        match = re.search(r"\b(\d{1,2})\b", text)
        limit = int(match.group(1)) if match else 10
        limit = min(max(limit, 1), 50)

        return {
            "type": "filesystem.top_largest_files",
            "limit": limit,
        }

    if (
        ("largest" in text or "biggest" in text)
        and (
            "file" in text
            or "disk space" in text
            or "most space" in text
            or "consumes" in text
        )
    ):
        return {"type": "filesystem.largest_file"}

    if (
        ("oldest" in text or "earliest modified" in text)
        and ("file" in text or "files" in text)
    ):
        return {"type": "filesystem.oldest_file"}

    # SOPHYANE_FILESYSTEM_LIST_FILES_CLASSIFIER
    if (
        (
            "list files" in text
            or "show files" in text
            or "display files" in text
            or "view files" in text
        )
        and not (
            "count" in text
            or "how many" in text
            or "number of" in text
            or "largest" in text
            or "biggest" in text
            or "latest" in text
            or "newest" in text
            or "oldest" in text
        )
    ):
        return {"type": "filesystem.list_files"}

    if (
        (
            "list folders" in text
            or "show folders" in text
            or "list directories" in text
            or "show directories" in text
        )
        and not (
            "count" in text
            or "how many" in text
            or "number of" in text
        )
    ):
        return {"type": "filesystem.list_folders"}

    if (
        (
            "count" in text
            or "how many" in text
            or "number of" in text
        )
        and (
            "folder" in text
            or "folders" in text
            or "directory" in text
            or "directories" in text
        )
    ):
        return {"type": "filesystem.folder_count"}

    if (
        (
            "count" in text
            or "how many" in text
            or "number of" in text
        )
        and ("file" in text or "files" in text)
    ):
        return {"type": "filesystem.file_count"}

    if (
        any(
            phrase in text
            for phrase in (
                "disk usage",
                "directory size",
                "folder size",
                "space used",
                "total size",
            )
        )
        and "largest" not in text
        and "biggest" not in text
    ):
        return {"type": "filesystem.directory_size"}

    return None


def evidence(
    root: Path,
    capability: str,
    scope: str,
    **values: Any,
) -> str:
    payload = {
        "ok": True,
        "capability": capability,
        "root": str(root),
        "scope": scope,
        "runtime_executed_action": True,
        "provider_selected_action": False,
        "deterministic": True,
        "sli_grounded": True,
        **values,
    }

    return json.dumps(
        payload,
        indent=2,
        ensure_ascii=False,
    )


def execute_capability(
    action: dict[str, Any],
    workspace: Path,
    request: str,
) -> tuple[bool, str]:
    capability = str(action.get("type") or "").strip().lower()

    if capability == "platform.install_launcher":
        return install_launcher()

    root, scope = select_scope(request, workspace)
    files = list(iter_files(root))

    if capability == "filesystem.largest_file":
        if not files:
            return False, "No regular files were found."

        path, stat = max(
            files,
            key=lambda item: item[1].st_size,
        )

        return True, evidence(
            root,
            capability,
            scope,
            path=str(path.relative_to(root)),
            absolute_path=str(path),
            size_bytes=stat.st_size,
            files_inspected=len(files),
        )

    if capability == "filesystem.largest_file_parent":
        if not files:
            return False, "No regular files were found."

        path, stat = max(
            files,
            key=lambda item: item[1].st_size,
        )

        return True, evidence(
            root,
            capability,
            scope,
            file=str(path.relative_to(root)),
            parent_directory=str(path.parent.relative_to(root)),
            size_bytes=stat.st_size,
            files_inspected=len(files),
        )

    if capability == "filesystem.top_largest_files":
        limit = int(action.get("limit") or 10)
        limit = min(max(limit, 1), 50)

        selected = sorted(
            files,
            key=lambda item: item[1].st_size,
            reverse=True,
        )[:limit]

        return True, evidence(
            root,
            capability,
            scope,
            limit=limit,
            files=[
                {
                    "path": str(path.relative_to(root)),
                    "size_bytes": stat.st_size,
                }
                for path, stat in selected
            ],
            files_inspected=len(files),
        )

    if capability == "filesystem.oldest_file":
        if not files:
            return False, "No regular files were found."

        path, stat = min(
            files,
            key=lambda item: item[1].st_mtime_ns,
        )

        modified = datetime.fromtimestamp(
            stat.st_mtime
        ).astimezone()

        return True, evidence(
            root,
            capability,
            scope,
            path=str(path.relative_to(root)),
            modified_iso=modified.isoformat(),
            size_bytes=stat.st_size,
            files_inspected=len(files),
        )

    if capability == "filesystem.file_count":
        return True, evidence(
            root,
            capability,
            scope,
            count=len(files),
        )

    # SOPHYANE_FILESYSTEM_LIST_FILES_EXECUTOR
    if capability == "filesystem.list_files":
        try:
            entries = sorted(
                (
                    p.name
                    for p in root.iterdir()
                    if p.is_file()
                    and not p.is_symlink()
                ),
                key=str.casefold,
            )
        except OSError as error:
            return False, f"Unable to list files: {error}"

        return True, evidence(
            root,
            capability,
            scope,
            count=len(entries),
            entries=entries,
        )

    if capability == "filesystem.list_folders":
        try:
            entries = sorted(
                (
                    p.name
                    for p in root.iterdir()
                    if p.is_dir()
                    and not p.is_symlink()
                    and p.name not in IGNORED_DIRECTORIES
                    and not p.name.startswith(".")
                ),
                key=str.lower,
            )
        except OSError as error:
            return False, f"Could not list folders under {root}: {error}"
        preview = entries[:100]
        return True, evidence(
            root,
            capability,
            scope,
            folder_count=len(entries),
            folders=preview,
            truncated=len(entries) > len(preview),
        )

    if capability == "filesystem.folder_count":
        try:
            folders = [
                entry
                for entry in root.iterdir()
                if entry.is_dir()
                and not entry.is_symlink()
                and entry.name not in IGNORED_DIRECTORIES
                and not entry.name.startswith(".")
            ]
        except OSError as error:
            return False, f"Could not count folders under {root}: {error}"

        return True, evidence(
            root,
            capability,
            scope,
            folder_count=len(folders),
        )

    if capability == "filesystem.directory_size":
        total = sum(
            stat.st_size
            for _, stat in files
        )

        return True, evidence(
            root,
            capability,
            scope,
            size_bytes=total,
            files_inspected=len(files),
        )

    if capability == "filesystem.empty_directories":
        empty_directories: list[str] = []

        for current, directories, filenames in os.walk(root):
            directories[:] = [
                name
                for name in directories
                if name not in IGNORED_DIRECTORIES
            ]

            visible_files = [
                filename
                for filename in filenames
                if Path(filename).suffix.lower()
                not in IGNORED_SUFFIXES
            ]

            if not directories and not visible_files:
                relative = Path(current).relative_to(root)
                empty_directories.append(str(relative) or ".")

        return True, evidence(
            root,
            capability,
            scope,
            directories=empty_directories[:200],
            total_count=len(empty_directories),
            truncated=len(empty_directories) > 200,
        )

    if capability == "filesystem.modified_today":
        today = datetime.now().astimezone().date()
        selected: list[dict[str, Any]] = []

        for path, stat in files:
            modified = datetime.fromtimestamp(
                stat.st_mtime
            ).astimezone()

            if modified.date() == today:
                selected.append(
                    {
                        "path": str(path.relative_to(root)),
                        "modified_iso": modified.isoformat(),
                        "size_bytes": stat.st_size,
                    }
                )

        selected.sort(
            key=lambda item: item["modified_iso"],
            reverse=True,
        )

        return True, evidence(
            root,
            capability,
            scope,
            files=selected[:200],
            total_count=len(selected),
            truncated=len(selected) > 200,
        )

    if capability == "filesystem.duplicate_files":
        files_by_size: dict[int, list[Path]] = defaultdict(list)

        for path, stat in files:
            if stat.st_size > 0:
                files_by_size[stat.st_size].append(path)

        duplicate_groups: list[dict[str, Any]] = []
        files_hashed = 0

        for size, candidate_paths in files_by_size.items():
            if len(candidate_paths) < 2:
                continue

            paths_by_hash: dict[str, list[Path]] = defaultdict(list)

            for path in candidate_paths:
                digest = hashlib.sha256()

                try:
                    with path.open("rb") as handle:
                        while True:
                            chunk = handle.read(1024 * 1024)

                            if not chunk:
                                break

                            digest.update(chunk)

                    paths_by_hash[digest.hexdigest()].append(path)
                    files_hashed += 1

                except OSError:
                    continue

            for digest, matching_paths in paths_by_hash.items():
                if len(matching_paths) > 1:
                    duplicate_groups.append(
                        {
                            "sha256": digest,
                            "size_bytes": size,
                            "files": [
                                str(path.relative_to(root))
                                for path in matching_paths
                            ],
                        }
                    )

        return True, evidence(
            root,
            capability,
            scope,
            duplicate_groups=duplicate_groups[:100],
            total_groups=len(duplicate_groups),
            files_hashed=files_hashed,
            truncated=len(duplicate_groups) > 100,
        )

    return False, f"Unsupported capability: {capability}"


def install_launcher() -> tuple[bool, str]:
    executable = shutil.which("sophyane")

    if not executable:
        return False, "The sophyane executable was not found in PATH."

    desktop = Path.home() / "Desktop"

    xdg_user_dir = shutil.which("xdg-user-dir")

    if xdg_user_dir:
        try:
            completed = subprocess.run(
                [xdg_user_dir, "DESKTOP"],
                text=True,
                capture_output=True,
                timeout=5,
                check=False,
            )

            candidate = completed.stdout.strip()

            if completed.returncode == 0 and candidate:
                desktop = Path(candidate).expanduser()

        except (OSError, subprocess.SubprocessError):
            pass

    desktop = desktop.resolve()
    default_desktop = (Path.home() / "Desktop").resolve()

    allowed_directories = {
        desktop,
        default_desktop,
        (Path.home() / ".local/share/applications").resolve(),
    }

    desktop.mkdir(
        parents=True,
        exist_ok=True,
    )

    target = (desktop / "sophyane.desktop").resolve()

    if target.parent not in allowed_directories:
        return False, (
            "Resolved launcher directory is outside the "
            "approved launcher allowlist."
        )

    content = (
        "[Desktop Entry]\n"
        "Type=Application\n"
        "Name=Sophyane\n"
        "Comment=Launch Sophyane\n"
        f"Exec={executable}\n"
        "Terminal=true\n"
        "Categories=Development;Utility;\n"
    )

    target.write_text(
        content,
        encoding="utf-8",
    )
    target.chmod(0o755)

    return True, json.dumps(
        {
            "ok": True,
            "capability": "platform.install_launcher",
            "launcher_path": str(target),
            "executable": executable,
            "bounded_write": True,
            "runtime_executed_action": True,
            "provider_selected_action": False,
            "sli_grounded": True,
        },
        indent=2,
    )


def format_bytes(value: int) -> str:
    units = ["B", "KB", "MB", "GB", "TB"]
    amount = float(value)

    for unit in units:
        if amount < 1024 or unit == units[-1]:
            return f"{amount:.2f} {unit}"

        amount /= 1024

    return f"{value} B"


def format_result(raw: str) -> str:
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return raw

    capability = data.get("capability")

    if capability == "filesystem.largest_file":
        return (
            "Largest file:\n"
            f"{data['path']}\n\n"
            f"Size: {format_bytes(data['size_bytes'])} "
            f"({data['size_bytes']} bytes)\n"
            f"Files inspected: {data['files_inspected']}\n"
            f"Scope: {data['scope']}\n\n"
            "Grounding evidence:\n"
            "- Read directly from filesystem metadata\n"
            "- No mutation performed\n"
            "- No shell command selected by the provider"
        )

    if capability == "filesystem.largest_file_parent":
        return (
            f"Largest file: {data['file']}\n"
            f"Containing folder: {data['parent_directory']}\n"
            f"Size: {format_bytes(data['size_bytes'])}"
        )

    if capability == "filesystem.top_largest_files":
        lines = [
            (
                f"{index}. {item['path']} — "
                f"{format_bytes(item['size_bytes'])}"
            )
            for index, item in enumerate(data["files"], 1)
        ]

        return "Largest files:\n" + "\n".join(lines)

    if capability == "filesystem.oldest_file":
        return (
            "Oldest modified file:\n"
            f"{data['path']}\n\n"
            f"Modified: {data['modified_iso']}\n"
            f"Size: {format_bytes(data['size_bytes'])}"
        )

    if capability == "filesystem.file_count":
        return (
            f"Files: {data['count']}\n"
            f"Scope: {data['scope']}"
        )

    if capability == "filesystem.folder_count":
        count = data.get("count", data.get("folder_count", 0))
        return (
            f"Folders: {count}\n"
            f"Scope: {data.get('scope', 'unknown')}"
        )

    if capability == "filesystem.directory_size":
        return (
            f"Total size: {format_bytes(data['size_bytes'])}\n"
            f"Bytes: {data['size_bytes']}\n"
            f"Files inspected: {data['files_inspected']}\n"
            f"Scope: {data['scope']}"
        )

    if capability == "filesystem.empty_directories":
        directories = data["directories"]

        return (
            f"Empty directories: {data['total_count']}\n"
            + (
                "\n".join(directories)
                if directories
                else "None found."
            )
        )

    if capability == "filesystem.modified_today":
        files = data["files"]

        lines = [
            f"{item['path']} — {item['modified_iso']}"
            for item in files
        ]

        return (
            f"Files modified today: {data['total_count']}\n"
            + (
                "\n".join(lines)
                if lines
                else "None found."
            )
        )

    if capability == "filesystem.duplicate_files":
        groups = data["duplicate_groups"]

        if not groups:
            return (
                "No duplicate files were found in the selected scope.\n"
                f"Files hashed: {data['files_hashed']}"
            )

        output: list[str] = [
            f"Duplicate groups: {data['total_groups']}"
        ]

        for index, group in enumerate(groups, 1):
            output.append(
                f"\nGroup {index} — "
                f"{format_bytes(group['size_bytes'])}"
            )

            output.extend(
                f"  {path}"
                for path in group["files"]
            )

        return "\n".join(output)

    if capability == "platform.install_launcher":
        return (
            "Sophyane launcher installed successfully.\n"
            f"Path: {data['launcher_path']}\n"
            f"Executable: {data['executable']}\n"
            "The write was limited to an approved launcher directory."
        )

    return raw


def wrap_adaptive_loop(
    original: Callable[..., str],
) -> Callable[..., str]:
    if getattr(original, "_sophyane_v20_wrapped", False):
        return original

    def run(**kwargs: Any) -> str:
        # SOPHYANE_V20_CANONICAL_MERGED_REQUEST
        # The original request preserves the user's initial intent, while
        # initial_text contains the provider-approved request after any live
        # keyboard instructions have been merged.
        original_request = str(
            kwargs.get("original_request")
            or ""
        ).strip()
        final_request = str(
            kwargs.get("initial_text")
            or ""
        ).strip()

        request_parts: list[str] = []

        if original_request:
            request_parts.append(original_request)

        if (
            final_request
            and final_request.casefold() != original_request.casefold()
        ):
            request_parts.append(
                "Final merged requirements after live steering:\n"
                + final_request
            )

        request = "\n\n".join(request_parts).strip()

                # SOPHYANE_CANONICAL_FILESYSTEM_CLASSIFICATION
        # Generated provider output and merged runtime text must never alter
        # the deterministic operation selected from the user's request.
        action = classify_request(original_request)

        if action is None:

            return original(**kwargs)

        workspace = Path(
            kwargs.get("workspace")
            or Path.cwd()
        ).resolve()

        print(
            "[SLI V20] deterministic capability selected: "
            f"{action['type']}",
            flush=True,
        )

        # SOPHYANE_TRACE_CANONICAL_AT_V20_ENTRY
        print(
            "\n[REQUEST TRACE 3: V20 ENTRY]\n"
            + "kwargs.original_request="
            + repr(kwargs.get("original_request"))
            + "\nkwargs.initial_text="
            + repr(kwargs.get("initial_text"))
            + "\nresolved_request="
            + repr(request)
            + "\n[END REQUEST TRACE 3]\n",
            flush=True,
        )

        # SOPHYANE_V20_MULTI_SCOPE_EXECUTION
        # Execute the selected filesystem capability independently for every
        # scope explicitly present in the canonical merged request.
        normalized_request = " ".join(request.casefold().split())

        workspace_terms = (
            "workspace",
            "working directory",
            "current directory",
            "current project",
            "this project",
            "repository",
            "repo",
        )

        computer_terms = (
            "my computer",
            "computer",
            "user home",
            "home directory",
            "whole home",
            "entire home",
        )

        wants_workspace = any(
            term in normalized_request
            for term in workspace_terms
        )

        wants_computer = any(
            term in normalized_request
            for term in computer_terms
        )

        scope_requests: list[tuple[str, str]] = []

        if wants_workspace:
            scope_requests.append(
                (
                    "Workspace",
                    "Run this filesystem request in the active workspace only.",
                )
            )

        if wants_computer:
            scope_requests.append(
                (
                    "Computer",
                    "Run this filesystem request in my computer home directory.",
                )
            )

        # Retain existing behaviour for requests containing zero or one
        # explicitly recognized scope.
        if len(scope_requests) < 2:
            scope_requests = [("Result", request)]

        rendered_results: list[str] = []
        failures: list[str] = []

        for scope_label, scope_request in scope_requests:
            print(
                "[SLI V20] executing scope: "
                f"{scope_label.casefold()}",
                flush=True,
            )

            ok, result = execute_capability(
                action,
                workspace,
                scope_request,
            )

            if not ok:
                failures.append(
                    f"{scope_label}: {result}"
                )
                continue

            rendered = format_result(result).strip()

            if len(scope_requests) == 1:
                rendered_results.append(rendered)
            else:
                rendered_results.append(
                    f"{scope_label}\n"
                    f"{'─' * len(scope_label)}\n"
                    f"{rendered}"
                )

        if not rendered_results:
            print(
                "[SLI V20] capability failed safely",
                flush=True,
            )
            return (
                "Capability execution failed safely:\n"
                + "\n".join(failures)
            )

        if failures:
            rendered_results.append(
                "Scope failures\n"
                "──────────────\n"
                + "\n".join(failures)
            )

        print(
            "[SLI V20] grounded evidence accepted",
            flush=True,
        )

        try:
            from sophyane.semantic_ontology_bridge import note_execution_success
            note_execution_success(
                str(kwargs.get("original_request") or request or "")
            )
        except Exception:
            pass

        return "\n\n".join(rendered_results)

    run._sophyane_v20_wrapped = True
    return run


def install_filesystem_capabilities_v20() -> None:
    global _INSTALLED

    if _INSTALLED:
        return

    from sophyane import adaptive_execution

    adaptive_execution.run_adaptive_loop = wrap_adaptive_loop(
        adaptive_execution.run_adaptive_loop
    )

    # tui_v2 imports run_adaptive_loop directly in some versions.
    try:
        from sophyane import tui_v2

        if hasattr(tui_v2, "run_adaptive_loop"):
            tui_v2.run_adaptive_loop = wrap_adaptive_loop(
                tui_v2.run_adaptive_loop
            )

    except Exception:
        pass

    _INSTALLED = True
