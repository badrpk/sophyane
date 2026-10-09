from types import SimpleNamespace
import sophyane.human_conversation_cli as cli


def test_existing_file_edit_is_execution_request():
    assert cli._repository_execution_request(
        "Modify the existing file src/example.py."
    ) is True


def test_explicit_targeted_patch_is_execution_request():
    assert cli._repository_execution_request(
        "Patch targeted_patch_e2e_probe.txt using targeted_patch."
    ) is True


def test_repository_test_command_is_execution_request():
    assert cli._repository_execution_request(
        "Run the tests for this repository."
    ) is True


def test_inspect_and_fix_is_execution_request():
    assert cli._repository_execution_request(
        "Inspect src/sophyane/foo.py and fix the failing function."
    ) is True


def test_ordinary_chat_is_not_execution_request():
    assert cli._repository_execution_request(
        "How are you?"
    ) is False


def test_explain_targeted_patch_is_not_execution_request():
    assert cli._repository_execution_request(
        "Explain targeted_patch."
    ) is False


def test_code_explanation_is_not_execution_request():
    assert cli._repository_execution_request(
        "What does this Python function do?"
    ) is False


def test_hypothetical_edit_advice_is_not_execution_request():
    assert cli._repository_execution_request(
        "Tell me how I could edit this file."
    ) is False


def test_architecture_opinion_is_not_execution_request():
    assert cli._repository_execution_request(
        "Do you think this repository architecture is good?"
    ) is False


def test_file_word_alone_does_not_trigger_execution():
    assert cli._repository_execution_request(
        "What is a Python file?"
    ) is False


def test_repository_word_alone_does_not_trigger_execution():
    assert cli._repository_execution_request(
        "Explain the repository."
    ) is False



def test_execute_repository_request_delegates_to_adaptive_loop(
    monkeypatch,
    tmp_path,
):
    captured = {}

    class FakeProvider:
        def generate(self, prompt, system_prompt=None):
            captured.setdefault("generate_calls", []).append(
                (prompt, system_prompt)
            )
            return '{"action":{"type":"respond","text":"INITIAL"}}'

    provider = FakeProvider()

    monkeypatch.setattr(
        "sophyane.config.load_config",
        lambda: {"provider": "ignored"},
    )
    monkeypatch.setattr(
        "sophyane.main.create_provider",
        lambda config: provider,
    )

    def fake_run_adaptive_loop(**kwargs):
        captured["adaptive_kwargs"] = kwargs
        return "ADAPTIVE_RESULT_SENTINEL"

    monkeypatch.setattr(
        "sophyane.adaptive_execution.run_adaptive_loop",
        fake_run_adaptive_loop,
    )

    request = "Modify the existing file src/example.py."

    result = cli._execute_repository_request(
        request,
        workspace=tmp_path,
    )

    assert result == "ADAPTIVE_RESULT_SENTINEL"

    kwargs = captured["adaptive_kwargs"]

    assert kwargs["original_request"] == request
    assert kwargs["workspace"] == tmp_path.resolve()
    assert callable(kwargs["ask"])
    assert kwargs["initial_text"] == (
        '{"action":{"type":"respond","text":"INITIAL"}}'
    )

    assert len(captured["generate_calls"]) == 1
    initial_prompt, system_prompt = captured["generate_calls"][0]

    assert request in initial_prompt
    assert system_prompt


def test_execute_repository_request_reuses_same_raw_provider_for_repairs(
    monkeypatch,
    tmp_path,
):
    calls = []

    class FakeProvider:
        def generate(self, prompt, system_prompt=None):
            calls.append((prompt, system_prompt))
            return f"RAW_RESPONSE_{len(calls)}"

    provider = FakeProvider()

    monkeypatch.setattr(
        "sophyane.config.load_config",
        lambda: {"provider": "ignored"},
    )
    monkeypatch.setattr(
        "sophyane.main.create_provider",
        lambda config: provider,
    )

    def fake_run_adaptive_loop(**kwargs):
        assert kwargs["initial_text"] == "RAW_RESPONSE_1"

        repaired = kwargs["ask"](
            "REPAIR_PROMPT_SENTINEL"
        )

        assert repaired == "RAW_RESPONSE_2"
        return "EXECUTION_COMPLETE"

    monkeypatch.setattr(
        "sophyane.adaptive_execution.run_adaptive_loop",
        fake_run_adaptive_loop,
    )

    result = cli._execute_repository_request(
        "Patch src/example.py.",
        workspace=tmp_path,
    )

    assert result == "EXECUTION_COMPLETE"
    assert len(calls) == 2
    assert calls[1][0] == "REPAIR_PROMPT_SENTINEL"


def test_execute_repository_request_does_not_call_executor_directly(
    monkeypatch,
    tmp_path,
):
    def forbidden_execute_action(*args, **kwargs):
        raise AssertionError(
            "human conversation bypassed adaptive execution"
        )

    class FakeProvider:
        def generate(self, prompt, system_prompt=None):
            return '{"action":{"type":"respond","text":"SAFE"}}'

    monkeypatch.setattr(
        "sophyane.execution_runtime.execute_action",
        forbidden_execute_action,
    )
    monkeypatch.setattr(
        "sophyane.config.load_config",
        lambda: {"provider": "ignored"},
    )
    monkeypatch.setattr(
        "sophyane.main.create_provider",
        lambda config: FakeProvider(),
    )
    monkeypatch.setattr(
        "sophyane.adaptive_execution.run_adaptive_loop",
        lambda **kwargs: "SAFE_ADAPTIVE_RESULT",
    )

    result = cli._execute_repository_request(
        "Modify src/example.py.",
        workspace=tmp_path,
    )

    assert result == "SAFE_ADAPTIVE_RESULT"


def test_once_execution_request_uses_execution_bridge(
    monkeypatch,
    capsys,
):
    calls = []

    monkeypatch.setattr(
        "sys.argv",
        [
            "sophyane-human-chat",
            "--once",
            "Modify src/example.py.",
        ],
    )

    monkeypatch.setattr(
        cli,
        "_execute_repository_request",
        lambda text: calls.append(
            ("execute", text)
        ) or cli._CompletedRepositoryExecution(
            "EXECUTION_EVIDENCE"
        ),
    )

    def forbidden_conversation_turn(*args, **kwargs):
        raise AssertionError(
            "execution request fell through to conversation_turn"
        )

    monkeypatch.setattr(
        cli,
        "conversation_turn",
        forbidden_conversation_turn,
    )

    assert cli.main() == 0

    output = capsys.readouterr().out

    assert calls == [
        ("execute", "Modify src/example.py.")
    ]
    assert "EXECUTION_EVIDENCE" in output


def test_once_normal_chat_stays_conversational(
    monkeypatch,
    capsys,
):
    class FakeTurn:
        reply = "CHAT_REPLY"

    monkeypatch.setattr(
        "sys.argv",
        [
            "sophyane-human-chat",
            "--once",
            "How are you?",
        ],
    )

    monkeypatch.setattr(
        cli,
        "_execute_repository_request",
        lambda *args, **kwargs: (
            (_ for _ in ()).throw(
                AssertionError(
                    "ordinary chat entered execution"
                )
            )
        ),
    )

    monkeypatch.setattr(
        cli,
        "conversation_turn",
        lambda text, **kwargs: FakeTurn(),
    )

    assert cli.main() == 0

    output = capsys.readouterr().out

    assert "CHAT_REPLY" in output


def test_interactive_execution_result_is_printed_directly(
    monkeypatch,
    capsys,
):
    from types import SimpleNamespace

    inputs = iter(
        [
            "Patch src/example.py.",
            "/exit",
        ]
    )

    monkeypatch.setattr(
        "builtins.input",
        lambda prompt="": next(inputs),
    )

    monkeypatch.setattr(
        "sys.argv",
        ["sophyane-human-chat"],
    )

    events = []

    monkeypatch.setattr(
        cli,
        "_execute_repository_request",
        lambda text, *, workspace=None: events.append(("execute", text))
        or "DIRECT_EXECUTION_RESULT",
    )

    def fake_conversation_turn(text, **kwargs):
        events.append(("conversation", text))
        return SimpleNamespace(
            reply="ROUTING_REPLY",
            semantic_disposition="actionable_mission",
        )

    monkeypatch.setattr(
        cli,
        "conversation_turn",
        fake_conversation_turn,
    )

    assert cli.main() == 0

    output = capsys.readouterr().out

    assert events == [
        ("conversation", "Patch src/example.py."),
        ("execute", "Patch src/example.py."),
    ]
    assert "DIRECT_EXECUTION_RESULT" in output


def test_interactive_normal_chat_stays_conversational(
    monkeypatch,
    capsys,
):
    inputs = iter(
        [
            "How are you?",
            "/exit",
        ]
    )

    class FakeTurn:
        reply = "INTERACTIVE_CHAT_REPLY"

    monkeypatch.setattr(
        "builtins.input",
        lambda prompt="": next(inputs),
    )

    monkeypatch.setattr(
        "sys.argv",
        ["sophyane-human-chat"],
    )

    monkeypatch.setattr(
        cli,
        "_execute_repository_request",
        lambda *args, **kwargs: (
            (_ for _ in ()).throw(
                AssertionError(
                    "ordinary interactive chat entered execution"
                )
            )
        ),
    )

    monkeypatch.setattr(
        cli,
        "conversation_turn",
        lambda text, **kwargs: FakeTurn(),
    )

    assert cli.main() == 0

    output = capsys.readouterr().out

    assert "INTERACTIVE_CHAT_REPLY" in output


def test_voice_execution_transcript_routes_to_execution(
    monkeypatch,
    capsys,
):
    inputs = iter(
        [
            "/voice",
            "/exit",
        ]
    )

    monkeypatch.setattr(
        "builtins.input",
        lambda prompt="": next(inputs),
    )
    monkeypatch.setattr(
        "sys.argv",
        ["sophyane-human-chat"],
    )
    monkeypatch.setattr(
        cli,
        "_voice_input_text",
        lambda: "Patch src/example.py.",
    )

    from types import SimpleNamespace

    events = []

    monkeypatch.setattr(
        cli,
        "_execute_repository_request",
        lambda text, *, workspace=None: events.append(
            ("execute", text)
        ) or "VOICE_EXECUTION_RESULT",
    )

    def fake_conversation_turn(text, **kwargs):
        events.append(("conversation", text))
        return SimpleNamespace(
            reply="VOICE_ROUTING_REPLY",
            semantic_disposition="actionable_mission",
        )

    monkeypatch.setattr(
        cli,
        "conversation_turn",
        fake_conversation_turn,
    )

    assert cli.main() == 0

    output = capsys.readouterr().out

    assert events == [
        ("conversation", "Patch src/example.py."),
        ("execute", "Patch src/example.py."),
    ]
    assert "VOICE_EXECUTION_RESULT" in output


def test_voice_normal_transcript_stays_conversational(
    monkeypatch,
    capsys,
):
    inputs = iter(
        [
            "/voice",
            "/exit",
        ]
    )

    class FakeTurn:
        reply = "VOICE_CHAT_REPLY"

    monkeypatch.setattr(
        "builtins.input",
        lambda prompt="": next(inputs),
    )
    monkeypatch.setattr(
        "sys.argv",
        ["sophyane-human-chat"],
    )
    monkeypatch.setattr(
        cli,
        "_voice_input_text",
        lambda: "How are you?",
    )

    monkeypatch.setattr(
        cli,
        "_execute_repository_request",
        lambda *args, **kwargs: (
            (_ for _ in ()).throw(
                AssertionError(
                    "normal voice transcript entered execution"
                )
            )
        ),
    )

    monkeypatch.setattr(
        cli,
        "conversation_turn",
        lambda text, **kwargs: FakeTurn(),
    )

    assert cli.main() == 0

    output = capsys.readouterr().out

    assert "VOICE_CHAT_REPLY" in output


def test_camera_originated_repo_like_text_remains_conversational(
    monkeypatch,
    capsys,
):
    inputs = iter(
        [
            "/see Patch src/example.py.",
            "/exit",
        ]
    )

    class FakeTurn:
        reply = "CAMERA_CHAT_REPLY"

    monkeypatch.setattr(
        "builtins.input",
        lambda prompt="": next(inputs),
    )
    monkeypatch.setattr(
        "sys.argv",
        ["sophyane-human-chat"],
    )

    monkeypatch.setattr(
        cli,
        "_camera_visual_input",
        lambda: (
            "/tmp/fake-camera.jpg",
            {"camera": "verified"},
        ),
    )

    monkeypatch.setattr(
        cli,
        "_execute_repository_request",
        lambda *args, **kwargs: (
            (_ for _ in ()).throw(
                AssertionError(
                    "camera-originated turn entered execution"
                )
            )
        ),
    )

    captured = {}

    def fake_conversation_turn(
        text,
        *,
        visual_artifact_path=None,
        metadata=None,
        **kwargs,
    ):
        captured["text"] = text
        captured["visual_artifact_path"] = visual_artifact_path
        captured["metadata"] = metadata
        return FakeTurn()

    monkeypatch.setattr(
        cli,
        "conversation_turn",
        fake_conversation_turn,
    )

    assert cli.main() == 0

    output = capsys.readouterr().out

    assert captured["text"] == "Patch src/example.py."
    assert captured["visual_artifact_path"] == "/tmp/fake-camera.jpg"
    assert captured["metadata"] == {"camera": "verified"}
    assert "CAMERA_CHAT_REPLY" in output


# SOPHYANE_HUMAN_CONVERSATION_ACTIVE_EXECUTION_FOLLOWUP_V1


def test_gallery_photo_paths_are_discovered_from_existing_termux_storage(
    monkeypatch,
    tmp_path,
):
    dcim = tmp_path / "dcim"
    pictures = tmp_path / "pictures"

    dcim.mkdir()
    pictures.mkdir()

    expected = []

    for index in range(12):
        path = dcim / f"camera_{index:02d}.jpg"
        path.write_bytes(b"jpg")
        expected.append(path.resolve())

    for index in range(12):
        path = pictures / f"picture_{index:02d}.png"
        path.write_bytes(b"png")
        expected.append(path.resolve())

    ignored = pictures / "ignore.txt"
    ignored.write_text("not an image")

    monkeypatch.setattr(
        cli,
        "_gallery_roots",
        lambda: (dcim, pictures),
        raising=False,
    )

    discovered = cli._gallery_photo_paths()

    assert len(discovered) == 24
    assert set(discovered) == set(expected)
    assert ignored.resolve() not in discovered


def test_gallery_enrichment_selects_exactly_twenty_real_paths(
    monkeypatch,
    tmp_path,
):
    roots = []

    for index in range(25):
        path = tmp_path / f"photo_{index:02d}.jpg"
        path.write_bytes(b"photo")
        roots.append(path.resolve())

    monkeypatch.setattr(
        cli,
        "_gallery_photo_paths",
        lambda: list(roots),
        raising=False,
    )

    request = cli._enrich_gallery_execution_request(
        "pick any random photos from my gallery",
        active_request="make file yaad.py\n"
        "it should be collage of 20 photos",
    )

    assert "make file yaad.py" in request
    assert "collage of 20 photos" in request

    selected = [
        str(path)
        for path in roots
        if str(path) in request
    ]

    assert len(selected) == 20
    assert len(set(selected)) == 20

    assert "Gallery filesystem access is already available." in request
    assert "Do not request photo/media permission." in request


def test_gallery_enrichment_is_deterministic_for_same_active_task(
    monkeypatch,
    tmp_path,
):
    photos = []

    for index in range(30):
        path = tmp_path / f"photo_{index:02d}.jpg"
        path.write_bytes(b"photo")
        photos.append(path.resolve())

    monkeypatch.setattr(
        cli,
        "_gallery_photo_paths",
        lambda: list(photos),
        raising=False,
    )

    kwargs = dict(
        text="pick any random photos from my gallery",
        active_request="make file yaad.py\n"
        "it should be collage of 20 photos",
    )

    first = cli._enrich_gallery_execution_request(**kwargs)
    second = cli._enrich_gallery_execution_request(**kwargs)

    assert first == second


def test_gallery_enrichment_reports_unavailable_access_truthfully(
    monkeypatch,
):
    monkeypatch.setattr(
        cli,
        "_gallery_photo_paths",
        lambda: [],
        raising=False,
    )

    request = cli._enrich_gallery_execution_request(
        "pick any random photos from my gallery",
        active_request="make file yaad.py",
    )

    assert "make file yaad.py" in request
    assert "No readable gallery images were found" in request
    assert "permission" not in request.casefold()


def test_interactive_followup_continues_active_execution_task(
    monkeypatch,
    capsys,
):
    inputs = iter(
        [
            "make file yaad.py",
            "it should be collage of 20 photos",
            "pick any random photos from my gallery",
            "/exit",
        ]
    )

    monkeypatch.setattr(
        "builtins.input",
        lambda prompt="": next(inputs),
    )

    monkeypatch.setattr(
        "sys.argv",
        ["sophyane-human-chat"],
    )

    from types import SimpleNamespace

    execution_calls = []
    intelligence_calls = []

    def fake_execute(text, *, workspace=None):
        execution_calls.append(text)

        if len(execution_calls) == 1:
            return "What content should I put inside yaad.py?"

        if len(execution_calls) == 2:
            return "Need photo source."

        return cli._CompletedRepositoryExecution(
            "YAAD_COMPLETE"
        )

    monkeypatch.setattr(
        cli,
        "_execute_repository_request",
        fake_execute,
    )

    def fake_conversation_turn(text, **kwargs):
        intelligence_calls.append(text)

        if len(intelligence_calls) > 1:
            raise AssertionError(
                "active execution follow-up fell through to conversation_turn"
            )

        return SimpleNamespace(
            reply="ROUTING_REPLY",
            semantic_disposition="actionable_mission",
        )

    monkeypatch.setattr(
        cli,
        "conversation_turn",
        fake_conversation_turn,
    )

    monkeypatch.setattr(
        cli,
        "_enrich_gallery_execution_request",
        lambda text, *, active_request: (
            active_request
            + "\n"
            + text
            + "\nGALLERY_PATHS_INJECTED"
        ),
        raising=False,
    )

    assert cli.main() == 0

    assert intelligence_calls == [
        "make file yaad.py"
    ]

    assert len(execution_calls) == 3

    assert execution_calls[0] == "make file yaad.py"

    assert (
        execution_calls[1]
        == "make file yaad.py\n"
           "it should be collage of 20 photos"
    )

    assert "make file yaad.py" in execution_calls[2]
    assert "it should be collage of 20 photos" in execution_calls[2]
    assert "pick any random photos from my gallery" in execution_calls[2]
    assert "GALLERY_PATHS_INJECTED" in execution_calls[2]

    output = capsys.readouterr().out

    assert "YAAD_COMPLETE" in output


def test_ordinary_chat_after_no_active_execution_stays_conversational(
    monkeypatch,
    capsys,
):
    inputs = iter(
        [
            "How are you?",
            "/exit",
        ]
    )

    monkeypatch.setattr(
        "builtins.input",
        lambda prompt="": next(inputs),
    )

    monkeypatch.setattr(
        "sys.argv",
        ["sophyane-human-chat"],
    )

    class FakeTurn:
        reply = "CHAT_OK"

    monkeypatch.setattr(
        cli,
        "conversation_turn",
        lambda text, **kwargs: FakeTurn(),
    )

    monkeypatch.setattr(
        cli,
        "_execute_repository_request",
        lambda *args, **kwargs: (
            (_ for _ in ()).throw(
                AssertionError(
                    "ordinary chat incorrectly entered execution"
                )
            )
        ),
    )

    assert cli.main() == 0

    output = capsys.readouterr().out
    assert "CHAT_OK" in output


def test_domain_backed_saas_build_routes_to_repository_execution():
    from sophyane.human_conversation_cli import (
        _repository_execution_request,
    )

    assert _repository_execution_request(
        "make saas on www.shmry.com"
    ) is True


def test_domain_mention_without_execution_remains_conversational():
    from sophyane.human_conversation_cli import (
        _repository_execution_request,
    )

    assert _repository_execution_request(
        "what is saas on www.shmry.com"
    ) is False


# SOPHYANE_REPOSITORY_OPERATION_SCOPE_RED_V1
def test_simple_file_creation_maps_to_ordinary_workspace_mutation():
    import sophyane.human_conversation_cli as cli
    from sophyane.rsi.authority import Operation

    mapper = getattr(
        cli,
        "_repository_operation_for_request",
        None,
    )

    assert callable(mapper)

    ordinary = Operation.__members__.get(
        "ORDINARY_WORKSPACE_MUTATION"
    )

    assert ordinary is not None
    assert mapper("make file hey.py") is ordinary


def test_explicit_sophyane_source_edit_maps_to_source_mutation():
    import sophyane.human_conversation_cli as cli
    from sophyane.rsi.authority import Operation

    mapper = getattr(
        cli,
        "_repository_operation_for_request",
        None,
    )

    assert callable(mapper)

    assert (
        mapper(
            "patch src/sophyane/human_conversation_cli.py"
        )
        is Operation.SOPHYANE_SOURCE_MUTATION
    )


def test_explicit_rsi_edit_maps_to_source_mutation():
    import sophyane.human_conversation_cli as cli
    from sophyane.rsi.authority import Operation

    mapper = getattr(
        cli,
        "_repository_operation_for_request",
        None,
    )

    assert callable(mapper)

    assert (
        mapper(
            "modify Sophyane RSI authority"
        )
        is Operation.SOPHYANE_SOURCE_MUTATION
    )


# SOPHYANE_NATURAL_LANGUAGE_MUTATION_RSI_RED_V1

def test_natural_language_leave_note_maps_to_ordinary_workspace_mutation():
    from sophyane.human_conversation_cli import _repository_operation_for_request
    from sophyane.rsi.authority import Operation

    request = (
        "Inside mode6_ladder_workspace, leave me a note named "
        "natural_request.txt saying exactly Natural language understood "
        "followed by one newline."
    )

    assert (
        _repository_operation_for_request(request)
        is Operation.ORDINARY_WORKSPACE_MUTATION
    )


def test_request_classification_has_no_result_42_challenge_leakage():
    from pathlib import Path

    source = Path(
        "src/sophyane/request_classification.py"
    ).read_text(encoding="utf-8")

    assert 'print("Result: 42")' not in source


def test_rsi_authority_has_no_result_42_challenge_leakage():
    from pathlib import Path

    source = Path(
        "src/sophyane/rsi/authority.py"
    ).read_text(encoding="utf-8")

    assert 'print("Result: 42")' not in source


# SOPHYANE_NATURAL_NOTE_ROUTING_RED_V1

def test_natural_language_leave_note_routes_to_repository_execution():
    from sophyane.human_conversation_cli import _repository_execution_request

    request = (
        "Inside mode6_ladder_workspace, leave me a note named "
        "natural_request.txt saying exactly Natural language understood "
        "followed by one newline."
    )

    assert _repository_execution_request(request) is True


def test_conversational_leave_note_question_does_not_route_to_execution():
    from sophyane.human_conversation_cli import _repository_execution_request

    assert (
        _repository_execution_request(
            "Explain how I could leave a note named natural_request.txt."
        )
        is False
    )


def test_leave_repository_unchanged_does_not_route_to_mutation():
    from sophyane.human_conversation_cli import _repository_execution_request

    assert (
        _repository_execution_request(
            "Leave this repository unchanged."
        )
        is False
    )


def test_completed_exact_write_releases_execution_before_next_normal_turn(
    tmp_path,
    monkeypatch,
):
    """A completed deterministic write must return Mode 6 to idle."""

    import builtins
    import sys

    from sophyane import human_conversation_cli as cli

    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv(
        "SOPHYANE_SESSION_MODE",
        "human_conversation",
    )

    # cli.main() owns its CLI arguments. Do not expose pytest's argv to it.
    monkeypatch.setattr(
        sys,
        "argv",
        ["sophyane-human-chat"],
    )

    request = (
        "make file lifecycle_exact.py containing exactly: "
        "EXACT_LIFECYCLE"
    )

    inputs = iter(
        [
            request,
            "hello",
            "/exit",
        ]
    )

    monkeypatch.setattr(
        builtins,
        "input",
        lambda _prompt="": next(inputs),
    )

    continuation_calls = []

    original_continue = cli._continue_execution_request

    def observe_continue(
        text,
        *,
        active_request,
    ):
        continuation_calls.append(
            (text, active_request)
        )
        return original_continue(
            text,
            active_request=active_request,
        )

    monkeypatch.setattr(
        cli,
        "_continue_execution_request",
        observe_continue,
    )

    # If execution correctly returns to idle, "hello" must take the
    # conversational path. Keep that path provider-free and observable.
    from types import SimpleNamespace

    conversation_calls = []

    def fake_conversation_turn(
        text,
        **kwargs,
    ):
        conversation_calls.append(text)

        if text == request:
            return SimpleNamespace(
                reply="ROUTING_REPLY",
                semantic_disposition="actionable_mission",
            )

        if text == "hello":
            return SimpleNamespace(
                reply="CHAT_OK",
                semantic_disposition="conversation",
            )

        raise AssertionError(
            f"unexpected conversational turn: {text!r}"
        )

    monkeypatch.setattr(
        cli,
        "conversation_turn",
        fake_conversation_turn,
    )

    monkeypatch.setattr(
        cli,
        "_handoff_turn_improvement",
        lambda _result: None,
    )

    rc = cli.main()

    target = tmp_path / "lifecycle_exact.py"

    assert rc == 0
    assert target.read_bytes() == b"EXACT_LIFECYCLE"

    # The completed exact write must not retain repository-execution
    # authority over the next ordinary conversational turn.
    assert continuation_calls == []
    assert conversation_calls == [
        request,
        "hello",
    ]


def test_mode6_interactive_uses_atomic_terminal_submission(
    monkeypatch,
):
    """Mode 6 must preserve terminal submission boundaries before routing."""
    request = (
        "make file probe.py containing exactly: "
        'print("MODE6 EXACT LIVE V2")'
    )

    submissions = iter([
        request,
        "/exit",
    ])

    atomic_calls = []

    def fake_atomic(prompt):
        atomic_calls.append(prompt)
        return next(submissions)

    def direct_input_must_not_be_used(_prompt):
        raise AssertionError(
            "Mode 6 bypassed the atomic terminal submission boundary"
        )

    monkeypatch.setattr(
        cli,
        "_read_atomic_submission",
        fake_atomic,
    )
    monkeypatch.setattr(
        "builtins.input",
        direct_input_must_not_be_used,
    )
    import sys

    monkeypatch.setattr(
        sys,
        "argv",
        ["sophyane-human-chat"],
    )

    execution_calls = []

    def fake_execute(text, *, workspace=None):
        execution_calls.append(text)
        return cli._CompletedRepositoryExecution("VERIFIED")

    monkeypatch.setattr(
        cli,
        "_execute_repository_request",
        fake_execute,
    )

    monkeypatch.setattr(
        cli,
        "conversation_turn",
        lambda text, **kwargs: SimpleNamespace(
            reply="route",
            semantic_disposition="actionable_mission",
        ),
    )

    rc = cli.main()

    assert rc == 0
    assert atomic_calls == [
        "\n> ",
        "\n> ",
    ]
    assert execution_calls == [request]


def test_mode6_real_atomic_reader_keeps_buffered_exit_out_of_execution(
    monkeypatch,
):
    import builtins
    import sys
    import sophyane.tui_v2 as tui

    request = (
        "make file probe.py containing exactly: "
        'print("MODE6 EXACT LIVE V2")'
    )

    class Buffered:
        def __init__(self):
            self.lines = iter(["/exit\n"])

        def readline(self):
            return next(self.lines, "")

    buffered = Buffered()

    monkeypatch.setattr(
        builtins,
        "input",
        lambda _prompt: request,
    )
    monkeypatch.setattr(
        tui.sys,
        "stdin",
        buffered,
    )
    monkeypatch.setattr(
        tui.select,
        "select",
        lambda *args: ([buffered], [], []),
    )

    tui._PENDING_TERMINAL_SUBMISSIONS.clear()

    monkeypatch.setattr(
        sys,
        "argv",
        ["sophyane-human-chat"],
    )

    execution_calls = []

    def fake_execute(text, *, workspace=None):
        execution_calls.append(text)
        return cli._CompletedRepositoryExecution("VERIFIED")

    monkeypatch.setattr(
        cli,
        "_execute_repository_request",
        fake_execute,
    )

    monkeypatch.setattr(
        cli,
        "conversation_turn",
        lambda text, **kwargs: SimpleNamespace(
            reply="route",
            semantic_disposition="actionable_mission",
        ),
    )

    rc = cli.main()

    assert rc == 0
    assert execution_calls == [request]
    assert "/exit" not in execution_calls[0]
    assert tui._PENDING_TERMINAL_SUBMISSIONS == []


def test_direct_module_main_guard_follows_repository_operation_definition():
    from pathlib import Path

    source = Path(cli.__file__).read_text(encoding="utf-8")

    operation_definition = (
        "def _repository_operation_for_request(request: str):"
    )
    main_guard = 'if __name__ == "__main__":'

    assert source.count(operation_definition) == 1
    assert source.count(main_guard) == 1
    assert source.index(operation_definition) < source.index(main_guard)

# SOPHYANE_MODE6_CLASSIFIED_READ_ONLY_ADAPTIVE_HANDOFF_RED_V1
def test_classified_read_only_operation_reaches_adaptive_loop(
    monkeypatch,
    tmp_path,
):
    from sophyane.rsi.authority import Operation

    captured = {}

    class FakeProvider:
        def generate(
            self,
            prompt,
            system_prompt="",
            **kwargs,
        ):
            return '{"action":"read_file","path":"pyproject.toml"}'

    monkeypatch.setattr(
        cli,
        "_repository_operation_for_request",
        lambda _request: Operation.READ_ONLY_OPERATION,
    )

    import sophyane.main as main
    import sophyane.adaptive_execution as adaptive

    monkeypatch.setattr(
        main,
        "create_provider",
        lambda _config: FakeProvider(),
    )

    def fake_run_adaptive_loop(**kwargs):
        captured.update(kwargs)
        return "DONE"

    monkeypatch.setattr(
        adaptive,
        "run_adaptive_loop",
        fake_run_adaptive_loop,
    )

    result = cli._execute_repository_request(
        "Inspect pyproject.toml.",
        workspace=tmp_path,
    )

    assert result == "DONE"
    assert captured["operation"] is Operation.READ_ONLY_OPERATION


def test_repository_execution_surfaces_successful_provider_per_call(
    monkeypatch,
    tmp_path,
):
    """Live execution evidence must identify each successful provider call."""

    from sophyane.providers.human_conversation import (
        HumanConversationProvider,
    )

    provider = HumanConversationProvider()

    responses = iter(
        [
            (
                "codex_cli",
                '{"action":{"type":"respond","text":"INITIAL"}}',
            ),
            (
                "nifdu_browser",
                '{"action":{"type":"respond","text":"REPAIR"}}',
            ),
        ]
    )

    def fake_generate(prompt, system_prompt=None, **kwargs):
        name, response = next(responses)
        provider.last_provider = name
        return response

    monkeypatch.setattr(
        provider,
        "generate",
        fake_generate,
    )

    monkeypatch.setattr(
        "sophyane.config.load_config",
        lambda: {"provider": "ignored"},
    )
    monkeypatch.setattr(
        "sophyane.main.create_provider",
        lambda _config: provider,
    )

    captured = {}

    def fake_run_adaptive_loop(**kwargs):
        captured["initial_text"] = kwargs["initial_text"]
        captured["repair_text"] = kwargs["ask"](
            "REPAIR_PROVIDER_ATTRIBUTION"
        )
        return "EXECUTION_COMPLETE"

    monkeypatch.setattr(
        "sophyane.adaptive_execution.run_adaptive_loop",
        fake_run_adaptive_loop,
    )

    result = cli._execute_repository_request(
        "Patch src/example.py.",
        workspace=tmp_path,
    )

    assert result.startswith("EXECUTION_COMPLETE")
    assert (
        "Provider evidence: codex_cli -> nifdu_browser"
        in result
    )

    evidence = getattr(
        provider,
        "execution_provider_evidence",
        (),
    )

    assert tuple(evidence) == (
        "codex_cli",
        "nifdu_browser",
    )


def test_repository_execution_reports_provider_evidence_in_result(
    monkeypatch,
    tmp_path,
):
    """Completed Mode-6 execution should expose successful provider routing."""

    from sophyane.providers.human_conversation import (
        HumanConversationProvider,
    )

    provider = HumanConversationProvider()

    responses = iter(
        [
            (
                "codex_cli",
                '{"action":{"type":"respond","text":"INITIAL"}}',
            ),
            (
                "nifdu_browser",
                '{"action":{"type":"respond","text":"REPAIR"}}',
            ),
        ]
    )

    def fake_generate(prompt, system_prompt=None, **kwargs):
        name, response = next(responses)
        provider.last_provider = name
        return response

    monkeypatch.setattr(
        provider,
        "generate",
        fake_generate,
    )

    monkeypatch.setattr(
        "sophyane.config.load_config",
        lambda: {"provider": "ignored"},
    )
    monkeypatch.setattr(
        "sophyane.main.create_provider",
        lambda _config: provider,
    )

    def fake_run_adaptive_loop(**kwargs):
        kwargs["ask"]("REPAIR_PROVIDER_EVIDENCE")
        return "EXECUTION_COMPLETE"

    monkeypatch.setattr(
        "sophyane.adaptive_execution.run_adaptive_loop",
        fake_run_adaptive_loop,
    )

    result = cli._execute_repository_request(
        "Patch src/example.py.",
        workspace=tmp_path,
    )

    assert "EXECUTION_COMPLETE" in result
    assert (
        "Provider evidence: codex_cli -> nifdu_browser"
        in result
    )


def test_repository_execution_reports_sanitized_provider_route_per_call(
    monkeypatch,
    tmp_path,
):
    """Visible route evidence preserves each call and never leaks diagnostics."""

    from sophyane.providers.human_conversation import (
        HumanConversationProvider,
    )

    provider = HumanConversationProvider()

    calls = iter(
        [
            (
                "nifdu_browser",
                (
                    "codex_cli[unavailable]",
                    "nifdu_browser[success]",
                ),
                '{"action":{"type":"respond","text":"INITIAL"}}',
            ),
            (
                "local_gguf",
                (
                    "codex_cli[unavailable]",
                    "nifdu_browser[unavailable]",
                    "local_gguf[success]",
                ),
                '{"action":{"type":"respond","text":"REPAIR"}}',
            ),
        ]
    )

    def fake_generate(
        prompt,
        system_prompt=None,
        **kwargs,
    ):
        name, route, response = next(calls)

        provider.last_provider = name
        provider.last_provider_route = list(route)

        # This deliberately represents sensitive internal diagnostics.
        # Visible route output must never derive from this field.
        provider.last_errors = [
            "SECRET_REFRESH_TOKEN_DIAGNOSTIC",
            "refresh token was revoked",
        ]

        return response

    monkeypatch.setattr(
        provider,
        "generate",
        fake_generate,
    )

    monkeypatch.setattr(
        "sophyane.config.load_config",
        lambda: {"provider": "ignored"},
    )

    monkeypatch.setattr(
        "sophyane.main.create_provider",
        lambda _config: provider,
    )

    def fake_run_adaptive_loop(**kwargs):
        kwargs["ask"](
            "REPAIR_SANITIZED_PROVIDER_ROUTE"
        )
        return "EXECUTION_COMPLETE"

    monkeypatch.setattr(
        "sophyane.adaptive_execution.run_adaptive_loop",
        fake_run_adaptive_loop,
    )

    result = cli._execute_repository_request(
        "Patch src/example.py.",
        workspace=tmp_path,
    )

    assert "EXECUTION_COMPLETE" in result

    # Existing successful-provider contract remains intact.
    assert (
        "Provider evidence: "
        "nifdu_browser -> local_gguf"
        in result
    )

    # New route evidence must preserve each provider call separately.
    assert (
        "Provider route 1: "
        "codex_cli[unavailable] -> "
        "nifdu_browser[success]"
        in result
    )

    assert (
        "Provider route 2: "
        "codex_cli[unavailable] -> "
        "nifdu_browser[unavailable] -> "
        "local_gguf[success]"
        in result
    )

    # Internal diagnostics must never cross the output boundary.
    assert "SECRET_REFRESH_TOKEN_DIAGNOSTIC" not in result
    assert "refresh token" not in result.casefold()


# SOPHYANE_MODE6_ONCE_EXIT_STATUS_TRUTHFULNESS_RED_V1
def test_once_repository_incomplete_execution_returns_nonzero(
    monkeypatch,
    capsys,
):
    """Uncompleted repository execution must not become process success."""

    request = "Build the requested project."

    monkeypatch.setattr(
        "sys.argv",
        [
            "sophyane-human-chat",
            "--once",
            request,
        ],
    )

    monkeypatch.setattr(
        cli,
        "_repository_execution_request",
        lambda text: text == request,
    )

    monkeypatch.setattr(
        cli,
        "_execute_repository_request",
        lambda text: "BOUNDED_EXECUTION_INCOMPLETE",
    )

    rc = cli.main()
    output = capsys.readouterr().out

    assert "BOUNDED_EXECUTION_INCOMPLETE" in output
    assert rc != 0


def test_once_repository_completed_execution_remains_success(
    monkeypatch,
    capsys,
):
    """Grounded completed-execution evidence remains exit status zero."""

    request = "Build the requested project."

    monkeypatch.setattr(
        "sys.argv",
        [
            "sophyane-human-chat",
            "--once",
            request,
        ],
    )

    monkeypatch.setattr(
        cli,
        "_repository_execution_request",
        lambda text: text == request,
    )

    monkeypatch.setattr(
        cli,
        "_execute_repository_request",
        lambda text: cli._CompletedRepositoryExecution(
            "VERIFIED_EXECUTION_COMPLETE"
        ),
    )

    rc = cli.main()
    output = capsys.readouterr().out

    assert "VERIFIED_EXECUTION_COMPLETE" in output
    assert rc == 0


def test_mode6_interactive_explicit_workspace_is_passed_to_executor(
    tmp_path,
    monkeypatch,
):
    """
    The interactive Mode-6 boundary must preserve an explicitly requested
    workspace when handing an actionable repository mission to the executor.

    The executor must not receive workspace=None and later fall back to the
    Sophyane process cwd.
    """
    import builtins
    import sys
    from pathlib import Path

    import sophyane.human_conversation_cli as cli

    # main() owns argparse; isolate it from pytest's process arguments.
    monkeypatch.setattr(
        sys,
        "argv",
        ["sophyane-human-chat"],
    )

    requested = tmp_path / "mode6_rsi_capability_test"
    requested.mkdir()

    monkeypatch.setattr(
        Path,
        "home",
        staticmethod(lambda: tmp_path),
    )

    request = (
        "Work in ~/mode6_rsi_capability_test.\n\n"
        "Read README.md and telemetry.sphy.\n"
        "Create a reusable Python program named sphy_telemetry.py.\n"
        "Then run it against telemetry.sphy and verify that its output "
        "exactly matches EXPECTED.txt."
    )

    submissions = iter(
        [
            request,
            "/exit",
        ]
    )

    monkeypatch.setattr(
        cli,
        "_read_atomic_submission",
        lambda _prompt: next(submissions),
    )

    class Actionable:
        reply = "Planning repository operation."
        semantic_disposition = "actionable_mission"

    monkeypatch.setattr(
        cli,
        "conversation_turn",
        lambda *args, **kwargs: Actionable(),
    )

    monkeypatch.setattr(
        cli,
        "_handoff_turn_improvement",
        lambda _result: None,
    )

    seen = []

    def fake_execute(text, *, workspace=None):
        seen.append(
            {
                "text": text,
                "workspace": workspace,
            }
        )
        return cli._CompletedRepositoryExecution(
            "verified"
        )

    monkeypatch.setattr(
        cli,
        "_execute_repository_request",
        fake_execute,
    )

    rc = cli.main()

    assert rc == 0
    assert len(seen) == 1
    assert seen[0]["text"] == request
    assert seen[0]["workspace"] == requested.resolve()


def test_mode6_repository_executor_hands_authoritative_capability_gap_to_failure_driven_controller(
    monkeypatch,
    tmp_path,
):
    """
    Once the selected LLM/adaptive execution path has produced an
    authoritative missing_reusable_capability result, Mode 6 must hand that
    failure to failure-driven development rather than merely returning the
    unresolved string.

    This test deliberately does not prescribe where the shared controller is
    stored.  It observes the public controller boundary instead.
    """
    from types import SimpleNamespace

    import sophyane.human_conversation_cli as cli
    from sophyane.failure_driven_capability import (
        CapabilityDevelopmentController,
        FailureClassification,
    )

    provider_calls = []

    class FakeProvider:
        def generate(
            self,
            prompt,
            system_prompt=None,
            **kwargs,
        ):
            provider_calls.append(
                {
                    "prompt": str(prompt),
                    "system_prompt": system_prompt,
                }
            )
            return (
                '{"action":{"type":"respond",'
                '"text":"LLM_AUTHORITY_REACHED"}}'
            )

    monkeypatch.setattr(
        "sophyane.config.load_config",
        lambda: {"provider": "ignored"},
    )
    monkeypatch.setattr(
        "sophyane.main.create_provider",
        lambda _config: FakeProvider(),
    )

    class AuthoritativeCapabilityGap(str):
        def __new__(cls):
            value = super().__new__(
                cls,
                "Stopped after bounded execution loop.\n\n"
                "Executable does not exist: sphy-telemetry",
            )
            value.failure_classification = (
                FailureClassification.MISSING_REUSABLE_CAPABILITY
            )
            value.capability_class = "executable.sphy-telemetry"
            value.failure_evidence = {
                "kind": "missing_executable",
                "executable": "sphy-telemetry",
                "request_declared_reusable_capability": True,
                "request_declared_missing_implementation": True,
            }
            return value

    adaptive_calls = []

    def fake_run_adaptive_loop(**kwargs):
        adaptive_calls.append(kwargs)
        return AuthoritativeCapabilityGap()

    monkeypatch.setattr(
        "sophyane.adaptive_execution.run_adaptive_loop",
        fake_run_adaptive_loop,
    )

    development_calls = []

    def fake_handle_failure(
        self,
        *,
        request,
        failure,
        classification,
        capability_class,
        execute_original=None,
    ):
        development_calls.append(
            {
                "controller": self,
                "request": request,
                "failure": failure,
                "classification": classification,
                "capability_class": capability_class,
                "execute_original": execute_original,
            }
        )

        # Keep this RED focused only on the handoff boundary.
        # Development/promotion/retry behavior is tested separately.
        return SimpleNamespace(
            accepted=False,
            decision="rejected_for_red_observation",
            retry_result=None,
            evidence={
                "observed_by": "mode6_handoff_red",
            },
        )

    monkeypatch.setattr(
        CapabilityDevelopmentController,
        "handle_failure",
        fake_handle_failure,
    )

    request = (
        "Work in ~/mode6_rsi_capability_test. "
        "I need a reusable SPHY-Telemetry parser, but there is "
        "currently no parser or implementation for that capability."
    )

    result = cli._execute_repository_request(
        request,
        workspace=tmp_path,
    )

    # The selected LLM boundary must have been crossed first.
    assert provider_calls, (
        "Mode 6 did not cross the selected LLM authority boundary"
    )

    # The adaptive execution lifecycle must also have run.
    assert len(adaptive_calls) == 1
    assert adaptive_calls[0]["original_request"] == request
    assert adaptive_calls[0]["workspace"] == tmp_path.resolve()

    # RED contract:
    # authoritative adaptive failure must activate failure-driven development.
    assert len(development_calls) == 1, (
        "Mode 6 returned the authoritative adaptive failure without "
        "handing it to CapabilityDevelopmentController.handle_failure"
    )

    handoff = development_calls[0]

    assert handoff["request"] == request
    assert (
        handoff["classification"]
        is FailureClassification.MISSING_REUSABLE_CAPABILITY
    )
    assert handoff["capability_class"] == (
        "executable.sphy-telemetry"
    )

    assert getattr(
        handoff["failure"],
        "failure_evidence",
        None,
    ) == {
        "kind": "missing_executable",
        "executable": "sphy-telemetry",
        "request_declared_reusable_capability": True,
        "request_declared_missing_implementation": True,
    }

    # Do not claim retry yet.  This RED only proves activation/handoff.
    assert result is not None


def test_mode6_failure_driven_controller_has_real_worker_and_independent_verifier(
    monkeypatch,
):
    """
    The shared Mode-6 failure-driven controller must not use the controller's
    deliberately non-promotable defaults.

    This RED does not require development to succeed.  It proves only that
    production wires a genuine development worker and an independent verifier
    into the shared controller owner.
    """
    import sophyane.human_conversation_cli as cli
    from sophyane.failure_driven_capability import (
        CapabilityDevelopmentController,
    )

    # Isolate this test from any controller created by an earlier test.
    monkeypatch.setattr(
        cli,
        "_mode6_failure_driven_controller",
        None,
    )

    controller = (
        cli._mode6_capability_development_controller()
    )

    assert isinstance(
        controller,
        CapabilityDevelopmentController,
    )

    # A real Mode-6 development worker must replace the deliberately inert
    # controller default.
    worker_func = getattr(
        controller.worker,
        "__func__",
        controller.worker,
    )
    default_worker_func = getattr(
        controller._default_worker,
        "__func__",
        controller._default_worker,
    )

    assert worker_func is not default_worker_func, (
        "Mode-6 failure-driven controller still uses the "
        "non-promotable default worker"
    )

    # The default verifier is an anonymous always-false lambda.  Exercise the
    # configured verifier with a sentinel candidate/request.  A production
    # verifier must have its own validation semantics rather than being the
    # constructor default.
    #
    # We deliberately do not assert True here: an independent verifier is
    # allowed to reject this meaningless sentinel.
    verifier = controller.verifier

    assert getattr(
        verifier,
        "__module__",
        "",
    ) != "sophyane.failure_driven_capability" or (
        getattr(verifier, "__name__", "") != "<lambda>"
    ), (
        "Mode-6 failure-driven controller still uses the "
        "constructor's always-false default verifier"
    )

    # Worker and verifier must also be distinct authorities/functions.
    assert verifier is not controller.worker, (
        "development worker and independent verifier must not be "
        "the same callable"
    )


def test_mode6_failure_driven_controller_is_bound_to_requested_workspace(
    monkeypatch,
    tmp_path,
):
    """
    Failure-driven development must be scoped to the explicitly requested
    Mode-6 workspace.

    A process-global controller may retain its capability store, but its
    development/verification adapter cannot be constructed without the
    workspace whose capability is being developed.
    """
    import inspect

    import sophyane.human_conversation_cli as cli

    monkeypatch.setattr(
        cli,
        "_mode6_failure_driven_controller",
        None,
    )

    signature = inspect.signature(
        cli._mode6_capability_development_controller
    )

    assert "workspace" in signature.parameters, (
        "Mode-6 failure-driven controller owner is not "
        "workspace-aware"
    )

    controller = cli._mode6_capability_development_controller(
        workspace=tmp_path,
    )

    assert controller is not None


# SOPHYANE_MODE6_FAILURE_DRIVEN_WORKER_BEHAVIOR_RED_V1
def test_mode6_failure_driven_implementation_worker_returns_candidate_proposal(
    monkeypatch,
    tmp_path,
):
    """
    A workspace-bound Mode-6 failure-driven controller must have a genuine
    implementation worker.

    This contract does not require a live provider.  A fake coding router
    supplies proposal evidence; production may defer when no coding provider
    is available, but it may not use the controller's inert default proposal.
    """
    import sophyane.human_conversation_cli as cli
    import sophyane.rsi.coding_provider as coding_provider

    class FakeRouter:
        def __init__(self, *args, **kwargs):
            pass

        def request(self, *args, **kwargs):
            return coding_provider.CodingResult(
                status="SUCCESS",
                provider="codex_cli",
                files={
                    "sphy_telemetry.py": (
                        "def main():\n"
                        "    return 0\n"
                    ),
                },
                failovers=(),
            )

    monkeypatch.setattr(
        coding_provider,
        "CodingRouter",
        FakeRouter,
    )

    monkeypatch.setattr(
        cli,
        "_mode6_failure_driven_controller",
        None,
    )

    controller = cli._mode6_capability_development_controller(
        workspace=tmp_path,
    )

    context = {
        "request": (
            "Create reusable SPHY-Telemetry support because no parser "
            "currently exists."
        ),
        "failure": {
            "kind": "missing_executable",
            "executable": "sphy-telemetry",
        },
        "classification": "missing_reusable_capability",
        "capability_class": "executable.sphy-telemetry",
        "attempt": 1,
        "candidate": None,
    }

    candidate = controller.worker(
        "implementation",
        context,
    )

    assert isinstance(candidate, dict)

    assert candidate != {
        "role": "implementation",
        "proposal": "unimplemented",
    }, (
        "Mode-6 implementation worker still returns the inert default "
        "capability proposal"
    )

    assert candidate["status"] == "SUCCESS"
    assert candidate["provider"] == "codex_cli"
    assert candidate["files"] == {
        "sphy_telemetry.py": (
            "def main():\n"
            "    return 0\n"
        ),
    }


def test_mode6_failure_driven_verifier_rejects_worker_self_claimed_success(
    monkeypatch,
    tmp_path,
):
    """
    Worker/provider claims are not independent verification.

    A candidate containing only self-asserted success and no independently
    verifiable implementation must be rejected by the Mode-6 verifier.
    """
    import sophyane.human_conversation_cli as cli

    monkeypatch.setattr(
        cli,
        "_mode6_failure_driven_controller",
        None,
    )

    controller = cli._mode6_capability_development_controller(
        workspace=tmp_path,
    )

    self_claimed_candidate = {
        "status": "SUCCESS",
        "provider": "codex_cli",
        "approved": True,
        "verified": True,
        "tests_passed": True,
        "files": {},
    }

    assert (
        controller.verifier(
            self_claimed_candidate,
            "Create reusable SPHY-Telemetry support.",
        )
        is False
    ), (
        "Mode-6 independent verifier trusted worker/provider "
        "self-asserted success"
    )


# SOPHYANE_MODE6_PROVIDER_BACKED_CAPABILITY_WORKER_RED_V1
def test_mode6_failure_driven_implementation_worker_uses_coding_router_without_mutating_primary(
    monkeypatch,
    tmp_path,
):
    """
    The Mode-6 capability implementation worker must obtain implementation
    bytes from the external coding-provider router while leaving the primary
    requested workspace untouched.

    Provider identity and proposed files must survive as evidence for later
    independent verification/promotion.  The provider is not allowed to
    approve or promote its own proposal.
    """
    import sophyane.human_conversation_cli as cli
    import sophyane.rsi.coding_provider as coding_provider

    workspace = (tmp_path / "workspace").resolve()
    workspace.mkdir()

    telemetry = workspace / "telemetry.sphy"
    telemetry.write_text(
        "NODE|alpha|TEMP=41.5|LOAD=72\n",
        encoding="utf-8",
    )

    before = {
        p.relative_to(workspace).as_posix(): p.read_bytes()
        for p in workspace.rglob("*")
        if p.is_file()
    }

    router_calls = []

    class FakeRouter:
        def __init__(self, *args, **kwargs):
            router_calls.append(
                {
                    "event": "construct",
                    "args": args,
                    "kwargs": kwargs,
                }
            )

        def request(
            self,
            prompt,
            requested_workspace,
            *,
            cancelled=lambda: False,
            timeout=300,
        ):
            router_calls.append(
                {
                    "event": "request",
                    "prompt": str(prompt),
                    "workspace": requested_workspace,
                    "timeout": timeout,
                }
            )

            return coding_provider.CodingResult(
                status="SUCCESS",
                provider="codex_cli",
                files={
                    "sphy_telemetry.py": (
                        "def main():\n"
                        "    return 0\n"
                    ),
                },
                failovers=(),
            )

    monkeypatch.setattr(
        coding_provider,
        "CodingRouter",
        FakeRouter,
    )

    monkeypatch.setattr(
        cli,
        "_mode6_failure_driven_controller",
        None,
    )

    controller = cli._mode6_capability_development_controller(
        workspace=workspace,
    )

    context = {
        "request": (
            "Work in the requested workspace. "
            "Create reusable SPHY-Telemetry support because there is "
            "currently no parser or reusable implementation."
        ),
        "failure": {
            "kind": "missing_executable",
            "executable": "sphy-telemetry",
        },
        "classification": "missing_reusable_capability",
        "capability_class": "executable.sphy-telemetry",
        "attempt": 1,
        "candidate": None,
    }

    candidate = controller.worker(
        "implementation",
        context,
    )

    requests = [
        event
        for event in router_calls
        if event["event"] == "request"
    ]

    assert len(requests) == 1, (
        "Mode-6 implementation worker did not issue exactly one "
        "bounded coding-router proposal request"
    )

    assert requests[0]["workspace"] == workspace

    prompt = requests[0]["prompt"]

    assert "SPHY-Telemetry" in prompt
    assert "executable.sphy-telemetry" in prompt

    assert isinstance(candidate, dict)

    assert candidate.get("status") == "SUCCESS"
    assert candidate.get("provider") == "codex_cli"

    assert candidate.get("files") == {
        "sphy_telemetry.py": (
            "def main():\n"
            "    return 0\n"
        ),
    }

    # Provider output is proposal evidence only.
    assert candidate.get("verified") is not True
    assert candidate.get("approved") is not True
    assert candidate.get("promoted") is not True

    after = {
        p.relative_to(workspace).as_posix(): p.read_bytes()
        for p in workspace.rglob("*")
        if p.is_file()
    }

    assert after == before, (
        "coding-provider proposal mutated the primary Mode-6 workspace "
        "before independent verification/promotion"
    )

    assert not (workspace / "sphy_telemetry.py").exists()


def test_mode6_failure_driven_implementation_worker_preserves_provider_defer(
    monkeypatch,
    tmp_path,
):
    """
    Provider unavailability is evidence, not permission to manufacture a
    candidate locally.
    """
    import sophyane.human_conversation_cli as cli
    import sophyane.rsi.coding_provider as coding_provider

    class FakeRouter:
        def __init__(self, *args, **kwargs):
            pass

        def request(self, *args, **kwargs):
            return coding_provider.CodingResult(
                status="DEFERRED_NO_CODING_PROVIDER",
                failovers=(
                    {
                        "provider": "codex_cli",
                        "status": "unavailable",
                    },
                    {
                        "provider": "nifdu_browser",
                        "status": "unavailable",
                    },
                ),
            )

    monkeypatch.setattr(
        coding_provider,
        "CodingRouter",
        FakeRouter,
    )

    monkeypatch.setattr(
        cli,
        "_mode6_failure_driven_controller",
        None,
    )

    controller = cli._mode6_capability_development_controller(
        workspace=tmp_path,
    )

    candidate = controller.worker(
        "implementation",
        {
            "request": "Create reusable parser support.",
            "failure": {
                "kind": "missing_executable",
                "executable": "sphy-telemetry",
            },
            "classification": "missing_reusable_capability",
            "capability_class": "executable.sphy-telemetry",
            "attempt": 1,
            "candidate": None,
        },
    )

    assert isinstance(candidate, dict)

    assert candidate.get("status") == (
        "DEFERRED_NO_CODING_PROVIDER"
    )

    assert not candidate.get("files")

    assert candidate.get("verified") is not True
    assert candidate.get("approved") is not True
    assert candidate.get("promoted") is not True


# SOPHYANE_MODE6_INDEPENDENT_CANDIDATE_VERIFIER_RED_V1

def test_mode6_failure_driven_verifier_validates_isolated_candidate_without_mutating_primary(
    monkeypatch,
    tmp_path,
):
    """
    Provider proposal bytes are not trusted verification evidence.

    Mode 6 must:
      * derive mutation scope from the host-owned request contract,
      * materialize proposed bytes only in an isolated candidate,
      * run host-owned verification there,
      * ignore provider-supplied verification commands/claims,
      * leave the primary workspace byte-for-byte unchanged.
    """
    import sys

    import sophyane.human_conversation_cli as cli
    import sophyane.rsi.coding_provider as coding_provider
    import sophyane.rsi.verification as verification

    workspace = (tmp_path / "workspace").resolve()
    workspace.mkdir()

    (workspace / "README.md").write_text(
        "# SPHY-Telemetry v1\n"
        "\n"
        "Each data line is:\n"
        "NODE|name|TEMP=<decimal>|LOAD=<integer>\n"
        "\n"
        "OVERLOAD if LOAD >= 90.\n"
        "WARNING if TEMP >= 40 and LOAD < 90.\n"
        "NORMAL otherwise.\n"
        "Comments are ignored.\n"
        "\n"
        "Create reusable Python program sphy_telemetry.py.\n",
        encoding="utf-8",
    )

    (workspace / "telemetry.sphy").write_text(
        "# SPHY-Telemetry v1\n"
        "NODE|alpha|TEMP=41.5|LOAD=72\n"
        "NODE|beta|TEMP=38.0|LOAD=91\n"
        "NODE|gamma|TEMP=44.5|LOAD=63\n",
        encoding="utf-8",
    )

    (workspace / "EXPECTED.txt").write_text(
        "alpha,41.5,72,WARNING\n"
        "beta,38.0,91,OVERLOAD\n"
        "gamma,44.5,63,WARNING\n",
        encoding="utf-8",
    )

    before = {
        path.relative_to(workspace).as_posix():
            path.read_bytes()
        for path in workspace.rglob("*")
        if path.is_file()
    }

    run_calls = []
    real_run_command = verification.run_command

    def recording_run_command(
        command,
        cwd,
        *,
        timeout=300,
        cancelled=lambda: False,
    ):
        run_calls.append(
            {
                "command": tuple(command),
                "cwd": cwd.resolve(),
            }
        )
        return real_run_command(
            command,
            cwd,
            timeout=timeout,
            cancelled=cancelled,
        )

    monkeypatch.setattr(
        verification,
        "run_command",
        recording_run_command,
    )

    # This behavioral test verifies the Mode-6 host-owned verifier contract,
    # not OS sandbox availability. RSI sandbox enforcement itself is covered
    # independently by tests/rsi/test_execution_sandbox.py. Keep production
    # fail-closed while allowing the already-isolated temporary candidate to
    # execute inside this test process environment.
    monkeypatch.setattr(
        verification,
        "sandbox_command",
        lambda command, _cwd, _scratch: list(command),
    )

    monkeypatch.setattr(
        cli,
        "_mode6_failure_driven_controller",
        None,
    )

    controller = cli._mode6_capability_development_controller(
        workspace=workspace,
    )

    proposed_program = "from pathlib import Path\nimport sys\n\ndef classify(temp, load):\n    if load >= 90:\n        return 'OVERLOAD'\n    if temp >= 40:\n        return 'WARNING'\n    return 'NORMAL'\n\ndef main():\n    for raw in Path(sys.argv[1]).read_text().splitlines():\n        line = raw.strip()\n        if not line or line.startswith('#'):\n            continue\n        node, name, temp_field, load_field = line.split('|')\n        if node != 'NODE':\n            raise ValueError('invalid record')\n        temp_text = temp_field.split('=', 1)[1]\n        load_text = load_field.split('=', 1)[1]\n        temp = float(temp_text)\n        load = int(load_text)\n        print(\n            f'{name},{temp_text},{load_text},'\n            f'{classify(temp, load)}'\n        )\n\nif __name__ == '__main__':\n    main()\n"

    class FakeRouter:
        def __init__(self, *args, **kwargs):
            pass

        def request(self, *args, **kwargs):
            return coding_provider.CodingResult(
                status="SUCCESS",
                provider="codex_cli",
                files={
                    "sphy_telemetry.py": proposed_program,
                },
                failovers=(),
            )

    monkeypatch.setattr(
        coding_provider,
        "CodingRouter",
        FakeRouter,
    )

    request = (
        "Work in the requested workspace. "
        "Read README.md and telemetry.sphy. "
        "Create reusable Python program sphy_telemetry.py that reads "
        "telemetry.sphy and writes CSV records as "
        "name,temp,load,status. "
        "Verify its output exactly matches EXPECTED.txt."
    )

    context = {
        "request": request,
        "failure": {
            "kind": "missing_executable",
            "executable": "sphy_telemetry.py",
        },
        "classification": "missing_reusable_capability",
        "capability_class": "executable.sphy_telemetry.py",
        "attempt": 1,
    }

    candidate = controller.worker(
        "implementation",
        context,
    )

    assert candidate["status"] == "SUCCESS"
    assert candidate["provider"] == "codex_cli"
    assert candidate["files"] == {
        "sphy_telemetry.py": proposed_program,
    }

    # Preserve the original hostile/self-serving evidence contract.
    # These fields are deliberately added after the real Mode-6 worker
    # created its host-owned provider provenance receipt. They grant no
    # authority and the provider-selected command must never execute.
    candidate["verified"] = True
    candidate["approved"] = True
    candidate["verification_command"] = [
        sys.executable,
        "-c",
        "raise SystemExit('PROVIDER_COMMAND_MUST_NOT_RUN')",
    ]

    verified = controller.verifier(
        candidate,
        request,
    )

    assert verified is True, (
        "Mode-6 independent verifier did not accept a valid isolated "
        "candidate after host-owned verification"
    )

    after = {
        path.relative_to(workspace).as_posix():
            path.read_bytes()
        for path in workspace.rglob("*")
        if path.is_file()
    }

    assert after == before, (
        "independent candidate verification mutated the primary workspace"
    )

    assert not (workspace / "sphy_telemetry.py").exists(), (
        "candidate implementation escaped into the primary workspace "
        "before trusted promotion"
    )

    assert run_calls, (
        "independent verifier did not execute host-owned verification"
    )

    assert all(
        call["cwd"] != workspace
        for call in run_calls
    ), (
        "verification executed in the primary workspace instead of an "
        "isolated candidate"
    )

    assert all(
        "PROVIDER_COMMAND_MUST_NOT_RUN"
        not in " ".join(call["command"])
        for call in run_calls
    ), (
        "provider supplied its own verification command"
    )

    assert any(
        "sphy_telemetry.py" in " ".join(call["command"])
        and "telemetry.sphy" in " ".join(call["command"])
        for call in run_calls
    ), (
        "host verification did not exercise the requested capability"
    )


def test_mode6_verified_candidate_promotes_exact_bytes_through_trusted_broker(
    monkeypatch,
    tmp_path,
):
    """
    Transition #4 is an orchestration contract, not a verifier contract.

    The Mode-6 verifier must remain non-mutating.  After it independently
    accepts candidate bytes, the controller's distinct promoter stage must
    rematerialize exactly those verified bytes and cross the existing
    CandidateWorkspace -> trusted-host broker boundary.

    Provider approval, allowed_paths, promoted, and verification-command
    claims grant no authority.
    """
    import sys

    import sophyane.human_conversation_cli as cli
    import sophyane.rsi.coding_provider as coding_provider
    import sophyane.rsi.verification as verification
    import sophyane.rsi_host_broker as broker
    from sophyane.failure_driven_capability import (
        FailureClassification,
    )

    workspace = (tmp_path / "workspace").resolve()
    workspace.mkdir()

    (workspace / "README.md").write_text(
        "# SPHY-Telemetry v1\n"
        "\n"
        "Each data line is:\n"
        "NODE|name|TEMP=<decimal>|LOAD=<integer>\n"
        "\n"
        "OVERLOAD if LOAD >= 90.\n"
        "WARNING if TEMP >= 40 and LOAD < 90.\n"
        "NORMAL otherwise.\n"
        "Comments are ignored.\n",
        encoding="utf-8",
    )

    (workspace / "telemetry.sphy").write_text(
        "# SPHY-Telemetry v1\n"
        "NODE|alpha|TEMP=41.5|LOAD=72\n"
        "NODE|beta|TEMP=38.0|LOAD=91\n"
        "NODE|gamma|TEMP=44.5|LOAD=63\n",
        encoding="utf-8",
    )

    (workspace / "EXPECTED.txt").write_text(
        "alpha,41.5,72,WARNING\n"
        "beta,38.0,91,OVERLOAD\n"
        "gamma,44.5,63,WARNING\n",
        encoding="utf-8",
    )

    original_files = {
        path.relative_to(workspace).as_posix():
            path.read_bytes()
        for path in workspace.rglob("*")
        if path.is_file()
    }

    proposed_program = (
        "from pathlib import Path\n"
        "import sys\n"
        "\n"
        "def classify(temp, load):\n"
        "    if load >= 90:\n"
        "        return 'OVERLOAD'\n"
        "    if temp >= 40:\n"
        "        return 'WARNING'\n"
        "    return 'NORMAL'\n"
        "\n"
        "def main():\n"
        "    for raw in Path(sys.argv[1]).read_text().splitlines():\n"
        "        line = raw.strip()\n"
        "        if not line or line.startswith('#'):\n"
        "            continue\n"
        "        node, name, temp_field, load_field = line.split('|')\n"
        "        if node != 'NODE':\n"
        "            raise ValueError('invalid record')\n"
        "        temp_text = temp_field.split('=', 1)[1]\n"
        "        load_text = load_field.split('=', 1)[1]\n"
        "        temp = float(temp_text)\n"
        "        load = int(load_text)\n"
        "        print(\n"
        "            f'{name},{temp_text},{load_text},'\n"
        "            f'{classify(temp, load)}'\n"
        "        )\n"
        "\n"
        "if __name__ == '__main__':\n"
        "    main()\n"
    )

    class FakeRouter:
        def __init__(self, *args, **kwargs):
            pass

        def request(self, *args, **kwargs):
            # Deterministic provider-free proposal.  The real Mode-6 worker
            # observes this provider identity and creates the host-owned
            # worker -> verifier attestation receipt.
            return coding_provider.CodingResult(
                status="SUCCESS",
                provider="codex_cli",
                files={
                    "sphy_telemetry.py": proposed_program,
                },
                failovers=(),
            )

    monkeypatch.setattr(
        coding_provider,
        "CodingRouter",
        FakeRouter,
    )

    request = (
        "Work in the requested workspace. "
        "Read README.md and telemetry.sphy. "
        "Create reusable Python program sphy_telemetry.py that reads "
        "telemetry.sphy and writes CSV records as "
        "name,temp,load,status. "
        "Verify its output exactly matches EXPECTED.txt."
    )

    # This test exercises orchestration semantics rather than Bubblewrap
    # availability. Production sandbox fail-closed behavior has its own
    # independent security tests.
    monkeypatch.setattr(
        verification,
        "sandbox_command",
        lambda command, _cwd, _scratch: list(command),
    )

    promotions = []
    real_promote_snapshot = broker.promote_snapshot

    def recording_promote_snapshot(
        repository,
        baseline,
        candidate_snapshot,
        evidence,
        allowed_paths,
        *,
        candidate_source=None,
    ):
        assert candidate_snapshot is None
        assert candidate_source is not None

        from sophyane.rsi.candidate_workspace import snapshot

        live = snapshot(candidate_source)

        promotions.append(
            {
                "repository": repository.resolve(),
                "fingerprint": live.fingerprint,
                "files": dict(live.files),
                "evidence_accepted": evidence.accepted,
                "evidence_fingerprint": evidence.fingerprint,
                "allowed_paths": set(allowed_paths),
            }
        )

        return real_promote_snapshot(
            repository,
            baseline,
            candidate_snapshot,
            evidence,
            allowed_paths,
            candidate_source=candidate_source,
        )

    monkeypatch.setattr(
        broker,
        "promote_snapshot",
        recording_promote_snapshot,
    )

    monkeypatch.setattr(
        cli,
        "_mode6_failure_driven_controller",
        None,
    )

    controller = cli._mode6_capability_development_controller(
        workspace=workspace,
    )

    # Keep the test deterministic and provider-free, but exercise the real
    # Mode-6 implementation worker so CodingRouter provider provenance crosses
    # the same host-owned worker -> verifier authority boundary as production.
    controller.max_attempts = 1

    result = controller.handle_failure(
        request=request,
        failure="executable does not exist: sphy_telemetry.py",
        classification=(
            FailureClassification.MISSING_REUSABLE_CAPABILITY
        ),
        capability_class="executable.sphy_telemetry.py",
        execute_original=None,
    )

    assert result.accepted is True, (
        "verified Mode-6 candidate was not accepted by the "
        "post-verification promotion stage"
    )

    assert len(promotions) == 1, (
        "independently verified Mode-6 candidate never crossed "
        "the trusted promotion broker"
    )

    promotion = promotions[0]

    assert promotion["repository"] == workspace
    assert promotion["evidence_accepted"] is True

    # The broker's live rematerialized bytes must be exactly the bytes
    # covered by host-owned verification evidence.
    assert (
        promotion["evidence_fingerprint"]
        == promotion["fingerprint"]
    )

    # Provider-supplied allowed_paths cannot expand host authority.
    assert promotion["allowed_paths"] == {
        "sphy_telemetry.py",
    }

    assert (
        promotion["files"]["sphy_telemetry.py"]
        == proposed_program.encode("utf-8")
    )

    # Inputs/oracle survive promotion byte-for-byte.
    for name, value in original_files.items():
        assert (workspace / name).read_bytes() == value

    # Exact trusted bytes are now primary.
    assert (
        workspace / "sphy_telemetry.py"
    ).read_bytes() == proposed_program.encode("utf-8")

    # The reusable store must contain the promoter-returned trusted artifact,
    # not gain success merely from worker self-claims.
    stored = controller.store.get(
        "executable.sphy_telemetry.py"
    )

    assert stored is not None

    # Promotion is not original-request retry.
    assert result.retry_original_request is False
    assert result.evidence["retry_result"] is None


def test_mode6_trusted_promoted_candidate_executes_without_provider(
    monkeypatch,
    tmp_path,
):
    """
    A trusted artifact that already crossed the promotion broker must have a
    bounded host-owned execution path.

    This is post-promotion execution only:
      * no LLM/provider request,
      * no recursive repository executor,
      * only the exact promoted program may execute,
      * success requires the expected workspace result.
    """
    import sophyane.human_conversation_cli as cli
    from sophyane.rsi import verification

    # Behavioral contract only.  Production keeps the real fail-closed
    # Bubblewrap boundary.
    monkeypatch.setattr(
        verification,
        "sandbox_command",
        lambda command, _cwd, _scratch: list(command),
    )

    workspace = tmp_path.resolve()

    (workspace / "telemetry.sphy").write_text(
        "# SPHY-Telemetry v1\n"
        "NODE|alpha|TEMP=41.5|LOAD=72\n"
        "NODE|beta|TEMP=38.0|LOAD=91\n"
        "NODE|gamma|TEMP=44.5|LOAD=63\n"
    )

    (workspace / "EXPECTED.txt").write_text(
        "alpha,41.5,72,WARNING\n"
        "beta,38.0,91,OVERLOAD\n"
        "gamma,44.5,63,WARNING\n"
    )

    program = workspace / "sphy_telemetry.py"

    program.write_text(
        "import sys\n"
        "from pathlib import Path\n"
        "\n"
        "def main():\n"
        "    for raw in Path(sys.argv[1]).read_text().splitlines():\n"
        "        if not raw or raw.startswith('#'):\n"
        "            continue\n"
        "        parts = raw.split('|')\n"
        "        name = parts[1]\n"
        "        temp = parts[2].split('=', 1)[1]\n"
        "        load = parts[3].split('=', 1)[1]\n"
        "        load_i = int(load)\n"
        "        temp_f = float(temp)\n"
        "        if load_i >= 90:\n"
        "            status = 'OVERLOAD'\n"
        "        elif temp_f >= 40:\n"
        "            status = 'WARNING'\n"
        "        else:\n"
        "            status = 'NORMAL'\n"
        "        print(f'{name},{temp},{load},{status}')\n"
        "\n"
        "if __name__ == '__main__':\n"
        "    main()\n"
    )

    candidate = {
        "status": "TRUSTED_PROMOTED",
        "provider": "codex_cli",
        "capability_class": "executable.sphy_telemetry.py",
        "files": {
            "sphy_telemetry.py": program.read_text(),
        },
        "fingerprint": "host-attested-test-fingerprint",
    }

    request = (
        "Create the missing reusable Python program "
        "sphy_telemetry.py, run it against telemetry.sphy, "
        "and verify that its output exactly matches EXPECTED.txt."
    )

    # Any provider acquisition during post-promotion retry is a contract
    # violation.
    monkeypatch.setattr(
        cli,
        "_mode6_create_provider",
        lambda *args, **kwargs: (
            (_ for _ in ()).throw(
                AssertionError(
                    "post-promotion retry acquired a provider"
                )
            )
        ),
        raising=False,
    )

    # Recursive Mode-6 execution would re-enter provider/adaptive routing.
    original_repository_executor = cli._execute_repository_request

    def forbidden_recursive_repository_execution(*args, **kwargs):
        raise AssertionError(
            "post-promotion retry recursively entered "
            "_execute_repository_request"
        )

    monkeypatch.setattr(
        cli,
        "_execute_repository_request",
        forbidden_recursive_repository_execution,
    )

    executor = getattr(
        cli,
        "_execute_mode6_promoted_capability",
        None,
    )

    assert callable(executor), (
        "Mode-6 has no bounded executor for a trusted promoted capability"
    )

    result = executor(
        candidate,
        request,
        workspace=workspace,
    )

    assert result is True, (
        "trusted promoted capability did not verify the original request"
    )

    # Keep the saved reference live so the recursion guard above is explicit:
    # the tested executor must not be the ordinary repository executor itself.
    assert executor is not original_repository_executor



def test_mode6_missing_capability_handoff_supplies_post_promotion_retry(
    monkeypatch,
    tmp_path,
):
    """
    Transition #5:

    The live Mode-6 failure handoff must supply an original-request executor
    to the failure-driven controller.  Promotion alone is not completion.

    This test stops at the controller boundary: no provider, candidate
    execution, or primary mutation is performed.
    """
    import sophyane.human_conversation_cli as cli
    from sophyane.failure_driven_capability import (
        CapabilityDevelopmentResult,
        FailureClassification,
    )

    workspace = tmp_path.resolve()

    class MissingCapabilityFailure(str):
        failure_classification = (
            FailureClassification.MISSING_REUSABLE_CAPABILITY
        )
        capability_class = "executable.sphy_telemetry.py"
        failure_evidence = {
            "kind": "missing_executable",
            "executable": "sphy_telemetry.py",
            "request_declared_reusable_capability": True,
            "request_declared_missing_implementation": True,
        }

    adaptive_failure = MissingCapabilityFailure(
        "executable does not exist: sphy_telemetry.py"
    )

    captured = {}

    class FakeController:
        def handle_failure(
            self,
            *,
            request,
            failure,
            classification,
            capability_class,
            execute_original=None,
        ):
            captured["request"] = request
            captured["failure"] = failure
            captured["classification"] = classification
            captured["capability_class"] = capability_class
            captured["execute_original"] = execute_original

            return CapabilityDevelopmentResult(
                accepted=True,
                retry_original_request=False,
                trace=(),
                evidence={
                    "promotion_decision": "accepted",
                    "retry_result": None,
                },
            )

    monkeypatch.setattr(
        cli,
        "_mode6_capability_development_controller",
        lambda *, workspace=None: FakeController(),
    )

    # Initial Mode-6 provider boundary is stubbed: no real request.
    class FakeProvider:
        def ask(self, _prompt):
            return "proposal"

    monkeypatch.setattr(
        cli,
        "_mode6_create_provider",
        lambda *args, **kwargs: FakeProvider(),
        raising=False,
    )

    # Use the actual symbol consumed by _execute_repository_request.
    import sophyane.adaptive_execution as adaptive

    monkeypatch.setattr(
        adaptive,
        "run_adaptive_loop",
        lambda *args, **kwargs: adaptive_failure,
    )

    request = (
        "Create the missing reusable Python program "
        "sphy_telemetry.py and verify it."
    )

    # Use the real execution signature directly.  The repository executor
    # accepts the request as positional ``text`` plus keyword-only workspace.
    cli._execute_repository_request(
        request,
        workspace=workspace,
    )

    assert "execute_original" in captured, (
        "Mode-6 missing-capability failure never reached "
        "the failure-driven controller"
    )

    assert callable(captured["execute_original"]), (
        "trusted promotion has no Mode-6 original-request retry executor"
    )



def test_mode6_successful_post_promotion_retry_completes_first_request(
    monkeypatch,
    tmp_path,
):
    """
    A successful failure-driven development + trusted post-promotion retry
    must complete the same first user request.

    The original adaptive missing-capability failure must not be returned
    after the controller has independently verified the retry.
    """
    from types import SimpleNamespace

    import sophyane.human_conversation_cli as cli
    import sophyane.adaptive_execution as adaptive
    import sophyane.capability_executors as capability_executors

    workspace = (tmp_path / "workspace").resolve()
    workspace.mkdir()

    request = (
        "Create reusable Python program first_request_tool.py "
        "and use it for this request."
    )

    original_failure = (
        "missing_reusable_capability: "
        "executable does not exist: first_request_tool.py"
    )

    # The ordinary provider path is deterministic and provider-free here.
    class FakeProvider:
        name = "codex_cli"

        def ask(self, *_args, **_kwargs):
            return "provider proposal"

    monkeypatch.setattr(
        cli,
        "_mode6_create_provider",
        lambda *args, **kwargs: FakeProvider(),
        raising=False,
    )

    # No already-promoted deterministic capability exists on entry.
    # _execute_repository_request imports this symbol locally from the
    # defining module, so patch that module rather than cli.
    monkeypatch.setattr(
        capability_executors,
        "execute_deterministic_capability",
        lambda *_args, **_kwargs: None,
    )

    # Force the authoritative adaptive result into the already-covered
    # missing reusable capability handoff.  The classifier metadata belongs
    # to adaptive execution; the repository executor must only consume it.
    from sophyane.failure_driven_capability import (
        FailureClassification,
    )

    class MissingCapabilityFailure(str):
        failure_classification = (
            FailureClassification.MISSING_REUSABLE_CAPABILITY
        )
        capability_class = "executable.first_request_tool.py"
        failure_evidence = {
            "kind": "missing_executable",
            "executable": "first_request_tool.py",
            "request_declared_reusable_capability": True,
            "request_declared_missing_implementation": True,
        }

    adaptive_failure = MissingCapabilityFailure(
        original_failure
    )

    monkeypatch.setattr(
        adaptive,
        "run_adaptive_loop",
        lambda *_args, **_kwargs: adaptive_failure,
    )

    calls = {
        "handle_failure": 0,
        "execute_original": 0,
    }

    class FakeController:
        mode6_workspace = workspace
        mode6_trusted_workspaces = {}

        def execute_or_reuse(self, *_args, **_kwargs):
            return SimpleNamespace(
                reused=False,
                original_outcome_verified=False,
                evidence={},
            )

        def handle_failure(
            self,
            *,
            request,
            failure,
            classification,
            capability_class,
            execute_original,
        ):
            calls["handle_failure"] += 1

            assert failure == original_failure
            assert capability_class == "executable.first_request_tool.py"

            # The controller contract says this callback is the actual
            # post-promotion retry of the original operation.
            calls["execute_original"] += 1

            assert execute_original(
                {
                    "status": "TRUSTED_PROMOTED",
                    "provider": "codex_cli",
                    "capability_class": capability_class,
                    "files": {
                        "first_request_tool.py": "print('ok')\n",
                    },
                    "fingerprint": "verified",
                },
                request,
            ) is True

            return SimpleNamespace(
                accepted=True,
                retry_original_request=True,
                trace=[
                    "promote",
                    "retry_original_request",
                    "verify_original_outcome",
                ],
                evidence={
                    "promotion_decision": "accepted",
                    "retry_result": True,
                },
            )

    fake_controller = FakeController()

    monkeypatch.setattr(
        cli,
        "_mode6_capability_development_controller",
        lambda *, workspace=None: fake_controller,
    )

    # Keep this RED about the caller's handling of the controller result,
    # not about the already-green promoted-capability executor.
    monkeypatch.setattr(
        cli,
        "_execute_mode6_promoted_capability",
        lambda candidate, request, *, workspace: True,
    )

    result = cli._execute_repository_request(
        request,
        workspace=workspace,
    )

    assert calls == {
        "handle_failure": 1,
        "execute_original": 1,
    }

    assert isinstance(
        result,
        cli._CompletedRepositoryExecution,
    ), (
        "successful post-promotion retry was discarded and the "
        "first request did not become a completed execution"
    )

    assert original_failure not in str(result), (
        "the original missing-capability failure leaked to the user "
        "after the retry had already succeeded"
    )


def test_mode6_second_request_reuses_trusted_promoted_capability_without_provider_or_redevelopment(
    monkeypatch,
    tmp_path,
):
    """
    Transition #6:

    Once a reusable executable has independently verified and crossed trusted
    promotion, a later same-class Mode-6 request must reuse that exact trusted
    artifact after the user turn's intelligence boundary but before acquiring
    another repository-execution provider.

    Store presence alone is not success: the promoted executor must execute
    and independently verify the later request in the current workspace.
    """
    import sophyane.human_conversation_cli as cli
    from sophyane.failure_driven_capability import (
        InMemoryCapabilityStore,
    )
    from sophyane.rsi import verification

    # Behavioral contract only. Production remains fail-closed when the
    # supported RSI sandbox is unavailable.
    monkeypatch.setattr(
        verification,
        "sandbox_command",
        lambda command, _cwd, _scratch: list(command),
    )

    workspace = tmp_path.resolve()

    (workspace / "telemetry.sphy").write_text(
        "# SPHY-Telemetry v1\n"
        "NODE|alpha|TEMP=41.5|LOAD=72\n"
        "NODE|beta|TEMP=38.0|LOAD=91\n"
        "NODE|gamma|TEMP=44.5|LOAD=63\n",
        encoding="utf-8",
    )

    (workspace / "EXPECTED.txt").write_text(
        "alpha,41.5,72,WARNING\n"
        "beta,38.0,91,OVERLOAD\n"
        "gamma,44.5,63,WARNING\n",
        encoding="utf-8",
    )

    program_text = (
        "import sys\n"
        "from pathlib import Path\n"
        "\n"
        "def main():\n"
        "    for raw in Path(sys.argv[1]).read_text().splitlines():\n"
        "        if not raw or raw.startswith('#'):\n"
        "            continue\n"
        "        parts = raw.split('|')\n"
        "        name = parts[1]\n"
        "        temp = parts[2].split('=', 1)[1]\n"
        "        load = parts[3].split('=', 1)[1]\n"
        "        load_i = int(load)\n"
        "        temp_f = float(temp)\n"
        "        if load_i >= 90:\n"
        "            status = 'OVERLOAD'\n"
        "        elif temp_f >= 40:\n"
        "            status = 'WARNING'\n"
        "        else:\n"
        "            status = 'NORMAL'\n"
        "        print(f'{name},{temp},{load},{status}')\n"
        "\n"
        "if __name__ == '__main__':\n"
        "    main()\n"
    )

    (workspace / "sphy_telemetry.py").write_text(
        program_text,
        encoding="utf-8",
    )

    trusted = {
        "status": "TRUSTED_PROMOTED",
        "provider": "codex_cli",
        "capability_class": "executable.sphy_telemetry.py",
        "files": {
            "sphy_telemetry.py": program_text,
        },
        "fingerprint": "trusted-test-fingerprint",
    }

    class ReuseResult:
        reused = True
        original_outcome_verified = True

    calls = {
        "execute_or_reuse": 0,
        "development": 0,
        "provider": 0,
        "execute": 0,
    }

    class ReuseController:
        def __init__(self):
            self.store = InMemoryCapabilityStore()
            self.store.put(
                "executable.sphy_telemetry.py",
                trusted,
            )
            self.mode6_workspace = None
            self.mode6_trusted_workspaces = {
                "executable.sphy_telemetry.py": workspace,
            }

        def execute_or_reuse(
            self,
            *,
            request,
            capability_class,
            execute=None,
            **kwargs,
        ):
            calls["execute_or_reuse"] += 1

            assert (
                capability_class
                == "executable.sphy_telemetry.py"
            )

            assert self.mode6_workspace == workspace

            candidate = self.store.get(capability_class)

            assert candidate is trusted

            executor = execute

            if executor is None:
                executor = kwargs.get("execute_original")

            assert callable(executor)

            calls["execute"] += 1

            assert executor(candidate, request) is True

            return ReuseResult()

        def handle_failure(self, **kwargs):
            calls["development"] += 1
            raise AssertionError(
                "second same-class request re-entered capability development"
            )

    controller = ReuseController()

    monkeypatch.setattr(
        cli,
        "_mode6_capability_development_controller",
        lambda *, workspace=None: (
            setattr(
                controller,
                "mode6_workspace",
                (
                    workspace.resolve()
                    if workspace is not None
                    else None
                ),
            )
            or controller
        ),
    )

    # A second repository provider request is forbidden. The genuine user
    # turn has already crossed Mode-6's selected intelligence boundary before
    # entering _execute_repository_request().
    def forbidden_provider(*args, **kwargs):
        calls["provider"] += 1
        raise AssertionError(
            "second same-class request acquired another provider "
            "instead of reusing the trusted promoted capability"
        )

    monkeypatch.setattr(
        "sophyane.main.create_provider",
        forbidden_provider,
    )

    request = (
        "Use the reusable sphy_telemetry.py program on "
        "telemetry.sphy and verify that its output exactly "
        "matches EXPECTED.txt."
    )

    result = cli._execute_repository_request(
        request,
        workspace=workspace,
    )

    assert calls["execute_or_reuse"] == 1, (
        "Mode-6 never attempted trusted capability reuse "
        "before provider acquisition"
    )

    assert calls["execute"] == 1, (
        "stored trusted capability was not executed and "
        "independently verified for the second request"
    )

    assert calls["development"] == 0, (
        "second same-class request redeveloped the capability"
    )

    assert calls["provider"] == 0, (
        "second same-class request acquired another provider"
    )

    assert isinstance(
        result,
        cli._CompletedRepositoryExecution,
    ), (
        "verified trusted reuse was not surfaced as completed "
        "repository execution"
    )



def test_mode6_failed_trusted_reuse_does_not_fall_through_to_provider(
    monkeypatch,
    tmp_path,
):
    """
    Once a trusted promoted capability has claimed and attempted this request,
    failed independent verification must terminate this execution attempt.

    Falling through to the provider/adaptive path could execute a side effect
    twice.  Only reused=False may authorize provider fallback.
    """
    from types import SimpleNamespace

    import sophyane.human_conversation_cli as cli
    import sophyane.capability_executors as capability_executors

    workspace = tmp_path.resolve()

    request = (
        "Use the reusable sphy_telemetry.py program "
        "for telemetry.sphy and EXPECTED.txt."
    )

    capability_class = "executable.sphy_telemetry.py"

    # The earlier deterministic capability layer does not claim this mission.
    monkeypatch.setattr(
        capability_executors,
        "execute_deterministic_capability",
        lambda *_args, **_kwargs: None,
    )

    calls = {
        "reuse": 0,
        "provider": 0,
    }

    class FakeController:
        mode6_workspace = workspace
        mode6_trusted_workspaces = {
            capability_class: workspace,
        }

        def execute_or_reuse(
            self,
            *,
            request,
            capability_class,
            execute,
        ):
            calls["reuse"] += 1

            assert capability_class == "executable.sphy_telemetry.py"

            # This result means a stored trusted capability was selected and
            # attempted, but the original outcome did not verify.
            return SimpleNamespace(
                reused=True,
                original_outcome_verified=False,
                evidence={
                    "reuse": "attempted",
                    "verification": "failed",
                },
            )

    controller = FakeController()

    monkeypatch.setattr(
        cli,
        "_mode6_capability_development_controller",
        lambda *, workspace=None: controller,
    )

    # If execution falls through beyond trusted reuse, the provider boundary
    # is reached.  Record that fact without making any real provider request.
    class ProviderFallbackReached(RuntimeError):
        pass

    def forbidden_provider(*args, **kwargs):
        calls["provider"] += 1
        raise ProviderFallbackReached(
            "provider fallback occurred after trusted reuse "
            "had already attempted the request"
        )

    # _execute_repository_request imports create_provider locally from
    # sophyane.main, so patch the defining module.
    import sophyane.main as sophyane_main

    monkeypatch.setattr(
        sophyane_main,
        "create_provider",
        forbidden_provider,
    )

    try:
        result = cli._execute_repository_request(
            request,
            workspace=workspace,
        )
    except ProviderFallbackReached as exc:
        raise AssertionError(
            "trusted promoted capability attempted the request but failed "
            "verification; provider fallback risks duplicate side effects"
        ) from exc

    assert calls["reuse"] == 1

    assert calls["provider"] == 0, (
        "provider was called after a trusted capability had already "
        "attempted the request"
    )

    assert not isinstance(
        result,
        cli._CompletedRepositoryExecution,
    ), (
        "failed trusted reuse must not be reported as completed"
    )

    assert "verification" in str(result).lower(), (
        "failed trusted reuse should return a non-completed failure result "
        "instead of silently starting another executor"
    )


def test_mode6_trusted_promoted_capability_is_not_reused_across_workspaces(
    monkeypatch,
    tmp_path,
):
    """
    Security contract:

    A capability promoted from workspace A must not become reusable authority
    in workspace B merely because both requests map to the same capability
    class.

    On a workspace mismatch, Mode 6 must fall through to its normal provider
    path rather than execute the foreign trusted artifact.  The provider is
    forbidden here only so the test can observe that boundary without making
    a real provider request.
    """
    import sophyane.human_conversation_cli as cli
    from sophyane.failure_driven_capability import (
        InMemoryCapabilityStore,
    )

    workspace_a = (tmp_path / "workspace-a").resolve()
    workspace_b = (tmp_path / "workspace-b").resolve()

    workspace_a.mkdir()
    workspace_b.mkdir()

    program_text = (
        "import sys\n"
        "print('workspace-a-capability')\n"
    )

    # This is the trusted artifact resulting from promotion in workspace A.
    trusted_from_a = {
        "status": "TRUSTED_PROMOTED",
        "provider": "codex_cli",
        "capability_class": "executable.sphy_telemetry.py",
        "files": {
            "sphy_telemetry.py": program_text,
        },
        "fingerprint": "workspace-a-trusted-fingerprint",
    }

    class ReuseResult:
        reused = False
        original_outcome_verified = False

    calls = {
        "execute_or_reuse": 0,
        "execute_foreign": 0,
        "provider": 0,
        "development": 0,
    }

    class SharedController:
        def __init__(self):
            self.store = InMemoryCapabilityStore()
            self.store.put(
                "executable.sphy_telemetry.py",
                trusted_from_a,
            )
            self.mode6_workspace = None

            # This is host-owned controller state established only after
            # trusted promotion in workspace A.  It is deliberately separate
            # from candidate/provider-controlled fields.
            self.mode6_trusted_workspaces = {
                "executable.sphy_telemetry.py": workspace_a,
            }

        def execute_or_reuse(
            self,
            *,
            request,
            capability_class,
            execute=None,
            **kwargs,
        ):
            calls["execute_or_reuse"] += 1

            candidate = self.store.get(capability_class)

            assert candidate is trusted_from_a
            assert self.mode6_workspace == workspace_b

            executor = execute
            if executor is None:
                executor = kwargs.get("execute_original")

            assert callable(executor)

            # The production caller must prevent a trusted artifact from
            # another workspace reaching execution authority.
            calls["execute_foreign"] += 1

            raise AssertionError(
                "foreign workspace trusted capability reached execution"
            )

        def handle_failure(self, **kwargs):
            calls["development"] += 1
            raise AssertionError(
                "cross-workspace isolation test unexpectedly entered "
                "capability development"
            )

    controller = SharedController()

    monkeypatch.setattr(
        cli,
        "_mode6_capability_development_controller",
        lambda *, workspace=None: (
            setattr(
                controller,
                "mode6_workspace",
                (
                    workspace.resolve()
                    if workspace is not None
                    else None
                ),
            )
            or controller
        ),
    )

    # If isolation works, the foreign artifact is treated as unavailable and
    # Mode 6 continues to the ordinary provider path.  Stop there without
    # issuing a real request.
    def provider_boundary(*args, **kwargs):
        calls["provider"] += 1
        raise RuntimeError("EXPECTED_PROVIDER_BOUNDARY")

    monkeypatch.setattr(
        "sophyane.main.create_provider",
        provider_boundary,
    )

    request = (
        "Use the reusable sphy_telemetry.py program on "
        "telemetry.sphy and verify that its output exactly "
        "matches EXPECTED.txt."
    )

    try:
        cli._execute_repository_request(
            request,
            workspace=workspace_b,
        )
    except RuntimeError as exc:
        assert str(exc) == "EXPECTED_PROVIDER_BOUNDARY"
    else:
        raise AssertionError(
            "cross-workspace request unexpectedly completed"
        )

    assert calls["execute_foreign"] == 0, (
        "workspace A's promoted artifact was offered execution authority "
        "inside workspace B"
    )

    assert calls["provider"] == 1, (
        "workspace mismatch did not fall through to the ordinary "
        "provider path"
    )

    assert calls["development"] == 0


def test_mode6_candidate_provider_field_cannot_control_promotion_authority(
    tmp_path,
    monkeypatch,
):
    """
    The provider selected by CodingRouter is host-observed authority evidence.

    A candidate may carry provider metadata for description/debugging, but
    changing candidate['provider'] after the worker returns must never change
    the provider passed to the trusted promotion boundary.
    """
    import sys

    import sophyane.human_conversation_cli as cli
    import sophyane.rsi.coding_provider as coding_provider
    import sophyane.rsi.verification as verification

    workspace = tmp_path.resolve()

    program_text = (
        "from pathlib import Path\n"
        "import sys\n"
        "\n"
        "def main():\n"
        "    lines = Path(sys.argv[1]).read_text().splitlines()\n"
        "    out = []\n"
        "    for line in lines:\n"
        "        if not line or line.startswith('#'):\n"
        "            continue\n"
        "        parts = line.split('|')\n"
        "        name = parts[1]\n"
        "        temp = parts[2].split('=', 1)[1]\n"
        "        load = parts[3].split('=', 1)[1]\n"
        "        load_i = int(load)\n"
        "        temp_f = float(temp)\n"
        "        status = (\n"
        "            'OVERLOAD'\n"
        "            if load_i >= 90\n"
        "            else 'WARNING'\n"
        "            if temp_f >= 40\n"
        "            else 'NORMAL'\n"
        "        )\n"
        "        out.append(f'{name},{temp},{load},{status}')\n"
        "    print('\\n'.join(out))\n"
        "\n"
        "if __name__ == '__main__':\n"
        "    main()\n"
    )

    (workspace / "telemetry.sphy").write_text(
        "# SPHY-Telemetry v1\n"
        "NODE|alpha|TEMP=41.5|LOAD=72\n"
        "NODE|beta|TEMP=38.0|LOAD=91\n"
        "NODE|gamma|TEMP=44.5|LOAD=63\n"
    )

    (workspace / "EXPECTED.txt").write_text(
        "alpha,41.5,72,WARNING\n"
        "beta,38.0,91,OVERLOAD\n"
        "gamma,44.5,63,WARNING\n"
    )

    request = (
        "Create reusable sphy_telemetry.py to process telemetry.sphy "
        "and verify that its output exactly matches EXPECTED.txt."
    )

    class FakeRouter:
        def __init__(self, *args, **kwargs):
            pass

        def request(self, *args, **kwargs):
            # This is the provider identity actually observed by the
            # host-side CodingRouter boundary.
            return coding_provider.CodingResult(
                status="SUCCESS",
                provider="codex_cli",
                files={
                    "sphy_telemetry.py": program_text,
                },
                failovers=(),
            )

    monkeypatch.setattr(
        coding_provider,
        "CodingRouter",
        FakeRouter,
    )

    # Android/Termux does not provide the production Bubblewrap sandbox.
    # This patch is test-only and exercises the verifier semantics without
    # weakening production's fail-closed sandbox policy.
    monkeypatch.setattr(
        verification,
        "sandbox_command",
        lambda command, workspace, timeout=60: tuple(command),
    )

    monkeypatch.setattr(
        cli,
        "_mode6_failure_driven_controller",
        None,
    )

    controller = cli._mode6_capability_development_controller(
        workspace=workspace,
    )

    context = {
        "request": request,
        "failure": {
            "kind": "missing_executable",
            "executable": "sphy_telemetry.py",
        },
        "classification": "missing_reusable_capability",
        "capability_class": "executable.sphy_telemetry.py",
        "attempt": 1,
    }

    candidate = controller.worker(
        "implementation",
        context,
    )

    assert candidate["status"] == "SUCCESS"
    assert candidate["provider"] == "codex_cli"
    assert candidate["files"] == {
        "sphy_telemetry.py": program_text,
    }

    # CodingRouter supplied codex_cli at the host/provider boundary.
    # Mutate only the candidate-carried copy before independent verification.
    # The implementation bytes remain exactly those returned by CodingRouter.
    candidate["provider"] = "nifdu_browser"

    assert candidate["files"] == {
        "sphy_telemetry.py": program_text,
    }

    # Provider identity is authority-bearing metadata.  Independent
    # verification must not accept a provider identity supplied solely by
    # the mutable candidate object.  It must be bound to host-observed
    # CodingRouter provenance.
    assert controller.verifier(candidate, request) is False


def test_mode6_reusable_executable_classifier_is_fail_closed():
    """
    Trusted promoted reuse is an authority-bearing shortcut.

    It must require explicit reusable-capability intent and exactly one safe
    Python basename.  Ordinary execution, creation, paths, traversal, and
    ambiguous program references must not select a trusted capability.
    """
    import sophyane.human_conversation_cli as cli

    classify = cli._mode6_reusable_executable_capability_class

    cases = (
        (
            "Use the reusable foo.py program for this request.",
            "executable.foo.py",
        ),
        (
            "Run the reusable `foo.py` capability now.",
            "executable.foo.py",
        ),
        (
            "Execute reusable parser_v2.py for the input.",
            "executable.parser_v2.py",
        ),

        # No explicit reusable-capability intent.
        (
            "Run foo.py for the input.",
            None,
        ),
        (
            "Execute foo.py now.",
            None,
        ),

        # Creation/implementation is development intent, not reuse.
        (
            "Create reusable foo.py for this request.",
            None,
        ),
        (
            "Implement reusable foo.py for this request.",
            None,
        ),

        # Paths and traversal must never become trusted capability classes.
        (
            "Use the reusable ../foo.py program.",
            None,
        ),
        (
            "Use the reusable sub/foo.py program.",
            None,
        ),
        (
            "Use the reusable ./foo.py program.",
            None,
        ),
        (
            r"Use the reusable sub\foo.py program.",
            None,
        ),

        # More than one candidate is ambiguous.
        (
            "Use the reusable foo.py or bar.py program.",
            None,
        ),
        (
            "Run reusable foo.py with bar.py.",
            None,
        ),
    )

    observed = []

    for request, expected in cases:
        actual = classify(request)
        observed.append((request, expected, actual))
        assert actual == expected, (
            f"classifier authority mismatch for {request!r}: "
            f"expected {expected!r}, got {actual!r}"
        )

    # Positive result is always a bounded capability class, never a path.
    for _request, _expected, actual in observed:
        if actual is None:
            continue

        assert actual.startswith("executable.")
        basename = actual.removeprefix("executable.")

        assert basename.endswith(".py")
        assert "/" not in basename
        assert "\\" not in basename
        assert ".." not in basename



def test_mode6_sandbox_unavailable_is_truthful_environmental_restriction(
    monkeypatch,
    tmp_path,
):
    """Missing OS isolation must never become successful RSI development."""
    import sophyane.human_conversation_cli as cli
    from sophyane.failure_driven_capability import FailureClassification
    from sophyane.rsi.sandbox import SandboxUnavailable

    workspace = tmp_path / "workspace"
    workspace.mkdir()

    (workspace / "input.sphy").write_text(
        "NODE|alpha|TEMP=41.5|LOAD=72\n"
    )
    (workspace / "EXPECTED.txt").write_text(
        "alpha,41.5,72,WARNING\n"
    )

    candidate = {
        "status": "SUCCESS",
        "provider": "codex_cli",
        "files": {
            "fresh_parser.py": (
                "print('alpha,41.5,72,WARNING')\n"
            ),
        },
    }

    controller = cli._mode6_capability_development_controller(
        workspace=workspace,
    )

    original_worker = controller.worker
    original_verifier = controller.verifier

    calls = {
        "worker": 0,
        "verifier": 0,
        "promoter": 0,
        "retry": 0,
    }

    def worker(role, request):
        calls["worker"] += 1
        if role == "implementation":
            return candidate
        return original_worker(role, request)

    def unavailable_verifier(candidate_arg, request):
        calls["verifier"] += 1
        raise SandboxUnavailable(
            "RSI requires an OS-enforced sandbox"
        )

    def forbidden_promoter(*args, **kwargs):
        calls["promoter"] += 1
        raise AssertionError(
            "sandbox-unavailable candidate must not promote"
        )

    def forbidden_retry(*args, **kwargs):
        calls["retry"] += 1
        raise AssertionError(
            "sandbox-unavailable candidate must not retry"
        )

    controller.worker = worker
    controller.verifier = unavailable_verifier
    controller.promoter = forbidden_promoter

    try:
        result = controller.handle_failure(
            request=(
                "Use a reusable fresh_parser.py capability "
                "for input.sphy and verify against EXPECTED.txt."
            ),
            failure={
                "classification": "missing_reusable_capability",
                "error": "executable does not exist: fresh_parser.py",
            },
            classification=(
                FailureClassification.MISSING_REUSABLE_CAPABILITY
            ),
            capability_class="executable.fresh_parser.py",
            execute_original=forbidden_retry,
        )
    finally:
        controller.worker = original_worker
        controller.verifier = original_verifier

    assert result.accepted is False
    assert result.retry_original_request is False

    assert calls["worker"] >= 1
    assert calls["verifier"] == 1
    assert calls["promoter"] == 0
    assert calls["retry"] == 0

    evidence = result.evidence

    assert evidence.get("classification") == (
        "infeasible_environmental_restriction"
    )
    assert evidence.get("environmental_restriction") is True
    assert evidence.get("sandbox_unavailable") is True
