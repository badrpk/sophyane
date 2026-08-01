from __future__ import annotations

import pytest

from sophyane.expert import exam


def test_llm_generator_preserves_provider_creation_error(
    monkeypatch,
) -> None:
    def broken_provider(_config):
        raise RuntimeError("provider unavailable")

    monkeypatch.setattr(
        "sophyane.main.create_provider",
        broken_provider,
    )

    generate = exam._llm_generate()

    with pytest.raises(
        RuntimeError,
        match="provider unavailable",
    ):
        generate("question", "system")
