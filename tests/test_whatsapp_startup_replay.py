from __future__ import annotations

import inspect

import sophyane.cloud.messaging as messaging
import sophyane.cloud.portal as portal


def _construct_portal_app():
    """Construct PortalApp using its real zero/default-argument surface."""
    signature = inspect.signature(
        portal.PortalApp
    )

    required = [
        parameter
        for parameter in signature.parameters.values()
        if parameter.name != "self"
        and parameter.default
        is inspect.Parameter.empty
        and parameter.kind
        in (
            inspect.Parameter.POSITIONAL_ONLY,
            inspect.Parameter.POSITIONAL_OR_KEYWORD,
            inspect.Parameter.KEYWORD_ONLY,
        )
    ]

    assert not required, (
        "PortalApp unexpectedly requires constructor "
        f"arguments: {[item.name for item in required]}"
    )

    return portal.PortalApp()


def test_startup_replay_wiring_exists():
    startup = getattr(
        portal,
        "_replay_whatsapp_inbound_at_startup",
        None,
    )

    assert callable(startup)


def test_portal_startup_invokes_replay(
    monkeypatch,
):
    calls = []

    def fake_replay():
        calls.append("replay")
        return []

    monkeypatch.setattr(
        messaging,
        "_replay_whatsapp_inbound_spool",
        fake_replay,
    )

    startup = getattr(
        portal,
        "_replay_whatsapp_inbound_at_startup",
        None,
    )

    assert callable(startup)

    startup()

    assert calls == ["replay"]


def test_startup_replay_failure_is_contained(
    monkeypatch,
):
    def fail_replay():
        raise RuntimeError(
            "replay unavailable"
        )

    monkeypatch.setattr(
        messaging,
        "_replay_whatsapp_inbound_spool",
        fail_replay,
    )

    startup = getattr(
        portal,
        "_replay_whatsapp_inbound_at_startup",
        None,
    )

    assert callable(startup)

    result = startup()

    assert isinstance(result, list)
    assert len(result) == 1

    failure = result[0]

    assert failure["ok"] is False
    assert failure["queued"] is False
    assert failure["stage"] == "startup_replay"
    assert "replay unavailable" in failure["error"]


def test_portal_app_lifecycle_triggers_startup_replay(
    monkeypatch,
):
    calls = []

    def fake_startup():
        calls.append("startup")
        return []

    monkeypatch.setattr(
        portal,
        "_replay_whatsapp_inbound_at_startup",
        fake_startup,
    )

    _construct_portal_app()

    assert calls == ["startup"]


def test_each_portal_app_runs_startup_replay_once(
    monkeypatch,
):
    calls = []

    def fake_startup():
        calls.append("startup")
        return []

    monkeypatch.setattr(
        portal,
        "_replay_whatsapp_inbound_at_startup",
        fake_startup,
    )

    first = _construct_portal_app()

    assert first is not None
    assert calls == ["startup"]

    second = _construct_portal_app()

    assert second is not None
    assert calls == [
        "startup",
        "startup",
    ]


def test_startup_wiring_does_not_use_ordinary_enqueue():
    startup = getattr(
        portal,
        "_replay_whatsapp_inbound_at_startup",
        None,
    )

    assert callable(startup)

    source = inspect.getsource(
        startup
    )

    assert (
        "_replay_whatsapp_inbound_spool"
        in source
    )

    assert (
        "enqueue_whatsapp_inbound_message"
        not in source
    )


def test_startup_wiring_never_uses_outbound_outbox():
    startup = getattr(
        portal,
        "_replay_whatsapp_inbound_at_startup",
        None,
    )

    assert callable(startup)

    source = inspect.getsource(
        startup
    )

    assert "WA_OUTBOX" not in source


def test_messaging_import_does_not_auto_replay():
    source = inspect.getsource(
        messaging
    )

    definition = (
        "def _replay_whatsapp_inbound_spool("
    )

    assert definition in source

    before_definition, after_definition = (
        source.split(
            definition,
            1,
        )
    )

    # No call can occur before the replay function exists.
    assert (
        "_replay_whatsapp_inbound_spool()"
        not in before_definition
    )

    # The replay function itself may of course exist and be
    # referenced by portal startup. Messaging must not invoke
    # it as a module-level import side effect.
    lines = after_definition.splitlines()

    top_level_calls = [
        line
        for line in lines
        if line.startswith(
            "_replay_whatsapp_inbound_spool()"
        )
    ]

    assert top_level_calls == []


def test_processor_idempotency_authority_remains_in_processor():
    source = inspect.getsource(
        messaging.process_whatsapp_inbound_message
    )

    assert "_begin_whatsapp_inbound(" in source
    assert "_finish_whatsapp_inbound(" in source


def test_portal_startup_does_not_mutate_durable_jobs_directly():
    startup = getattr(
        portal,
        "_replay_whatsapp_inbound_at_startup",
        None,
    )

    assert callable(startup)

    source = inspect.getsource(
        startup
    )

    assert (
        "_persist_whatsapp_inbound_message"
        not in source
    )

    assert (
        "_remove_whatsapp_inbound_message"
        not in source
    )
