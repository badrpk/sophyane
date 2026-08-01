"""Deterministic startup reporting and read-only request interception."""

from __future__ import annotations

import os
import re
from datetime import datetime
from pathlib import Path


_ONTOLOGY_PRINTED = False


def is_latest_file_query(text: object) -> bool:
    """Recognise natural wording for the most recently modified file."""
    if text is None:
        return False

    value = " ".join(str(text).lower().strip().split())

    if not value:
        return False

    # It must concern a file.
    if not re.search(r"\b(file|document|code|script)\b", value):
        return False

    # It must concern recent modification/amendment.
    recent = bool(
        re.search(
            r"\b(last|latest|newest|most recent|recently)\b",
            value,
        )
    )

    modified = bool(
        re.search(
            r"\b(amend|amended|amendment|modify|modified|"
            r"change|changed|edit|edited|update|updated|touch|touched)\b",
            value,
        )
    )

    # Handles:
    # "what last file i amended"
    # "which file was modified most recently"
    # "show my newest file"
    if recent and modified:
        return True

    if recent and re.search(
        r"\b(which|what|show|find|tell|where)\b",
        value,
    ):
        return True

    return False


def _candidate_request_values(local_values: dict[str, object]) -> list[str]:
    """Collect all non-empty strings from a live request function."""
    preferred_names = (
        "original_message",
        "original_request",
        "user_message",
        "message",
        "request",
        "approved_request",
        "refined_request",
        "resolved_request",
        "semantic_request",
        "user_input",
        "prompt",
        "query",
        "text",
    )

    results: list[str] = []
    seen: set[str] = set()

    for name in preferred_names:
        if name not in local_values:
            continue

        value = local_values[name]

        if value is None:
            continue

        text = str(value).strip()

        if text and text not in seen:
            seen.add(text)
            results.append(text)

    # Also inspect other function arguments and simple local strings.
    for name, value in local_values.items():
        if name.startswith("_"):
            continue

        if not isinstance(value, str):
            continue

        text = value.strip()

        if text and text not in seen:
            seen.add(text)
            results.append(text)

    return results


def should_intercept_latest_file(
    local_values: dict[str, object],
) -> bool:
    return any(
        is_latest_file_query(candidate)
        for candidate in _candidate_request_values(local_values)
    )


def latest_file_report() -> str:
    """Find the newest accessible user file without invoking an AI provider."""
    home = Path.home()

    excluded_parts = {
        ".git",
        "__pycache__",
        ".pytest_cache",
        ".mypy_cache",
        ".ruff_cache",
        ".cache",
        ".local",
        ".npm",
        ".cargo",
        ".rustup",
        ".venv",
        "venv",
        "node_modules",
        "build",
        "dist",
    }

    excluded_suffixes = (
        ".pyc",
        ".pyo",
        ".swp",
        ".tmp",
        ".lock",
    )

    newest_path: Path | None = None
    newest_mtime = -1.0
    newest_size = 0

    for root, directories, files in os.walk(
        home,
        topdown=True,
        followlinks=False,
    ):
        directories[:] = [
            name
            for name in directories
            if name not in excluded_parts
            and not name.startswith(".Trash")
        ]

        root_path = Path(root)

        for filename in files:
            if filename.startswith("."):
                continue

            if filename.endswith(excluded_suffixes):
                continue

            path = root_path / filename

            try:
                stat = path.stat()
            except (OSError, PermissionError):
                continue

            if not path.is_file():
                continue

            if stat.st_mtime > newest_mtime:
                newest_path = path
                newest_mtime = stat.st_mtime
                newest_size = stat.st_size

    if newest_path is None:
        return (
            "Latest-file inspection completed, but no accessible "
            "user file was found."
        )

    modified = datetime.fromtimestamp(newest_mtime).astimezone()

    return "\n".join(
        [
            "Most recently modified accessible user file",
            "────────────────────────────────────────────────────────",
            f"Path     : {newest_path}",
            f"Modified : {modified:%Y-%m-%d %H:%M:%S %Z}",
            f"Size     : {newest_size:,} bytes",
            "",
            "This result is based on filesystem modification time.",
        ]
    )


def print_startup_ontology_once() -> None:
    """Show detailed startup diagnostics only when requested."""
    global _ONTOLOGY_PRINTED

    if _ONTOLOGY_PRINTED:
        return

    _ONTOLOGY_PRINTED = True

    verbose = str(
        os.environ.get("SOPHYANE_VERBOSE_STARTUP", "")
    ).strip().lower()

    if verbose not in {"1", "true", "yes", "on"}:
        return

    try:
        from .semantic_ontology import render_semantic_ontology_report

        print(render_semantic_ontology_report())
    except Exception as error:
        print(f"◆ Startup diagnostics unavailable: {error}")


# SOPHYANE_RAW_INPUT_CAPTURE_V6

_PENDING_LATEST_FILE_QUERY = False
_INPUT_CAPTURE_INSTALLED = False
_ORIGINAL_BUILTIN_INPUT = None
_ORIGINAL_RICH_CONSOLE_INPUT = None


def _remember_typed_input(value: object) -> None:
    """Remember a latest-file question across later SLI menu input."""
    global _PENDING_LATEST_FILE_QUERY

    try:
        text = str(value).strip()
    except Exception:
        return

    if is_latest_file_query(text):
        _PENDING_LATEST_FILE_QUERY = True


def consume_pending_latest_file_query() -> bool:
    """Consume one preserved latest-file request."""
    global _PENDING_LATEST_FILE_QUERY

    pending = _PENDING_LATEST_FILE_QUERY
    _PENDING_LATEST_FILE_QUERY = False

    return pending


def clear_pending_latest_file_query() -> None:
    """Explicitly clear pending interception state."""
    global _PENDING_LATEST_FILE_QUERY
    _PENDING_LATEST_FILE_QUERY = False


# SOPHYANE_MULTI_TUI_INPUT_CAPTURE_V8

_MULTI_TUI_CAPTURE_INSTALLED = False
_CAPTURED_ORIGINALS = {}


def install_input_capture() -> None:
    """Capture typed input from supported terminal UI frameworks.

    This is the single canonical input-capture installer. It includes
    built-in input handling and optional integrations for available TUI
    frameworks.
    """
    global _MULTI_TUI_CAPTURE_INSTALLED

    if _MULTI_TUI_CAPTURE_INSTALLED:
        return

    _MULTI_TUI_CAPTURE_INSTALLED = True

    # --------------------------------------------------------
    # Built-in input
    # --------------------------------------------------------

    try:
        import builtins

        original = builtins.input

        if not getattr(original, "_sophyane_capture_v8", False):
            _CAPTURED_ORIGINALS["builtins.input"] = original

            _bound_captured_builtin_input = original
            def captured_builtin_input(prompt=""):
                value = _bound_captured_builtin_input(prompt)
                _remember_typed_input(value)
                return value

            captured_builtin_input._sophyane_capture_v8 = True
            builtins.input = captured_builtin_input
    except Exception:
        pass

    # --------------------------------------------------------
    # Rich Console.input
    # --------------------------------------------------------

    try:
        from rich.console import Console

        original = Console.input

        if not getattr(original, "_sophyane_capture_v8", False):
            _CAPTURED_ORIGINALS["rich.Console.input"] = original

            _bound_captured_rich_input = original
            def captured_rich_input(self, *args, **kwargs):
                value = _bound_captured_rich_input(self, *args, **kwargs)
                _remember_typed_input(value)
                return value

            captured_rich_input._sophyane_capture_v8 = True
            Console.input = captured_rich_input
    except Exception:
        pass

    # --------------------------------------------------------
    # prompt_toolkit PromptSession.prompt
    # --------------------------------------------------------

    try:
        from prompt_toolkit import PromptSession

        original = PromptSession.prompt

        if not getattr(original, "_sophyane_capture_v8", False):
            _CAPTURED_ORIGINALS[
                "prompt_toolkit.PromptSession.prompt"
            ] = original

            _bound_captured_prompt_session = original
            def captured_prompt_session(self, *args, **kwargs):
                value = _bound_captured_prompt_session(self, *args, **kwargs)
                _remember_typed_input(value)
                return value

            captured_prompt_session._sophyane_capture_v8 = True
            PromptSession.prompt = captured_prompt_session
    except Exception:
        pass

    # --------------------------------------------------------
    # prompt_toolkit PromptSession.prompt_async
    # --------------------------------------------------------

    try:
        from prompt_toolkit import PromptSession

        original_async = PromptSession.prompt_async

        if not getattr(original_async, "_sophyane_capture_v8", False):
            _CAPTURED_ORIGINALS[
                "prompt_toolkit.PromptSession.prompt_async"
            ] = original_async

            _bound_captured_prompt_session_async = original_async
            async def captured_prompt_session_async(
                self,
                *args,
                **kwargs,
            ):
                value = await _bound_captured_prompt_session_async(
                    self,
                    *args,
                    **kwargs,
                )
                _remember_typed_input(value)
                return value

            captured_prompt_session_async._sophyane_capture_v8 = True
            PromptSession.prompt_async = captured_prompt_session_async
    except Exception:
        pass

    # --------------------------------------------------------
    # prompt_toolkit.shortcuts.prompt
    # --------------------------------------------------------

    try:
        import prompt_toolkit.shortcuts as shortcuts

        original = shortcuts.prompt

        if not getattr(original, "_sophyane_capture_v8", False):
            _CAPTURED_ORIGINALS[
                "prompt_toolkit.shortcuts.prompt"
            ] = original

            _bound_captured_shortcuts_prompt = original
            def captured_shortcuts_prompt(*args, **kwargs):
                value = _bound_captured_shortcuts_prompt(*args, **kwargs)
                _remember_typed_input(value)
                return value

            captured_shortcuts_prompt._sophyane_capture_v8 = True
            shortcuts.prompt = captured_shortcuts_prompt
    except Exception:
        pass

    # --------------------------------------------------------
    # questionary Question.ask
    # --------------------------------------------------------

    try:
        from questionary.question import Question

        original = Question.ask

        if not getattr(original, "_sophyane_capture_v8", False):
            _CAPTURED_ORIGINALS["questionary.Question.ask"] = original

            _bound_captured_questionary_ask = original
            def captured_questionary_ask(self, *args, **kwargs):
                value = _bound_captured_questionary_ask(self, *args, **kwargs)
                _remember_typed_input(value)
                return value

            captured_questionary_ask._sophyane_capture_v8 = True
            Question.ask = captured_questionary_ask
    except Exception:
        pass

    # --------------------------------------------------------
    # questionary Question.unsafe_ask
    # --------------------------------------------------------

    try:
        from questionary.question import Question

        original = Question.unsafe_ask

        if not getattr(original, "_sophyane_capture_v8", False):
            _CAPTURED_ORIGINALS[
                "questionary.Question.unsafe_ask"
            ] = original

            _bound_captured_questionary_unsafe_ask = original
            def captured_questionary_unsafe_ask(
                self,
                *args,
                **kwargs,
            ):
                value = _bound_captured_questionary_unsafe_ask(self, *args, **kwargs)
                _remember_typed_input(value)
                return value

            captured_questionary_unsafe_ask._sophyane_capture_v8 = True
            Question.unsafe_ask = captured_questionary_unsafe_ask
    except Exception:
        pass

    # --------------------------------------------------------
    # InquirerPy BaseSimplePrompt.execute
    # --------------------------------------------------------

    try:
        from InquirerPy.base.simple import BaseSimplePrompt

        original = BaseSimplePrompt.execute

        if not getattr(original, "_sophyane_capture_v8", False):
            _CAPTURED_ORIGINALS[
                "InquirerPy.BaseSimplePrompt.execute"
            ] = original

            _bound_captured_inquirer_execute = original
            def captured_inquirer_execute(self, *args, **kwargs):
                value = _bound_captured_inquirer_execute(self, *args, **kwargs)
                _remember_typed_input(value)
                return value

            captured_inquirer_execute._sophyane_capture_v8 = True
            BaseSimplePrompt.execute = captured_inquirer_execute
    except Exception:
        pass

    # --------------------------------------------------------
    # InquirerPy BaseSimplePrompt.execute_async
    # --------------------------------------------------------

    try:
        from InquirerPy.base.simple import BaseSimplePrompt

        original_async = BaseSimplePrompt.execute_async

        if not getattr(original_async, "_sophyane_capture_v8", False):
            _CAPTURED_ORIGINALS[
                "InquirerPy.BaseSimplePrompt.execute_async"
            ] = original_async

            _bound_captured_inquirer_execute_async = original_async
            async def captured_inquirer_execute_async(
                self,
                *args,
                **kwargs,
            ):
                value = await _bound_captured_inquirer_execute_async(
                    self,
                    *args,
                    **kwargs,
                )
                _remember_typed_input(value)
                return value

            captured_inquirer_execute_async._sophyane_capture_v8 = True
            BaseSimplePrompt.execute_async = (
                captured_inquirer_execute_async
            )
    except Exception:
        pass


def input_capture_status() -> list[str]:
    """Return the terminal input APIs wrapped by V8."""
    return sorted(_CAPTURED_ORIGINALS)

