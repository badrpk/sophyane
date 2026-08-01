from __future__ import annotations

from sophyane import observability


def test_list_traces_merges_and_deduplicates_backends(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        observability,
        "_list_native_traces",
        lambda limit=20: {
            "ok": True,
            "traces": [
                {
                    "run_id": "native-1",
                    "source": "native",
                },
                {
                    "run_id": "shared",
                    "source": "native",
                },
            ],
            "count": 2,
        },
    )

    monkeypatch.setattr(
        observability,
        "_list_compat_traces",
        lambda limit=20: {
            "ok": True,
            "traces": [
                {
                    "run_id": "shared",
                    "source": "compat",
                },
                {
                    "run_id": "compat-1",
                    "source": "compat",
                },
            ],
            "count": 2,
        },
    )

    result = observability.list_traces(limit=10)

    assert result["ok"] is True
    assert result["count"] == 3
    assert [
        item["run_id"]
        for item in result["traces"]
    ] == [
        "native-1",
        "shared",
        "compat-1",
    ]


def test_list_traces_survives_native_backend_failure(
    monkeypatch,
) -> None:
    def broken_native(limit=20):
        raise RuntimeError("native trace store unavailable")

    monkeypatch.setattr(
        observability,
        "_list_native_traces",
        broken_native,
    )

    monkeypatch.setattr(
        observability,
        "_list_compat_traces",
        lambda limit=20: {
            "ok": True,
            "traces": [{"run_id": "compat-only"}],
            "count": 1,
        },
    )

    result = observability.list_traces()

    assert result["count"] == 1
    assert result["traces"][0]["run_id"] == "compat-only"
