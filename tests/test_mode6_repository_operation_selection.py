from pathlib import Path

import pytest

from sophyane import human_conversation_cli as cli
from sophyane.rsi.authority import Operation


@pytest.mark.parametrize(
    ("request_text", "expected"),
    [
        (
            "make file lease-proof.txt",
            Operation.ORDINARY_WORKSPACE_MUTATION,
        ),
        (
            "modify src/sophyane/example.py",
            Operation.SOPHYANE_SOURCE_MUTATION,
        ),
        (
            "inspect src/sophyane/example.py",
            Operation.READ_ONLY_OPERATION,
        ),
    ],
)
def test_repository_operation_mapper_preserves_scope(
    request_text,
    expected,
):
    assert cli._repository_operation_for_request(request_text) is expected


@pytest.mark.parametrize(
    ("request_text", "expected"),
    [
        (
            "make file lease-proof.txt",
            Operation.ORDINARY_WORKSPACE_MUTATION,
        ),
        (
            "modify src/sophyane/example.py",
            Operation.SOPHYANE_SOURCE_MUTATION,
        ),
        (
            "inspect src/sophyane/example.py",
            Operation.READ_ONLY_OPERATION,
        ),
    ],
)
def test_execute_repository_request_passes_exact_operation_to_provider(
    tmp_path: Path,
    monkeypatch,
    request_text,
    expected,
):
    seen = []

    class FakeHumanProvider:
        def generate(
            self,
            prompt,
            system_prompt,
            *,
            operation=Operation.READ_ONLY_OPERATION,
        ):
            seen.append(operation)
            return '{"type":"respond","message":"ok"}'

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

    # Make isinstance(..., HumanConversationProvider) accept the fake
    # without invoking any real provider.
    monkeypatch.setattr(
        "sophyane.providers.human_conversation.HumanConversationProvider",
        FakeHumanProvider,
    )

    monkeypatch.setattr(
        "sophyane.adaptive_execution.run_adaptive_loop",
        lambda **kwargs: (kwargs["ask"]("follow-up"), "ok")[1],
    )

    result = cli._execute_repository_request(
        request_text,
        workspace=tmp_path,
    )

    assert result == "ok"
    assert seen == [Operation.READ_ONLY_OPERATION, expected]


def test_generic_repository_mutation_is_ordinary():
    from sophyane.human_conversation_cli import _repository_operation_for_request
    from sophyane.rsi.authority import Operation

    cases = [
        "create actual_provider_trace.txt containing exactly TEST",
        "Inside mode6_provider_proof, create actual_provider_trace.txt containing exactly TEST",
        "modify src/example.py",
        "update docs/example.md",
    ]

    for request_text in cases:
        assert (
            _repository_operation_for_request(request_text)
            is Operation.ORDINARY_WORKSPACE_MUTATION
        ), request_text


def test_protected_and_read_only_operations_remain_narrow():
    from sophyane.human_conversation_cli import _repository_operation_for_request
    from sophyane.rsi.authority import Operation

    assert (
        _repository_operation_for_request("modify src/sophyane/example.py")
        is Operation.SOPHYANE_SOURCE_MUTATION
    )

    assert (
        _repository_operation_for_request("inspect src/sophyane/example.py")
        is Operation.READ_ONLY_OPERATION
    )


def test_mode6_exact_literal_write_reuses_verified_capability_after_semantic_admission(
    tmp_path: Path,
    monkeypatch,
):
    """
    The genuine Mode-6 turn reaches intelligence before this execution
    boundary. Once semantic admission has classified it as actionable,
    Sophyane should reuse an existing verified deterministic capability
    rather than spend a second provider request.
    """

    request = (
        'make file mode6_exact_literal.py containing exactly:\n'
        'print("MODE6 EXACT LITERAL")'
    )

    provider_calls = []

    def forbidden_provider(*args, **kwargs):
        provider_calls.append((args, kwargs))
        raise AssertionError(
            "exact verified write unnecessarily acquired a second provider"
        )

    monkeypatch.setattr(
        "sophyane.main.create_provider",
        forbidden_provider,
    )

    result = cli._execute_repository_request(
        request,
        workspace=tmp_path,
    )

    target = tmp_path / "mode6_exact_literal.py"

    assert provider_calls == []
    assert target.read_bytes() == b'print("MODE6 EXACT LITERAL")'

    assert isinstance(
        result,
        cli._CompletedRepositoryExecution,
    )
    assert "filesystem.write_exact_verified" in str(result)



def test_local_initial_source_action_is_refreshed_with_trusted_provider(monkeypatch, tmp_path):
    from sophyane.providers.human_conversation import ProviderResponse
    from sophyane.human_conversation_cli import _execute_repository_request
    from sophyane.providers.human_conversation import HumanConversationProvider
    calls = []
    subject = HumanConversationProvider({})
    def generate(prompt, system_prompt, *, operation=Operation.READ_ONLY_OPERATION):
        calls.append(operation)
        if len(calls) == 1:
            return ProviderResponse('{"action":{"type":"write_file","path":"x.txt","content":"bad"}}', "local_gguf")
        return ProviderResponse('{"action":{"type":"write_file","path":"src/sophyane/x.py","content":"good"}}', "codex_cli")
    subject.generate = generate
    seen = []
    monkeypatch.setattr("sophyane.main.create_provider", lambda _config: subject)
    monkeypatch.setattr("sophyane.main.load_runtime_config", lambda: {})
    monkeypatch.setattr("sophyane.adaptive_execution.run_adaptive_loop", lambda **kwargs: seen.append(kwargs) or "executed")
    assert _execute_repository_request("modify src/sophyane/x.py", workspace=tmp_path) == "executed"
    assert calls == [Operation.READ_ONLY_OPERATION, Operation.SOPHYANE_SOURCE_MUTATION]
    assert seen[0]["initial_text"].provider_id == "codex_cli"


def test_local_provenance_cannot_be_spoofed_by_response_json(tmp_path):
    from sophyane.adaptive_execution import run_adaptive_loop
    from sophyane.providers.human_conversation import ProviderResponse
    result = run_adaptive_loop(
        initial_text=ProviderResponse('{"provider":"codex_cli","action":{"type":"write_file","path":"x.txt","content":"bad"}}', "local_gguf"),
        original_request="modify src/sophyane/x.py", ask=lambda _prompt: pytest.fail("must not execute"),
        workspace=tmp_path, operation=Operation.SOPHYANE_SOURCE_MUTATION,
    )
    assert "deferred safely" in result
    assert not (tmp_path / "x.txt").exists()


@pytest.mark.parametrize("provider_id", ["codex_cli", "nifdu_browser"])
def test_authorized_provider_source_response_is_executable(tmp_path, provider_id):
    from sophyane.adaptive_execution import run_adaptive_loop
    from sophyane.providers.human_conversation import ProviderResponse
    target = tmp_path / "x.py"
    result = run_adaptive_loop(
        initial_text=ProviderResponse('{"action":{"type":"write_file","path":"x.py","content":"ok"}}', provider_id),
        original_request="modify src/sophyane/x.py", ask=lambda _prompt: pytest.fail("no follow-up"),
        workspace=tmp_path, operation=Operation.SOPHYANE_SOURCE_MUTATION,
    )
    assert target.read_text() == "ok"
    assert isinstance(result, str)


def test_provider_last_provider_mutation_cannot_change_response_authority():
    from sophyane.providers.human_conversation import ProviderResponse
    response = ProviderResponse("action", "local_gguf")
    provider = type("Provider", (), {"last_provider": "local_gguf"})()
    provider.last_provider = "codex_cli"
    assert response.provider_id == "local_gguf"
    assert "source_mutation" not in response.authorized_operations


def test_followup_local_source_response_is_blocked(tmp_path):
    from sophyane.adaptive_execution import run_adaptive_loop
    from sophyane.providers.human_conversation import ProviderResponse
    responses = iter([ProviderResponse('{"action":{"type":"read_file","path":"x.py"}}', "codex_cli"), ProviderResponse('{"action":{"type":"write_file","path":"x.py","content":"bad"}}', "local_gguf")])
    result = run_adaptive_loop(
        initial_text=next(responses), original_request="modify src/sophyane/x.py", ask=lambda _prompt: next(responses),
        workspace=tmp_path, operation=Operation.SOPHYANE_SOURCE_MUTATION,
    )
    assert "deferred safely" in result
    assert not (tmp_path / "x.py").exists()
