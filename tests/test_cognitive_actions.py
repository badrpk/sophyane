def test_safe_actions_install():
    import sophyane.cognitive_actions

    from sophyane.cognitive_loop import (
        cognitive_action_registry,
    )

    registry = (
        cognitive_action_registry()
    )

    assert registry.supports(
        "hypothesis_only"
    )

    assert registry.supports(
        "memory_inspection"
    )

    assert not registry.supports(
        "shell"
    )

    assert not registry.supports(
        "financial_transaction"
    )

    assert not registry.supports(
        "machine_control"
    )


def test_safe_actions_auto_install_in_fresh_runtime():
    import json
    import subprocess
    import sys

    code = r'''
import json
from sophyane.cognitive_loop import cognitive_loop_status

status = cognitive_loop_status()

print(json.dumps({
    "registered_actions": status["registered_actions"],
    "install_error": status["builtin_action_install_error"],
}))
'''

    result = subprocess.run(
        [
            sys.executable,
            "-c",
            code,
        ],
        check=True,
        capture_output=True,
        text=True,
    )

    payload = json.loads(
        result.stdout.strip()
    )

    assert (
        payload["install_error"]
        is None
    )

    assert (
        "hypothesis_only"
        in payload[
            "registered_actions"
        ]
    )

    assert (
        "memory_inspection"
        in payload[
            "registered_actions"
        ]
    )
