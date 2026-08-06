from sophyane.personal_fact_resolver import (
    extract_company_candidates,
    try_personal_semantic_reply,
)


def test_company_extraction_removes_legal_context() -> None:
    values = extract_company_candidates(
        "Certificate of Formation for "
        "Example Ventures LLC was accepted."
    )

    assert values == [
        "Example Ventures LLC",
    ]


def test_company_extraction_preserves_suffix_period() -> None:
    values = extract_company_candidates(
        "Company name: Northstar Trading Inc."
    )

    assert values == [
        "Northstar Trading Inc.",
    ]


def test_policy_instruction_is_learned(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        "sophyane.personal_semantic_memory.STATE_DIR",
        tmp_path,
    )
    monkeypatch.setattr(
        "sophyane.personal_semantic_memory.MEMORY_FILE",
        tmp_path / "memory.json",
    )

    reply = try_personal_semantic_reply(
        "when I ask personal information, "
        "search my email"
    )

    assert reply is not None
    assert "Instruction interpreted as policy: True" in reply
    assert "Email searched for this instruction: False" in reply


def test_personal_question_searches_private_email(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        "sophyane.personal_semantic_memory.STATE_DIR",
        tmp_path,
    )
    monkeypatch.setattr(
        "sophyane.personal_semantic_memory.MEMORY_FILE",
        tmp_path / "memory.json",
    )

    try_personal_semantic_reply(
        "when I ask personal information, "
        "search my email"
    )

    monkeypatch.setattr(
        "sophyane.email_account_registry.active_profile",
        lambda: "default",
    )

    monkeypatch.setattr(
        "sophyane.connectors.email_imap.handler.execute",
        lambda **_kwargs: {
            "ok": True,
            "matches": 1,
            "formatted": (
                "Certificate of Formation for "
                "Example Ventures LLC was accepted."
            ),
        },
    )

    monkeypatch.setattr(
        "sophyane.personal_fact_resolver.sys.stdin.isatty",
        lambda: False,
    )

    reply = try_personal_semantic_reply(
        "what is name of my USA company?"
    )

    assert reply is not None
    assert "Answer: Example Ventures LLC" in reply
    assert "Private source searched: active email" in reply
    assert "Public internet fallback: blocked" in reply


def test_confirmed_fact_answers_without_research(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        "sophyane.personal_semantic_memory.STATE_DIR",
        tmp_path,
    )
    monkeypatch.setattr(
        "sophyane.personal_semantic_memory.MEMORY_FILE",
        tmp_path / "memory.json",
    )

    learned = try_personal_semantic_reply(
        "My USA company is Atlas Ventures LLC."
    )

    assert learned is not None

    reply = try_personal_semantic_reply(
        "what is name of my USA company?"
    )

    assert reply is not None
    assert "Answer: Atlas Ventures LLC" in reply
    assert "Source: confirmed personal fact" in reply
