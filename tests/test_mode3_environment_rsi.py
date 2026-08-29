from sophyane.environment import (
    EnvironmentAction,
    Scenario,
)
from sophyane.mode3_environment_rsi import (
    MAX_ENVIRONMENT_RSI_STEPS,
    parse_environment_action,
)


def test_environment_rsi_is_hard_bounded():
    assert (
        MAX_ENVIRONMENT_RSI_STEPS
        <= 12
    )


def test_environment_action_parser():
    action = parse_environment_action(
        (
            'ENVIRONMENT_ACTION_JSON: '
            '{"actor":"sophyane",'
            '"action":"finish",'
            '"payload":{'
            '"operation":"set",'
            '"key":"done",'
            '"value":true'
            '}}'
        )
    )

    assert action is not None

    assert (
        action.action
        == "finish"
    )

    assert (
        action.payload[
            "key"
        ]
        == "done"
    )


def test_environment_action_parser_rejects_prose():
    assert (
        parse_environment_action(
            "I think we should finish."
        )
        is None
    )
