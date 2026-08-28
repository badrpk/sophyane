from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from sophyane.task_executor import (
    execute_compiled_task,
)


def compiled_for(
    target: str,
):
    requirement = SimpleNamespace(
        requirement_id="r1",
    )

    requirement.to_dict = lambda: {
        "requirement_id": "r1",
        "text": (
            "Decouple checkout. Publish OrderPlaced and move "
            "email, analytics and inventory to consumers."
        ),
    }

    return SimpleNamespace(
        ok=True,
        requirements=[requirement],
        execution_plan=[
            {
                "requirement_id": "r1",
                "contract": "async_event",
                "operation": "modify_event_pipeline",
                "validated_value": (
                    "Publish OrderPlaced; email consumer; "
                    "analytics consumer; inventory consumer."
                ),
                "targets": [
                    {
                        "path": target,
                    }
                ],
            }
        ],
    )


def test_accepts_compact_synchronous_checkout(
    tmp_path: Path,
):
    target = (
        tmp_path
        / "app"
        / "checkout.py"
    )

    target.parent.mkdir(
        parents=True
    )

    target.write_text(
        """from dataclasses import dataclass


@dataclass
class Order:
    id: int


def checkout(
    order,
    *,
    send_email,
    log_analytics,
    update_inventory,
):
    send_email(order)
    log_analytics(order)
    update_inventory(order)
    return order
""",
        encoding="utf-8",
    )

    result = execute_compiled_task(
        compiled_for(
            "app/checkout.py"
        ),
        workspace=tmp_path,
    )

    assert result.ok
    assert result.steps[0].ok
    assert result.steps[0].mutated

    text = target.read_text()

    assert "broker.publish" in text
    assert "OrderPlaced" in text
    assert "def email_consumer" in text
    assert "def analytics_consumer" in text
    assert "def inventory_consumer" in text


def test_preserves_surrounding_module(
    tmp_path: Path,
):
    target = (
        tmp_path
        / "checkout.py"
    )

    target.write_text(
        """CONSTANT = 42


def helper():
    return "before"


def checkout(order, *, send_email, log_analytics, update_inventory):
    send_email(order)
    log_analytics(order)
    update_inventory(order)
    return order


def tail():
    return "after"
""",
        encoding="utf-8",
    )

    result = execute_compiled_task(
        compiled_for(
            "checkout.py"
        ),
        workspace=tmp_path,
    )

    assert result.ok

    text = target.read_text()

    assert "CONSTANT = 42" in text
    assert 'return "before"' in text
    assert 'return "after"' in text


def test_fails_closed_without_all_three_side_effects(
    tmp_path: Path,
):
    target = (
        tmp_path
        / "checkout.py"
    )

    original = """def checkout(order, *, send_email):
    send_email(order)
    return order
"""

    target.write_text(
        original,
        encoding="utf-8",
    )

    result = execute_compiled_task(
        compiled_for(
            "checkout.py"
        ),
        workspace=tmp_path,
    )

    assert not result.ok
    assert not result.steps[0].ok
    assert not result.steps[0].mutated
    assert target.read_text() == original


def test_structural_executor_is_idempotent(
    tmp_path: Path,
):
    target = (
        tmp_path
        / "checkout.py"
    )

    target.write_text(
        """class Order:
    def __init__(self, id):
        self.id = id


def checkout(order, *, send_email, log_analytics, update_inventory):
    send_email(order)
    log_analytics(order)
    update_inventory(order)
    return order
""",
        encoding="utf-8",
    )

    compiled = compiled_for(
        "checkout.py"
    )

    first = execute_compiled_task(
        compiled,
        workspace=tmp_path,
    )

    assert first.ok
    assert first.steps[0].mutated

    snapshot = target.read_text()

    second = execute_compiled_task(
        compiled,
        workspace=tmp_path,
    )

    assert second.ok
    assert not second.steps[0].mutated
    assert target.read_text() == snapshot
