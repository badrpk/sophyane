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
        ) or "EXECUTION_EVIDENCE",
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
        lambda text: FakeTurn(),
    )

    assert cli.main() == 0

    output = capsys.readouterr().out

    assert "CHAT_REPLY" in output


def test_interactive_execution_result_is_printed_directly(
    monkeypatch,
    capsys,
):
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

    execution_calls = []

    monkeypatch.setattr(
        cli,
        "_execute_repository_request",
        lambda text: execution_calls.append(
            text
        ) or "DIRECT_EXECUTION_RESULT",
    )

    def forbidden_conversation_turn(*args, **kwargs):
        raise AssertionError(
            "execution result was conversationally paraphrased"
        )

    monkeypatch.setattr(
        cli,
        "conversation_turn",
        forbidden_conversation_turn,
    )

    assert cli.main() == 0

    output = capsys.readouterr().out

    assert execution_calls == [
        "Patch src/example.py."
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
        lambda text: FakeTurn(),
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

    execution_calls = []

    monkeypatch.setattr(
        cli,
        "_execute_repository_request",
        lambda text: execution_calls.append(
            text
        ) or "VOICE_EXECUTION_RESULT",
    )

    def forbidden_conversation_turn(*args, **kwargs):
        raise AssertionError(
            "voice execution transcript fell through to conversation"
        )

    monkeypatch.setattr(
        cli,
        "conversation_turn",
        forbidden_conversation_turn,
    )

    assert cli.main() == 0

    output = capsys.readouterr().out

    assert execution_calls == [
        "Patch src/example.py."
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
        lambda text: FakeTurn(),
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

    execution_calls = []

    def fake_execute(text, *, workspace=None):
        execution_calls.append(text)

        if len(execution_calls) == 1:
            return "What content should I put inside yaad.py?"

        if len(execution_calls) == 2:
            return "Need photo source."

        return "YAAD_COMPLETE"

    monkeypatch.setattr(
        cli,
        "_execute_repository_request",
        fake_execute,
    )

    def forbidden_chat(*args, **kwargs):
        raise AssertionError(
            "active execution follow-up fell through to conversation_turn"
        )

    monkeypatch.setattr(
        cli,
        "conversation_turn",
        forbidden_chat,
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
        lambda text: FakeTurn(),
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
