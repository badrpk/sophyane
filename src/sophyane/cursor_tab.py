"""Cursor-style main prompt for Sophyane."""

from __future__ import annotations

import json
import os
import re
import shlex
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable

STATE_DIR = Path.home() / ".local" / "state" / "sophyane"
CONFIG_PATH = STATE_DIR / "cursor_tab.json"
HISTORY_PATH = STATE_DIR / "cursor_tab_history"


@dataclass
class TabSettings:
    enabled: bool = True
    context: bool = True
    privacy: bool = True
    confidence: float = 0.55
    debounce_ms: int = 180
    max_workspace_files: int = 40
    max_suggestions: int = 30


def load_settings() -> TabSettings:
    defaults = TabSettings()

    try:
        data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return defaults

    if not isinstance(data, dict):
        return defaults

    values = asdict(defaults)

    for key in values:
        if key in data:
            values[key] = data[key]

    try:
        values["confidence"] = max(
            0.0,
            min(1.0, float(values["confidence"])),
        )
        values["debounce_ms"] = max(
            0,
            min(3000, int(values["debounce_ms"])),
        )
        values["max_workspace_files"] = max(
            1,
            min(300, int(values["max_workspace_files"])),
        )
        values["max_suggestions"] = max(
            1,
            min(100, int(values["max_suggestions"])),
        )
    except (TypeError, ValueError):
        return defaults

    return TabSettings(**values)


def save_settings(settings: TabSettings) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    temporary = CONFIG_PATH.with_suffix(".tmp")
    temporary.write_text(
        json.dumps(
            asdict(settings),
            indent=2,
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    temporary.replace(CONFIG_PATH)


def safe_workspace(tui: Any) -> Path | None:
    value = getattr(tui, "active_workspace", None)

    if value is None:
        return None

    try:
        path = Path(value).expanduser().resolve()
    except (OSError, RuntimeError, TypeError):
        return None

    return path if path.is_dir() else None


def workspace_files(
    workspace: Path | None,
    limit: int,
) -> list[str]:
    if workspace is None:
        return []

    ignored = {
        ".git",
        ".hg",
        ".svn",
        "__pycache__",
        "node_modules",
        ".venv",
        "venv",
        "dist",
        "build",
    }

    results: list[str] = []

    try:
        paths = workspace.rglob("*")
    except OSError:
        return results

    for path in paths:
        if len(results) >= limit:
            break

        try:
            relative = path.relative_to(workspace)
        except ValueError:
            continue

        if any(part in ignored for part in relative.parts):
            continue

        try:
            if not path.is_file():
                continue
        except OSError:
            continue

        results.append(relative.as_posix())

    return results


def recent_messages(tui: Any) -> list[str]:
    results: list[str] = []

    for value in getattr(tui, "project_requirements", []) or []:
        text = str(value or "").strip()

        if text:
            results.append(text)

    for item in getattr(tui, "history", []) or []:
        if (
            isinstance(item, (list, tuple))
            and len(item) >= 2
            and str(item[0]).lower() == "user"
        ):
            text = str(item[1] or "").strip()

            if text:
                results.append(text)

    active = str(
        getattr(tui, "active_request", "") or ""
    ).strip()

    if active:
        results.append(active)

    return results[-15:]


def deduplicate(values: Iterable[str]) -> list[str]:
    results: list[str] = []
    seen: set[str] = set()

    for value in values:
        normalized = " ".join(str(value).split())

        if not normalized:
            continue

        marker = normalized.casefold()

        if marker in seen:
            continue

        seen.add(marker)
        results.append(normalized)

    return results


def typo_correction(text: str) -> str:
    corrections = {
        "brower": "browser",
        "resposive": "responsive",
        "interace": "interface",
        "funtion": "function",
        "firet": "first",
        "becuase": "because",
        "projet": "project",
        "fancyer": "fancier",
    }

    corrected = text

    for wrong, right in corrections.items():
        corrected = re.sub(
            rf"\b{re.escape(wrong)}\b",
            right,
            corrected,
            flags=re.IGNORECASE,
        )

    return corrected


def static_suggestions(text: str) -> list[str]:
    normalized = " ".join(text.lower().split())

    values = [
        "make snake game",
        "make snake game in the browser",
        "make a snake game",
        "make a browser-based snake game",
        "make it browser based",
        "make it responsive for mobile phones",
        "make the interface modern and attractive",
        "continue the existing project",
        "inspect the current project",
        "test the current project and repair failures",
        "open the current project in the browser",
        "add mobile touch controls",
        "preserve existing behavior while improving the design",
        "verify the result before completion",
        "/inspect",
        "/status",
        "/new",
        "/tab status",
        "/tab help",
    ]

    prefix_map = {
        "mak": [
            "make snake game",
            "make snake game in the browser",
            "make a snake game",
            "make a browser-based snake game",
        ],
        "make s": [
            "make snake game",
            "make snake game in the browser",
        ],
        "bro": ["browser based"],
        "mob": ["mobile responsive"],
        "res": ["responsive for mobile phones"],
        "fan": ["fancy modern interface"],
        "tes": ["test the current project and repair failures"],
        "fix": ["fix the current project"],
        "ope": ["open the current project in the browser"],
        "cont": ["continue the existing project"],
        "ins": ["inspect the current project"],
        "/ta": ["/tab status", "/tab help"],
    }

    preferred: list[str] = []

    for prefix, suggestions in prefix_map.items():
        if normalized.startswith(prefix):
            preferred.extend(suggestions)

    corrected = typo_correction(text)

    if corrected != text:
        preferred.insert(0, corrected)

    return preferred + values


def build_suggestions(tui: Any, text: str) -> list[str]:
    settings = getattr(
        tui,
        "_cursor_tab_settings",
        load_settings(),
    )

    candidates = static_suggestions(text)

    if settings.context:
        candidates.extend(reversed(recent_messages(tui)))

        workspace = safe_workspace(tui)

        for path in workspace_files(
            workspace,
            settings.max_workspace_files,
        ):
            candidates.extend(
                [
                    f"inspect {path}",
                    f"edit {path}",
                    f"fix {path}",
                    f"explain {path}",
                ]
            )

    candidates = deduplicate(candidates)

    if not text:
        return candidates[: settings.max_suggestions]

    lower = text.casefold()
    matches: list[str] = []

    prefix_matches: list[str] = []
    fuzzy_matches: list[str] = []

    for candidate in candidates:
        candidate_lower = candidate.casefold()

        if candidate_lower == lower:
            continue

        if candidate_lower.startswith(lower):
            prefix_matches.append(candidate)
            continue

        words = lower.split()

        if words and all(word in candidate_lower for word in words):
            fuzzy_matches.append(candidate)

    # Ghost text requires the candidate to begin with the exact
    # current buffer. Keep fuzzy candidates only after compatible
    # prefix candidates so Tab always has an insertable suffix.
    matches = prefix_matches + fuzzy_matches
    return matches[: settings.max_suggestions]


class ProjectAutoSuggest:
    def __init__(self, tui: Any) -> None:
        self.tui = tui
        self.last_text = ""
        self.values_cache: list[str] = []
        self.index = 0

    def values(self, text: str) -> list[str]:
        if text != self.last_text:
            self.last_text = text
            self.values_cache = build_suggestions(
                self.tui,
                text,
            )
            self.index = 0

        return self.values_cache

    def cycle(self, text: str, delta: int) -> None:
        values = self.values(text)

        if not values:
            self.index = 0
            return

        self.index = (self.index + delta) % len(values)

    def reject(self) -> None:
        self.values_cache = []
        self.index = 0

    def get_suggestion(self, buffer: Any, document: Any) -> Any:
        from prompt_toolkit.auto_suggest import Suggestion

        settings = getattr(
            self.tui,
            "_cursor_tab_settings",
            load_settings(),
        )

        if not settings.enabled:
            return None

        text = document.text
        values = self.values(text)

        if not values:
            return None

        selected = values[self.index % len(values)]

        if selected.casefold().startswith(text.casefold()):
            suffix = selected[len(text) :]

            if suffix:
                return Suggestion(suffix)

        return None

    async def get_suggestion_async(
        self,
        buffer: Any,
        document: Any,
    ) -> Any:
        """Async prompt_toolkit compatibility wrapper."""
        return self.get_suggestion(buffer, document)


def accept_full(event: Any) -> bool:
    suggestion = event.current_buffer.suggestion

    if suggestion is None:
        return False

    event.current_buffer.insert_text(suggestion.text)
    return True


def accept_word(event: Any) -> bool:
    suggestion = event.current_buffer.suggestion

    if suggestion is None or not suggestion.text:
        return False

    match = re.match(r"(\s*\S+\s*)", suggestion.text)
    piece = match.group(1) if match else suggestion.text
    event.current_buffer.insert_text(piece)
    return True


def insert_prefix(event: Any, prefix: str) -> None:
    buffer = event.current_buffer

    if buffer.text.strip():
        buffer.insert_text(" ")

    buffer.insert_text(prefix)


def status_text(settings: TabSettings, tui: Any) -> str:
    return "\n".join(
        [
            "Cursor-style Tab:",
            f"- enabled: {settings.enabled}",
            f"- context: {settings.context}",
            f"- privacy: {settings.privacy}",
            f"- confidence: {settings.confidence:.2f}",
            f"- debounce: {settings.debounce_ms} ms",
            f"- workspace: {safe_workspace(tui) or 'none'}",
            "",
            "Keys:",
            "- Tab: accept full suggestion",
            "- Ctrl+Right: accept next suggested word",
            "- Alt+]: next suggestion",
            "- Alt+[: previous suggestion",
            "- Escape: reject suggestion",
            "- Ctrl+K: inline-edit request",
            "- Alt+Enter: quick question",
            "- Ctrl+L: include project context",
        ]
    )


def handle_tab_command(tui: Any, message: str) -> bool:
    stripped = message.strip()

    if stripped == "/steering status":
        from sophyane.runtime_semantic_instruction import (
            semantic_status,
        )

        print(semantic_status(tui))
        return True

    if not stripped.startswith("/tab"):
        return False

    try:
        parts = shlex.split(stripped)
    except ValueError as error:
        print(f"Tab command error: {error}")
        return True

    command = parts[1].lower() if len(parts) > 1 else "status"
    value = parts[2] if len(parts) > 2 else ""

    settings = getattr(
        tui,
        "_cursor_tab_settings",
        load_settings(),
    )

    if command == "on":
        settings.enabled = True
        save_settings(settings)
        print("Cursor-style Tab enabled.")
        return True

    if command == "off":
        settings.enabled = False
        save_settings(settings)
        print("Cursor-style Tab disabled.")
        return True

    if command == "status":
        print(status_text(settings, tui))
        return True

    if command == "context":
        if value.lower() not in {"on", "off"}:
            print("Usage: /tab context on|off")
            return True

        settings.context = value.lower() == "on"
        save_settings(settings)
        print(
            "Tab project context "
            + ("enabled." if settings.context else "disabled.")
        )
        return True

    if command == "privacy":
        if value.lower() not in {"on", "off"}:
            print("Usage: /tab privacy on|off")
            return True

        settings.privacy = value.lower() == "on"
        save_settings(settings)
        print(
            "Tab privacy mode "
            + ("enabled." if settings.privacy else "disabled.")
        )
        return True

    if command == "confidence":
        try:
            settings.confidence = max(
                0.0,
                min(1.0, float(value)),
            )
        except ValueError:
            print("Usage: /tab confidence 0.0-1.0")
            return True

        save_settings(settings)
        print(
            f"Tab confidence set to "
            f"{settings.confidence:.2f}."
        )
        return True

    if command == "debounce":
        try:
            settings.debounce_ms = max(
                0,
                min(3000, int(value)),
            )
        except ValueError:
            print("Usage: /tab debounce MILLISECONDS")
            return True

        save_settings(settings)
        print(
            f"Tab debounce set to "
            f"{settings.debounce_ms} ms."
        )
        return True

    if command == "reset":
        settings = TabSettings()
        tui._cursor_tab_settings = settings
        save_settings(settings)
        print("Cursor-style Tab settings reset.")
        return True

    if command in {"help", "keys"}:
        print(status_text(settings, tui))
        print(
            "\nCommands:\n"
            "/tab on|off\n"
            "/tab status\n"
            "/tab context on|off\n"
            "/tab privacy on|off\n"
            "/tab confidence 0.0-1.0\n"
            "/tab debounce MILLISECONDS\n"
            "/tab reset\n"
            "/tab help"
        )
        return True

    print(
        f"Unknown /tab command: {command}\n"
        "Run /tab help."
    )
    return True


class CursorTabSession:
    def __init__(self, tui: Any) -> None:
        self.tui = tui
        self.tui._cursor_tab_settings = load_settings()
        self.suggester = ProjectAutoSuggest(tui)
        self.session = self.create_session()

    def create_session(self) -> Any:
        from prompt_toolkit import PromptSession
        from prompt_toolkit.history import FileHistory
        from prompt_toolkit.key_binding import KeyBindings

        STATE_DIR.mkdir(parents=True, exist_ok=True)
        bindings = KeyBindings()

        @bindings.add("tab")
        def tab_accept(event: Any) -> None:
            if not accept_full(event):
                event.current_buffer.insert_text("    ")

        @bindings.add("c-right")
        def word_accept(event: Any) -> None:
            if not accept_word(event):
                event.current_buffer.cursor_right()

        @bindings.add("escape")
        def reject(event: Any) -> None:
            self.suggester.reject()
            event.app.invalidate()

        @bindings.add("escape", "]")
        def next_suggestion(event: Any) -> None:
            self.suggester.cycle(
                event.current_buffer.text,
                1,
            )
            event.app.invalidate()

        @bindings.add("escape", "[")
        def previous_suggestion(event: Any) -> None:
            self.suggester.cycle(
                event.current_buffer.text,
                -1,
            )
            event.app.invalidate()

        @bindings.add("c-k")
        def inline_edit(event: Any) -> None:
            insert_prefix(
                event,
                "edit the current project code: ",
            )

        @bindings.add("escape", "enter")
        def quick_question(event: Any) -> None:
            insert_prefix(
                event,
                "answer a quick question about the current project: ",
            )

        @bindings.add("c-l")
        def project_context(event: Any) -> None:
            insert_prefix(
                event,
                "using the current project context, ",
            )

        return PromptSession(
            history=FileHistory(str(HISTORY_PATH)),
            auto_suggest=self.suggester,
            key_bindings=bindings,
            multiline=False,
            enable_history_search=True,
            complete_while_typing=False,
            mouse_support=False,
        )

    def prompt(self, prompt_text: str = "❯ ") -> str:
        while True:
            self.tui._cursor_tab_settings = load_settings()

            message = self.session.prompt(prompt_text)

            if handle_tab_command(self.tui, message):
                continue

            return message


def install_on_tui(tui: Any) -> None:
    if getattr(tui, "_cursor_tab_session", None) is None:
        tui._cursor_tab_session = CursorTabSession(tui)


def read_main_prompt(
    tui: Any,
    prompt_text: str = "❯ ",
) -> str:
    if (
        not sys.stdin.isatty()
        or not sys.stdout.isatty()
        or os.environ.get("SOPHYANE_DISABLE_CURSOR_TAB") == "1"
    ):
        return input(prompt_text)

    try:
        install_on_tui(tui)
        return tui._cursor_tab_session.prompt(prompt_text)
    except ImportError:
        return input(prompt_text)
    except Exception as error:
        print(
            "\nCursor-style Tab unavailable; "
            f"using standard input: {type(error).__name__}: {error}",
            file=sys.stderr,
        )
        return input(prompt_text)
