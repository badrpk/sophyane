"""Attach Cursor-style Tab to ObservableTUI."""

from __future__ import annotations

from typing import Any


def install_cursor_tab_patch() -> None:
    from sophyane import tui_v2
    from sophyane.cursor_tab import (
        install_on_tui,
        read_main_prompt,
    )

    if getattr(
        tui_v2.ObservableTUI,
        "_cursor_tab_patch_installed",
        False,
    ):
        return

    original_init = tui_v2.ObservableTUI.__init__

    def init(
        self: Any,
        *args: Any,
        **kwargs: Any,
    ) -> None:
        original_init(self, *args, **kwargs)

        try:
            install_on_tui(self)
        except Exception:
            pass

    def read_prompt(
        self: Any,
        prompt_text: str = "❯ ",
    ) -> str:
        return read_main_prompt(self, prompt_text)

    tui_v2.ObservableTUI.__init__ = init
    tui_v2.ObservableTUI.read_prompt = read_prompt
    tui_v2.ObservableTUI._cursor_tab_patch_installed = True
