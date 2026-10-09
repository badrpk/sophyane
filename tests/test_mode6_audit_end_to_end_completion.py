from pathlib import Path

from sophyane import human_conversation_cli as cli
from sophyane.rsi.authority import Operation


def test_mode6_audit_returns_grounded_final_answer_without_mutation(
    tmp_path: Path,
    monkeypatch,
):
    target = tmp_path / "guardrails.txt"
    target.write_text(
        "tenant isolation: enforced\n"
        "SSRF protection: partial\n"
        "idempotency: enforced\n",
        encoding="utf-8",
    )

    before = target.read_bytes()
    provider_calls = []

    class FakeHumanProvider:
        def generate(
            self,
            prompt,
            system_prompt,
            *,
            operation=Operation.READ_ONLY_OPERATION,
        ):
            provider_calls.append((prompt, operation))

            if len(provider_calls) == 1:
                return (
                    '{"action":{"type":"read_file",'
                    '"path":"guardrails.txt"}}'
                )

            assert "tenant isolation: enforced" in prompt
            assert "SSRF protection: partial" in prompt

            return (
                '{"action":{"type":"respond",'
                '"message":"Audit findings: tenant isolation and '
                'idempotency are enforced; SSRF protection is partial."}}'
            )

    monkeypatch.setattr(
        "sophyane.main.create_provider",
        lambda _config: FakeHumanProvider(),
    )
    monkeypatch.setattr(
        "sophyane.main.load_runtime_config",
        lambda: {},
    )
    monkeypatch.setattr(
        "sophyane.config.load_config",
        lambda: {},
    )
    monkeypatch.setattr(
        "sophyane.providers.human_conversation.HumanConversationProvider",
        FakeHumanProvider,
    )

    request_text = (
        "Audit whether Sophyane enforces its execution guardrails "
        "deterministically. Report the findings."
    )

    result = cli._execute_repository_request(
        request_text,
        workspace=tmp_path,
    )

    assert len(provider_calls) == 2
    assert all(
        operation is Operation.READ_ONLY_OPERATION
        for _, operation in provider_calls
    )

    assert "Audit findings:" in str(result)
    assert "SSRF protection is partial" in str(result)
    assert "Stopped after bounded execution loop" not in str(result)
    assert "no implementation target was specified" not in str(result)

    assert target.read_bytes() == before
    assert sorted(p.name for p in tmp_path.iterdir()) == [
        "guardrails.txt"
    ]
