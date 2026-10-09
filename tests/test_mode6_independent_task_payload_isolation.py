import os


def test_independent_mode6_tasks_isolate_provider_payloads(
    monkeypatch,
    tmp_path,
):
    from sophyane import human_conversation_cli as cli

    task_a = (
        "Audit the repository for unsafe shell admission. "
        "Live requirement: inspect README.md."
    )
    task_b = (
        "Create an unrelated calculator.py with addition tests."
    )

    calls = []
    handoffs = []

    class FakeProvider:
        def generate(self, prompt, system_prompt):
            calls.append(
                {
                    "prompt": str(prompt),
                    "fresh": os.environ.get(
                        "SOPHYANE_CODEX_FRESH"
                    ),
                }
            )
            return (
                '{"action":{"type":"run_command",'
                '"command":"printf verification"}}'
            )

    def fake_adaptive_loop(
        *,
        initial_text,
        original_request,
        ask,
        workspace,
        max_steps,
        operation,
    ):
        handoffs.append(
            {
                "request": original_request,
                "workspace": workspace,
            }
        )

        ask("same-task verification follow-up")
        return str(initial_text)

    monkeypatch.setattr(
        "sophyane.main.create_provider",
        lambda _config: FakeProvider(),
    )
    monkeypatch.setattr(
        "sophyane.config.load_config",
        lambda: {},
    )
    monkeypatch.setattr(
        "sophyane.adaptive_execution.run_adaptive_loop",
        fake_adaptive_loop,
    )
    monkeypatch.setenv(
        "SOPHYANE_SESSION_MODE",
        "human_conversation",
    )
    monkeypatch.setenv(
        "SOPHYANE_CODEX_FRESH",
        "caller-value",
    )

    workspace = tmp_path / "repo"
    workspace.mkdir()

    cli._execute_repository_request(
        task_a,
        workspace=workspace,
    )

    cli._execute_repository_request(
        task_b,
        workspace=workspace,
    )

    assert len(calls) == 4
    assert len(handoffs) == 2

    a_initial, a_followup, b_initial, b_followup = calls

    assert a_initial["fresh"] == "1"
    assert b_initial["fresh"] == "1"

    assert a_followup["fresh"] == "caller-value"
    assert b_followup["fresh"] == "caller-value"

    assert "ORIGINAL TASK:" in a_initial["prompt"]
    assert task_a in a_initial["prompt"]

    assert "ORIGINAL TASK:" in b_initial["prompt"]
    assert task_b in b_initial["prompt"]

    assert task_a not in b_initial["prompt"]
    assert "inspect README.md" not in b_initial["prompt"]

    assert task_b not in a_initial["prompt"]

    assert handoffs[0]["request"] == task_a
    assert handoffs[1]["request"] == task_b

    assert handoffs[0]["workspace"] == workspace.resolve()
    assert handoffs[1]["workspace"] == workspace.resolve()

    assert os.environ["SOPHYANE_CODEX_FRESH"] == "caller-value"
