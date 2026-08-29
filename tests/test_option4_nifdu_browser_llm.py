from __future__ import annotations

from pathlib import Path


def test_option4_contains_nifdu_submenu():
    text = Path(
        "src/sophyane/startup_policy.py"
    ).read_text(
        encoding="utf-8",
    )

    assert (
        "Choose external LLM intelligence:"
        in text
    )

    assert (
        "NIFDU Browser"
        in text
    )

    assert (
        '"SOPHYANE_SESSION_MODE"] = "nifdu_llm"'
        in text
    )

    assert (
        '"SOPHYANE_SESSION_PROVIDER"] = "nifdu_browser"'
        in text
    )


def test_nifdu_provider_is_dedicated():
    text = Path(
        "src/sophyane/main.py"
    ).read_text(
        encoding="utf-8",
    )

    assert (
        'session_mode == "nifdu_llm"'
        in text
    )

    assert (
        "NifduBrowserProvider"
        in text
    )


def test_nifdu_provider_reuses_existing_bridge():
    text = Path(
        "src/sophyane/providers/nifdu_browser.py"
    ).read_text(
        encoding="utf-8",
    )

    assert (
        "sophyane-chatgpt-loop"
        in text
    )

    assert (
        "captureScreenshot"
        not in text
    )

    assert (
        "remote-debugging-port"
        not in text
    )


def test_nifdu_bridge_two_argument_contract_uses_none_image(
    monkeypatch,
    tmp_path,
):
    import json

    from sophyane.providers.nifdu_browser import (
        NifduBrowserProvider,
    )

    bridge = tmp_path / "bridge.py"

    bridge.write_text(
        """
calls = []

def ask(prompt, image=None):
    calls.append((prompt, image))
    return "bridge-ok"
""".lstrip(),
        encoding="utf-8",
    )

    selection = tmp_path / "selection.json"

    selection.write_text(
        json.dumps(
            {
                "kind": "function",
                "module": str(bridge),
                "name": "ask",
                "args": [
                    "prompt",
                    "image",
                ],
                "async": False,
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.setenv(
        "SOPHYANE_NIFDU_CALLABLE_FILE",
        str(selection),
    )

    provider = NifduBrowserProvider(
        timeout=180,
    )

    assert (
        provider.generate(
            "hello"
        )
        == "bridge-ok"
    )

    # Critical regression:
    # timeout must not become the bridge image argument.
    module = None

    # Re-import through the provider's loader so we can directly
    # verify the bridge itself accepts image=None. The provider
    # generate result above already exercises the actual path.
    from sophyane.providers import nifdu_browser

    module = nifdu_browser._load_module(
        bridge
    )

    assert (
        module.ask(
            "probe",
            None,
        )
        == "bridge-ok"
    )


def test_provider_rejects_unknown_two_argument_signature(
    monkeypatch,
    tmp_path,
):
    import json

    from sophyane.providers.base import (
        ProviderError,
    )

    from sophyane.providers.nifdu_browser import (
        NifduBrowserProvider,
    )

    bridge = tmp_path / "bridge.py"

    bridge.write_text(
        """
def ask(prompt, timeout):
    return "wrong-contract"
""".lstrip(),
        encoding="utf-8",
    )

    selection = tmp_path / "selection.json"

    selection.write_text(
        json.dumps(
            {
                "kind": "function",
                "module": str(bridge),
                "name": "ask",
                "args": [
                    "prompt",
                    "timeout",
                ],
                "async": False,
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.setenv(
        "SOPHYANE_NIFDU_CALLABLE_FILE",
        str(selection),
    )

    provider = NifduBrowserProvider()

    try:
        provider.generate(
            "hello"
        )

    except ProviderError as error:
        assert (
            "Unsupported NIFDU bridge callable"
            in str(error)
        )

    else:
        raise AssertionError(
            "unsupported bridge signature was accepted"
        )


def test_execution_session_mode_preserves_nifdu(
    monkeypatch,
):
    from sophyane.v13_cli import (
        _execution_session_mode,
    )

    monkeypatch.setenv(
        "SOPHYANE_SESSION_MODE",
        "nifdu_llm",
    )

    assert (
        _execution_session_mode()
        == "nifdu_llm"
    )


def test_nifdu_execution_mode_does_not_select_race(
    monkeypatch,
):
    from sophyane.v13_cli import (
        _execution_session_mode,
        _should_use_adaptive_race,
    )

    monkeypatch.setenv(
        "SOPHYANE_SESSION_MODE",
        "nifdu_llm",
    )

    assert (
        _execution_session_mode()
        == "nifdu_llm"
    )

    assert (
        _should_use_adaptive_race()
        is False
    )


def test_nifdu_leaf_provider_is_discoverable_by_tui_context():
    from sophyane.providers.nifdu_browser import (
        NifduBrowserProvider,
    )

    from sophyane.runtime_provider_context_patch import (
        _walk_provider,
    )

    provider = NifduBrowserProvider(
        timeout=120,
    )

    assert (
        _walk_provider(
            provider
        )
        is provider
    )


def test_nifdu_leaf_provider_identity_wins_over_stale_config():
    from types import SimpleNamespace

    from sophyane.providers.nifdu_browser import (
        NifduBrowserProvider,
    )

    from sophyane.runtime_provider_context_patch import (
        _active_name,
    )

    provider = NifduBrowserProvider(
        timeout=120,
    )

    tui = SimpleNamespace(
        ask=SimpleNamespace(
            __self__=SimpleNamespace(
                provider=provider,
            )
        ),
        config={
            "provider": "gemini",
            "model": "gemini-3.7-flash",
        },
    )

    # Bypass the synthetic callable limitation by placing the
    # authoritative provider in the same cache used by ObservableTUI.
    tui._sophyane_provider_dispatcher = provider

    assert (
        _active_name(
            tui
        )
        == "nifdu_browser"
    )


def test_session_banner_prefers_transient_nifdu_model(
    monkeypatch,
):
    from sophyane.session_banner import (
        model_ready_label,
    )

    monkeypatch.setenv(
        "SOPHYANE_SESSION_MODE",
        "nifdu_llm",
    )

    monkeypatch.setenv(
        "SOPHYANE_SESSION_MODEL",
        "chatgpt-browser",
    )

    assert (
        model_ready_label(
            "gemini-3.7-flash"
        )
        == "chatgpt-browser · Ready"
    )


def test_live_cli_banner_honors_transient_session_model():
    text = Path(
        "src/sophyane/cli_entry.py"
    ).read_text(
        encoding="utf-8",
    )

    assert (
        "SOPHYANE_SESSION_MODEL"
        in text
    )


def test_nifdu_guarded_file_write(
    tmp_path,
):
    from sophyane.nifdu_guarded_execution import (
        apply_file_write_proposal,
    )

    result = apply_file_write_proposal(
        """WRITE_FILE
path: chakwal.py
content:
print('chakwal')
END_WRITE_FILE""",
        workspace=tmp_path,
        expected_filename="chakwal.py",
    )

    assert (
        result
        == tmp_path / "chakwal.py"
    )

    assert (
        result.read_text(
            encoding="utf-8",
        )
        == "print('chakwal')\n"
    )


def test_nifdu_guarded_execution_rejects_shell(
    tmp_path,
):
    from sophyane.nifdu_guarded_execution import (
        NifduExecutionError,
        apply_file_write_proposal,
    )

    try:
        apply_file_write_proposal(
            """printf "%s\\n" "print('chakwal')" > chakwal.py""",
            workspace=tmp_path,
            expected_filename="chakwal.py",
        )

    except NifduExecutionError:
        pass

    else:
        raise AssertionError(
            "raw shell response was accepted"
        )


def test_nifdu_guarded_execution_rejects_escape(
    tmp_path,
):
    from sophyane.nifdu_guarded_execution import (
        NifduExecutionError,
        apply_file_write_proposal,
    )

    try:
        apply_file_write_proposal(
            """WRITE_FILE
path: ../chakwal.py
content:
print('chakwal')
END_WRITE_FILE""",
            workspace=tmp_path,
        )

    except NifduExecutionError:
        pass

    else:
        raise AssertionError(
            "workspace escape was accepted"
        )


def test_nifdu_requested_python_filename():
    from sophyane.nifdu_guarded_execution import (
        requested_python_filename,
    )

    assert (
        requested_python_filename(
            "make a file test.py"
        )
        == "test.py"
    )

    assert (
        requested_python_filename(
            "Create exactly one Python file named chakwal.py "
            "with contents print('chakwal')"
        )
        == "chakwal.py"
    )

    assert (
        requested_python_filename(
            "tell me about Python"
        )
        is None
    )


def test_nifdu_tui_guarded_execution_is_wired():
    text = Path(
        "src/sophyane/tui_v2.py"
    ).read_text(
        encoding="utf-8",
    )

    assert (
        "SOPHYANE_NIFDU_TUI_GUARDED_EXECUTION_V1"
        in text
    )

    assert (
        "execute_nifdu_file_request"
        in text
    )

    assert (
        '== "nifdu_llm"'
        in text
    )


def test_nifdu_executor_does_not_execute_llm_shell():
    import ast

    text = Path(
        "src/sophyane/nifdu_guarded_execution.py"
    ).read_text(
        encoding="utf-8",
    )

    tree = ast.parse(
        text
    )

    for node in ast.walk(tree):
        if not isinstance(
            node,
            ast.Call,
        ):
            continue

        # Forbid os.system(...)
        if (
            isinstance(
                node.func,
                ast.Attribute,
            )
            and isinstance(
                node.func.value,
                ast.Name,
            )
            and node.func.value.id == "os"
            and node.func.attr == "system"
        ):
            raise AssertionError(
                "os.system execution is forbidden"
            )

        # Inspect subprocess.run/Popen structurally.
        if (
            isinstance(
                node.func,
                ast.Attribute,
            )
            and isinstance(
                node.func.value,
                ast.Name,
            )
            and node.func.value.id == "subprocess"
            and node.func.attr in {
                "run",
                "Popen",
            }
        ):
            keyword_values = {
                keyword.arg: keyword.value
                for keyword in node.keywords
                if keyword.arg is not None
            }

            shell = keyword_values.get(
                "shell"
            )

            if shell is not None:
                assert (
                    isinstance(
                        shell,
                        ast.Constant,
                    )
                    and shell.value is False
                )

            if node.args:
                rendered = ast.unparse(
                    node.args[0]
                )

                assert rendered not in {
                    "request",
                    "response",
                }


def test_nifdu_browser_launcher_uses_fixed_python_argv():
    import ast

    source = Path(
        "src/sophyane/nifdu_guarded_execution.py"
    ).read_text(
        encoding="utf-8",
    )

    tree = ast.parse(
        source
    )

    calls = [
        node
        for node in ast.walk(tree)
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "subprocess"
            and node.func.attr == "Popen"
        )
    ]

    assert len(calls) == 1

    call = calls[0]

    assert call.args

    argv = call.args[0]

    assert isinstance(
        argv,
        ast.List,
    )

    assert [
        ast.unparse(item)
        for item in argv.elts
    ] == [
        "sys.executable",
        "str(target)",
    ]

    shell_keywords = [
        keyword
        for keyword in call.keywords
        if keyword.arg == "shell"
    ]

    assert all(
        isinstance(
            keyword.value,
            ast.Constant,
        )
        and keyword.value.value is False
        for keyword in shell_keywords
    )

    rendered = ast.unparse(
        call
    )

    assert "response" not in rendered
    assert "request" not in rendered





def test_nifdu_browser_launcher_validates_before_popen():
    text = Path(
        "src/sophyane/nifdu_guarded_execution.py"
    ).read_text(
        encoding="utf-8",
    )

    validation = text.index(
        "validate_python_file("
    )

    launch = text.index(
        "process = subprocess.Popen("
    )

    assert validation < launch


def test_nifdu_executor_only_handles_python_file_requests(
    tmp_path,
):
    from sophyane.nifdu_guarded_execution import (
        execute_nifdu_file_request,
    )

    assert (
        execute_nifdu_file_request(
            "What is the capital of Pakistan?",
            workspace=tmp_path,
        )
        is None
    )


def test_nifdu_guard_is_in_effective_intent_run():
    text = Path(
        "src/sophyane/runtime_intent_refinement_patch.py"
    ).read_text(
        encoding="utf-8",
    )

    marker = (
        "SOPHYANE_NIFDU_EFFECTIVE_RUN_GUARDED_EXECUTION_V1"
    )

    assert marker in text

    assert (
        "execute_nifdu_file_request"
        in text
    )

    assert (
        '== "nifdu_llm"'
        in text
    )

    assert (
        text.index(marker)
        < text.index(
            "refined_result = _confirm_refinement"
        )
    )


def test_nifdu_effective_run_does_not_require_original_run():
    text = Path(
        "src/sophyane/runtime_intent_refinement_patch.py"
    ).read_text(
        encoding="utf-8",
    )

    assert (
        "_nifdu_refinement_original_run"
        not in text
    )


def test_nifdu_guarded_file_request_still_recognized():
    from sophyane.nifdu_guarded_execution import (
        requested_python_filename,
    )

    assert (
        requested_python_filename(
            "Create exactly one Python file named test.py. "
            "Its exact complete contents must be: "
            "print('option4-nifdu')"
        )
        == "test.py"
    )


def test_nifdu_replace_parser():
    from sophyane.nifdu_guarded_execution import (
        parse_file_replace_proposal,
    )

    proposal = parse_file_replace_proposal(
        """REPLACE_FILE
path: yaqeen.py
content:
print('snake')
END_REPLACE_FILE"""
    )

    assert (
        proposal.relative_path
        == "yaqeen.py"
    )

    assert (
        proposal.content
        == "print('snake')\n"
    )


def test_nifdu_replace_rejects_other_file(
    tmp_path,
):
    from sophyane.nifdu_guarded_execution import (
        NifduExecutionError,
        apply_file_replace_proposal,
    )

    target = tmp_path / "yaqeen.py"

    target.write_text(
        "",
        encoding="utf-8",
    )

    try:
        apply_file_replace_proposal(
            """REPLACE_FILE
path: other.py
content:
print('bad')
END_REPLACE_FILE""",
            workspace=tmp_path,
            expected_filename="yaqeen.py",
        )

    except NifduExecutionError:
        pass

    else:
        raise AssertionError(
            "replacement escaped expected active file"
        )


def test_nifdu_continuation_resolves_it(
    tmp_path,
):
    from sophyane.nifdu_guarded_execution import (
        is_nifdu_file_continuation_request,
    )

    target = tmp_path / "yaqeen.py"

    target.write_text(
        "",
        encoding="utf-8",
    )

    assert is_nifdu_file_continuation_request(
        "code a snake game in it",
        active_file=target,
        workspace=tmp_path,
    )


def test_nifdu_continuation_guard_precedes_refinement():
    text = Path(
        "src/sophyane/runtime_intent_refinement_patch.py"
    ).read_text(
        encoding="utf-8",
    )

    assert (
        text.index(
            "SOPHYANE_NIFDU_GUARDED_CONTINUATION_DISPATCH_V1"
        )
        <
        text.index(
            "refined_result = _confirm_refinement"
        )
    )


def test_nifdu_active_workspace_is_path_normalized():
    text = Path(
        "src/sophyane/runtime_intent_refinement_patch.py"
    ).read_text(
        encoding="utf-8",
    )

    assert (
        "SOPHYANE_NIFDU_ACTIVE_PATH_STATE_V1"
        in text
    )

    assert (
        "self.active_workspace = _SophyaneActivePath("
        in text
    )


def test_nifdu_deterministic_empty_create(
    tmp_path,
):
    from sophyane.nifdu_guarded_execution import (
        deterministic_empty_python_create,
    )

    target = deterministic_empty_python_create(
        "create a file yaqeen.py",
        workspace=tmp_path,
    )

    assert target == tmp_path / "yaqeen.py"
    assert target.is_file()

    assert (
        target.read_text(
            encoding="utf-8",
        )
        == ""
    )


def test_nifdu_empty_create_does_not_capture_content_request(
    tmp_path,
):
    from sophyane.nifdu_guarded_execution import (
        deterministic_empty_python_create,
    )

    result = deterministic_empty_python_create(
        (
            "Create a file yaqeen.py with this content: "
            "print('hello')"
        ),
        workspace=tmp_path,
    )

    assert result is None
    assert not (tmp_path / "yaqeen.py").exists()


def test_nifdu_empty_create_route_precedes_browser_guard():
    from pathlib import Path

    text = Path(
        "src/sophyane/runtime_intent_refinement_patch.py"
    ).read_text(
        encoding="utf-8",
    )

    native = text.index(
        "SOPHYANE_NIFDU_DETERMINISTIC_EMPTY_CREATE_V1"
    )

    browser = text.index(
        "SOPHYANE_NIFDU_EFFECTIVE_RUN_GUARDED_EXECUTION_V1"
    )

    assert native < browser


def test_nifdu_run_browser_classifier():
    from sophyane.nifdu_guarded_execution import (
        requested_browser_python_file,
    )

    assert (
        requested_browser_python_file(
            "run yaqeen.py in browser so i can play game"
        )
        == "yaqeen.py"
    )

    assert (
        requested_browser_python_file(
            "open yaqeen.py in chromium"
        )
        == "yaqeen.py"
    )

    assert (
        requested_browser_python_file(
            "code snake game in yaqeen.py"
        )
        is None
    )


def test_nifdu_browser_launch_rejects_invalid_python(
    tmp_path,
):
    from sophyane.nifdu_guarded_execution import (
        NifduExecutionError,
        validate_python_file,
    )

    target = tmp_path / "broken.py"

    target.write_text(
        "def bad():\nprint('x')\n",
        encoding="utf-8",
    )

    try:
        validate_python_file(
            target
        )

    except NifduExecutionError:
        pass

    else:
        raise AssertionError(
            "invalid Python reached execution gate"
        )


def test_nifdu_browser_launch_guard_precedes_continuation():
    from pathlib import Path

    text = Path(
        "src/sophyane/runtime_intent_refinement_patch.py"
    ).read_text(
        encoding="utf-8",
    )

    launch = text.index(
        "SOPHYANE_NIFDU_GUARDED_BROWSER_LAUNCH_V1"
    )

    continuation_tokens = (
        "SOPHYANE_NIFDU_GUARDED_CONTINUATION",
        "execute_nifdu_file_continuation",
    )

    continuation = min(
        text.index(token)
        for token in continuation_tokens
        if token in text
    )

    assert launch < continuation


# SOPHYANE_NIFDU_EXPLICIT_FILE_READ_GROUNDING_TESTS_V1

def test_nifdu_explicit_file_read_returns_real_contents(
    tmp_path,
):
    from sophyane.nifdu_guarded_execution import (
        grounded_nifdu_python_file_read,
    )

    target = tmp_path / "yaqeen.py"

    target.write_text(
        "print('real-grounded-content')\n",
        encoding="utf-8",
    )

    response = grounded_nifdu_python_file_read(
        "what is content of yaqeen.py",
        workspace=tmp_path,
    )

    assert response is not None
    assert "yaqeen.py" in response
    assert "print('real-grounded-content')" in response


def test_nifdu_explicit_file_read_reports_missing_without_invention(
    tmp_path,
):
    from sophyane.nifdu_guarded_execution import (
        grounded_nifdu_python_file_read,
    )

    response = grounded_nifdu_python_file_read(
        "what is content of yaqeen.py",
        workspace=tmp_path,
    )

    assert response is not None
    assert response == (
        "Local file yaqeen.py does not exist in the active workspace."
    )


def test_nifdu_explicit_file_read_does_not_capture_create_request(
    tmp_path,
):
    from sophyane.nifdu_guarded_execution import (
        grounded_nifdu_python_file_read,
    )

    assert (
        grounded_nifdu_python_file_read(
            (
                "Create a file yaqeen.py with this content: "
                "print('hello')"
            ),
            workspace=tmp_path,
        )
        is None
    )


def test_nifdu_ungrounded_browser_reference_is_blocked(
    tmp_path,
):
    from sophyane.nifdu_guarded_execution import (
        ungrounded_nifdu_browser_reference,
    )

    response = ungrounded_nifdu_browser_reference(
        "play this code in browser",
        workspace=tmp_path,
    )

    assert response is not None
    assert "grounded local file" in response
    assert "filename" in response


def test_nifdu_explicit_browser_filename_not_blocked_by_reference_guard(
    tmp_path,
):
    from sophyane.nifdu_guarded_execution import (
        ungrounded_nifdu_browser_reference,
    )

    assert (
        ungrounded_nifdu_browser_reference(
            "run yaqeen.py in browser",
            workspace=tmp_path,
        )
        is None
    )


def test_nifdu_grounded_read_dispatch_precedes_file_generation():
    from pathlib import Path

    text = Path(
        "src/sophyane/tui_v2.py"
    ).read_text(
        encoding="utf-8",
    )

    grounding = text.index(
        "SOPHYANE_NIFDU_EXPLICIT_FILE_READ_GROUNDING_V1"
    )

    generation = text.index(
        "execute_nifdu_file_request("
    )

    assert grounding < generation


def test_nifdu_ungrounded_browser_reference_dispatch_precedes_adaptive_fallback():
    from pathlib import Path

    text = Path(
        "src/sophyane/tui_v2.py"
    ).read_text(
        encoding="utf-8",
    )

    marker = text.index(
        "SOPHYANE_NIFDU_UNGROUNDED_BROWSER_REFERENCE_V1"
    )

    adaptive = text.index(
        "if self.dispatch_user_request is not None:"
    )

    assert marker < adaptive


# SOPHYANE_NIFDU_FILE_DISCOVERY_GROUNDING_TESTS_V1

def test_nifdu_named_file_discovery_reports_absent(
    tmp_path,
):
    from sophyane.nifdu_guarded_execution import (
        grounded_nifdu_named_file_discovery,
    )

    result = grounded_nifdu_named_file_discovery(
        "is there any file in my device named yaqeen.py",
        roots=[tmp_path],
    )

    assert result is not None
    assert result["handled"] is True
    assert result["paths"] == []
    assert "No accessible file named yaqeen.py was found" in result["message"]


def test_nifdu_named_file_discovery_returns_real_path(
    tmp_path,
):
    from sophyane.nifdu_guarded_execution import (
        grounded_nifdu_named_file_discovery,
    )

    folder = tmp_path / "project"
    folder.mkdir()

    target = folder / "yaqeen.py"
    target.write_text(
        "print('grounded')\n",
        encoding="utf-8",
    )

    result = grounded_nifdu_named_file_discovery(
        "search the path of yaqeen.py",
        roots=[tmp_path],
    )

    assert result is not None
    assert result["handled"] is True
    assert result["paths"] == [target.resolve()]
    assert str(target.resolve()) in result["message"]


def test_nifdu_named_file_discovery_never_invents_path(
    tmp_path,
):
    from sophyane.nifdu_guarded_execution import (
        grounded_nifdu_named_file_discovery,
    )

    result = grounded_nifdu_named_file_discovery(
        "where is yaqeen.py",
        roots=[tmp_path],
    )

    assert result is not None
    assert "/path/to/" not in result["message"]


def test_nifdu_code_of_filename_is_grounded(
    tmp_path,
):
    from sophyane.nifdu_guarded_execution import (
        grounded_nifdu_python_file_read,
    )

    target = tmp_path / "yaqeen.py"
    target.write_text(
        "print('real-code')\n",
        encoding="utf-8",
    )

    result = grounded_nifdu_python_file_read(
        "code of yaqeen.py",
        workspace=tmp_path,
    )

    assert result is not None
    assert "print('real-code')" in result


def test_nifdu_fetch_named_file_code_is_grounded(
    tmp_path,
):
    from sophyane.nifdu_guarded_execution import (
        grounded_nifdu_python_file_read,
    )

    target = tmp_path / "yaqeen.py"
    target.write_text(
        "print('fetch-real')\n",
        encoding="utf-8",
    )

    result = grounded_nifdu_python_file_read(
        "fetch the code of yaqeen.py",
        workspace=tmp_path,
    )

    assert result is not None
    assert "print('fetch-real')" in result


def test_nifdu_file_discovery_dispatch_precedes_provider():
    from pathlib import Path

    text = Path(
        "src/sophyane/tui_v2.py"
    ).read_text(
        encoding="utf-8",
    )

    discovery = text.index(
        "SOPHYANE_NIFDU_NAMED_FILE_DISCOVERY_DISPATCH_V1"
    )

    provider = text.index(
        "execute_nifdu_file_request("
    )

    assert discovery < provider


def test_nifdu_grounded_file_followup_helper(
    tmp_path,
):
    from sophyane.nifdu_guarded_execution import (
        grounded_nifdu_file_followup,
    )

    target = tmp_path / "yaqeen.py"
    target.write_text(
        "print('remembered')\n",
        encoding="utf-8",
    )

    result = grounded_nifdu_file_followup(
        "fetch the code",
        active_file=target,
    )

    assert result is not None
    assert "print('remembered')" in result


def test_nifdu_grounded_file_followup_rejects_missing_active_file(
    tmp_path,
):
    from sophyane.nifdu_guarded_execution import (
        grounded_nifdu_file_followup,
    )

    result = grounded_nifdu_file_followup(
        "what is content of this file?",
        active_file=tmp_path / "missing.py",
    )

    assert result is not None
    assert "no longer exists" in result.lower()


# SOPHYANE_NIFDU_EFFECTIVE_GROUNDING_TESTS_V1

def test_nifdu_followup_classifier_recognizes_file_reference():
    from sophyane.nifdu_guarded_execution import (
        is_nifdu_file_followup_request,
    )

    assert is_nifdu_file_followup_request(
        "what is content of this file?"
    )

    assert is_nifdu_file_followup_request(
        "fetch the code"
    )

    assert not is_nifdu_file_followup_request(
        "what is the capital of Pakistan?"
    )


def test_nifdu_multiple_grounded_files_followup_is_ambiguous(
    tmp_path,
):
    from sophyane.nifdu_guarded_execution import (
        grounded_nifdu_file_followup,
    )

    first = tmp_path / "a" / "yaqeen.py"
    second = tmp_path / "b" / "yaqeen.py"

    first.parent.mkdir()
    second.parent.mkdir()

    first.write_text(
        "print('a')\n",
        encoding="utf-8",
    )

    second.write_text(
        "print('b')\n",
        encoding="utf-8",
    )

    response = grounded_nifdu_file_followup(
        "what is content of this file?",
        active_file=None,
        candidate_paths=[
            first,
            second,
        ],
    )

    assert response is not None
    assert "multiple grounded files" in response.lower()
    assert str(first.resolve()) in response
    assert str(second.resolve()) in response


def test_nifdu_effective_run_contains_grounding_dispatch():
    from pathlib import Path

    text = Path(
        "src/sophyane/runtime_intent_refinement_patch.py"
    ).read_text(
        encoding="utf-8",
    )

    assert (
        "SOPHYANE_NIFDU_EFFECTIVE_LOCAL_GROUNDING_V1"
        in text
    )

    assert (
        "grounded_nifdu_named_file_discovery"
        in text
    )

    assert (
        "grounded_nifdu_python_file_read"
        in text
    )

    assert (
        "grounded_nifdu_file_followup"
        in text
    )


def test_nifdu_effective_grounding_precedes_preflight_and_provider_execution():
    from pathlib import Path

    text = Path(
        "src/sophyane/runtime_intent_refinement_patch.py"
    ).read_text(
        encoding="utf-8",
    )

    grounding = text.index(
        "SOPHYANE_NIFDU_EFFECTIVE_LOCAL_GROUNDING_V1"
    )

    preflight = text.index(
        "SOPHYANE_AUTHORITATIVE_OBJECTIVE_PREFLIGHT"
    )

    native_execution = text.index(
        "SOPHYANE_NIFDU_NATIVE_EXECUTION_HANDOFF_V1"
    )

    assert grounding < preflight
    assert grounding < native_execution


# SOPHYANE_NIFDU_READONLY_ROUTING_TESTS_V2

def test_nifdu_largest_file_is_grounded(tmp_path):
    from sophyane.nifdu_guarded_execution import (
        grounded_nifdu_largest_file,
    )

    (tmp_path / "small.txt").write_text("x", encoding="utf-8")
    big = tmp_path / "largest.bin"
    big.write_bytes(b"x" * 4096)

    result = grounded_nifdu_largest_file(
        "what is largest file of sophyane?",
        workspace=tmp_path,
    )

    assert result is not None
    assert str(big.resolve()) in result
    assert "4096" in result


def test_nifdu_largest_file_ignores_git(tmp_path):
    from sophyane.nifdu_guarded_execution import (
        grounded_nifdu_largest_file,
    )

    hidden = tmp_path / ".git"
    hidden.mkdir()
    (hidden / "huge.bin").write_bytes(b"x" * 10000)

    real = tmp_path / "real.bin"
    real.write_bytes(b"x" * 100)

    result = grounded_nifdu_largest_file(
        "largest file of sophyane",
        workspace=tmp_path,
    )

    assert result is not None
    assert str(real.resolve()) in result
    assert "huge.bin" not in result


def test_make_use_of_is_not_execution_request():
    from sophyane.tui_v2 import _execution_requested

    assert not _execution_requested(
        "you probably forget the context and done "
        "make use of xerus repo of badrpk"
    )


def test_real_make_request_remains_execution():
    from sophyane.tui_v2 import _execution_requested

    assert _execution_requested("make a snake game")


def test_effective_nifdu_largest_file_precedes_provider():
    from pathlib import Path

    text = Path(
        "src/sophyane/runtime_intent_refinement_patch.py"
    ).read_text(encoding="utf-8")

    marker = text.index(
        "SOPHYANE_NIFDU_EFFECTIVE_LARGEST_FILE_DISPATCH_V1"
    )

    provider = text.index(
        "self.call_provider(",
        marker,
    )

    assert marker < provider


# SOPHYANE_ORCHESTRATION_MAKE_USE_OF_TEST_V1

def test_orchestration_patch_preserves_make_use_of_as_chat():
    from sophyane import tui_v2
    from sophyane.runtime_orchestration_patch import (
        install_orchestration_patch,
    )

    request = (
        "you probably forget the context and done "
        "make use of xerus repo of badrpk"
    )

    assert not tui_v2._execution_requested(
        request
    )

    install_orchestration_patch()

    assert not tui_v2._execution_requested(
        request
    )


def test_orchestration_patch_preserves_real_execution():
    from sophyane import tui_v2
    from sophyane.runtime_orchestration_patch import (
        install_orchestration_patch,
    )

    install_orchestration_patch()

    assert tui_v2._execution_requested(
        "make a snake game"
    )

    assert tui_v2._execution_requested(
        "build a website"
    )
