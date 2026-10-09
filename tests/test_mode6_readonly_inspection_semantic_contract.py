from sophyane.human_conversation import (
    _default_responder,
)


def test_mode6_semantic_prompt_distinguishes_readonly_work(
    monkeypatch,
):
    captured = {}

    class FakeReasoner:
        def __call__(self, operation, payload):
            captured["operation"] = operation
            captured["payload"] = payload
            return {
                "reply": "Routing decision pending execution.",
                "semantic_disposition": "actionable_mission",
            }

    monkeypatch.setattr(
        "sophyane.discovery_provider_reasoner.SessionProviderReasoner",
        lambda *args, **kwargs: FakeReasoner(),
    )

    _default_responder(
        "Inspect actual repository files without modifying them.",
        {
            "trusted_context": {},
            "recent_turns": [],
        },
    )

    instructions = " ".join(
        captured["payload"]["instructions"]
    )

    assert "read-only" in instructions
    assert "repository files" in instructions
    assert "actionable_mission" in instructions
    assert "conceptual explanations" in instructions
    assert "guarded executor" in instructions
