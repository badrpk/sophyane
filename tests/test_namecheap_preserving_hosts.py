from unittest.mock import patch

from sophyane.cloud.namecheap import (
    NamecheapClient,
    NamecheapConfig,
)


def client() -> NamecheapClient:
    return NamecheapClient(
        NamecheapConfig(
            api_user="u",
            api_key="secret",
            username="u",
            client_ip="203.0.113.9",
        )
    )


def test_merge_preserves_unrelated_records() -> None:
    existing = [
        {
            "host": "@",
            "type": "A",
            "address": "198.51.100.4",
            "ttl": "300",
        },
        {
            "host": "www",
            "type": "CNAME",
            "address": "example.host.",
            "ttl": "300",
        },
        {
            "host": "_github-pages-challenge",
            "type": "TXT",
            "address": "verification-token",
            "ttl": "300",
        },
        {
            "host": "mail",
            "type": "A",
            "address": "192.0.2.8",
            "ttl": "300",
        },
    ]

    managed = [
        {
            "host": "mail",
            "type": "A",
            "address": "203.0.113.20",
            "ttl": "300",
        },
        {
            "host": "@",
            "type": "MX",
            "address": "mail.nifdu.com",
            "mx_pref": "10",
            "ttl": "300",
        },
    ]

    merged = NamecheapClient.merge_hosts(
        existing,
        managed,
        managed_keys={
            ("mail", "A"),
            ("@", "MX"),
        },
    )

    assert {
        "host": "www",
        "type": "CNAME",
        "address": "example.host.",
        "ttl": "300",
    } in merged

    assert any(
        row["host"]
        == "_github-pages-challenge"
        for row in merged
    )

    assert not any(
        row["host"] == "mail"
        and row["address"] == "192.0.2.8"
        for row in merged
    )

    assert any(
        row["host"] == "mail"
        and row["address"] == "203.0.113.20"
        for row in merged
    )


def test_preview_does_not_call_sethosts() -> None:
    c = client()

    with (
        patch.object(
            c,
            "get_hosts",
            return_value=[
                {
                    "host": "www",
                    "type": "CNAME",
                    "address": "existing.example",
                    "ttl": "300",
                },
            ],
        ),
        patch.object(
            c,
            "replace_hosts",
        ) as write,
    ):
        result = c.merge_and_replace_hosts(
            "nifdu.com",
            [
                {
                    "host": "mail",
                    "type": "A",
                    "address": "203.0.113.20",
                    "ttl": "300",
                },
            ],
            managed_keys={
                ("mail", "A"),
            },
            apply=False,
        )

    assert result["applied"] is False
    assert result["preserved_count"] == 1
    write.assert_not_called()


def test_live_apply_uses_complete_merged_set() -> None:
    c = client()

    with (
        patch.object(
            c,
            "get_hosts",
            return_value=[
                {
                    "host": "www",
                    "type": "CNAME",
                    "address": "existing.example",
                    "ttl": "300",
                },
            ],
        ),
        patch.object(
            c,
            "replace_hosts",
            return_value={
                "ok": True,
            },
        ) as write,
    ):
        result = c.merge_and_replace_hosts(
            "nifdu.com",
            [
                {
                    "host": "mail",
                    "type": "A",
                    "address": "203.0.113.20",
                    "ttl": "300",
                },
            ],
            managed_keys={
                ("mail", "A"),
            },
            apply=True,
        )

    assert result["applied"] is True

    records = write.call_args.args[1]

    assert any(
        row["host"] == "www"
        for row in records
    )

    assert any(
        row["host"] == "mail"
        for row in records
    )
