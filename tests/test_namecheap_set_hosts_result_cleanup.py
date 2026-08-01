from __future__ import annotations

from sophyane.cloud.namecheap import NamecheapClient


def test_set_hosts_executes_api_call_and_returns_summary(
    monkeypatch,
) -> None:
    client = object.__new__(NamecheapClient)

    calls: list[tuple[str, dict[str, str]]] = []

    def fake_call(
        command: str,
        **params: str,
    ):
        calls.append((command, params))
        return object()

    monkeypatch.setattr(
        client,
        "_call",
        fake_call,
    )

    result = client.set_hosts(
        "example.com",
        ipv4="203.0.113.10",
        ipv6="",
        www=True,
    )

    assert len(calls) == 1

    command, params = calls[0]

    assert command == "namecheap.domains.dns.setHosts"
    assert params["SLD"] == "example"
    assert params["TLD"] == "com"

    assert result["ok"] is True
    assert result["domain"] == "example.com"
    assert result["ipv4"] == "203.0.113.10"
    assert result["command"] == command
    assert result["hosts_set"] == 4
