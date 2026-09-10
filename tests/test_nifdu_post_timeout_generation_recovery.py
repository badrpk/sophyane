import sophyane.providers.nifdu_cdp_bridge as bridge


class FakeCDP:
    def __init__(self, evaluations):
        self.evaluations = list(evaluations)
        self.expressions = []

    def evaluate(self, expression):
        self.expressions.append(expression)

        if not self.evaluations:
            raise AssertionError(
                "unexpected extra CDP evaluate call"
            )

        value = self.evaluations.pop(0)

        if isinstance(value, Exception):
            raise value

        return value


def test_prepare_for_new_generation_is_noop_when_not_generating(
    monkeypatch,
):
    cdp = FakeCDP(
        [
            {
                "generating": False,
                "stopPresent": False,
            },
        ]
    )

    monkeypatch.setattr(
        bridge.time,
        "sleep",
        lambda _: None,
    )

    bridge.prepare_for_new_generation(
        cdp,
        timeout=1.0,
        interval=0.01,
    )

    assert len(cdp.expressions) == 1


def test_prepare_for_new_generation_stops_stale_generation(
    monkeypatch,
):
    cdp = FakeCDP(
        [
            # Initial observation: previous request is still generating.
            {
                "generating": True,
                "stopPresent": True,
            },

            # Stop-button click succeeds.
            True,

            # First post-click observation: still winding down.
            {
                "generating": True,
                "stopPresent": True,
            },

            # Next observation: generation has stopped.
            {
                "generating": False,
                "stopPresent": False,
            },
        ]
    )

    monkeypatch.setattr(
        bridge.time,
        "sleep",
        lambda _: None,
    )

    bridge.prepare_for_new_generation(
        cdp,
        timeout=1.0,
        interval=0.01,
    )

    assert len(cdp.expressions) == 4

    joined = "\n".join(cdp.expressions).lower()

    assert "stop-button" in joined
    assert ".click()" in joined


def test_ask_recovers_prior_generation_before_baseline():
    import inspect

    source = inspect.getsource(
        bridge.ask
    )

    recovery = source.index(
        "prepare_for_new_generation("
    )

    baseline = source.index(
        "before = assistant_state(cdp)"
    )

    assert recovery < baseline
