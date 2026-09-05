import json

from sophyane import adaptive_execution as adaptive
from sophyane import execution_runtime as runtime


def _selected(payload: dict):
    raw = json.dumps(payload)

    # Production adaptive execution uses runtime.extract_plan(), not
    # adaptive.extract_plan().
    plan = runtime.extract_plan(raw)

    assert isinstance(plan, dict)

    return adaptive._selected_action(
        runtime,
        plan,
    )


def test_direct_top_level_write_file_is_executable():
    action = _selected(
        {
            "type": "write_file",
            "path": "nifdu_benchmark_api/app.py",
            "content": "print('ok')\n",
        }
    )

    assert action is not None
    assert action["type"] == "write_file"
    assert action["path"] == "nifdu_benchmark_api/app.py"
    assert action["content"] == "print('ok')\n"


def test_nested_action_write_file_is_executable():
    action = _selected(
        {
            "action": {
                "type": "write_file",
                "path": "nifdu_benchmark_api/app.py",
                "content": "print('ok')\n",
            }
        }
    )

    assert action is not None
    assert action["type"] == "write_file"
    assert action["path"] == "nifdu_benchmark_api/app.py"


def test_top_level_files_bundle_becomes_batch():
    action = _selected(
        {
            "files": [
                {
                    "path": "nifdu_benchmark_api/app.py",
                    "content": "print('ok')\n",
                },
                {
                    "path": "nifdu_benchmark_api/requirements.txt",
                    "content": "Flask\npytest\n",
                },
            ]
        }
    )

    assert action is not None
    assert action["type"] == "batch"

    assert [
        child["path"]
        for child in action["actions"]
    ] == [
        "nifdu_benchmark_api/app.py",
        "nifdu_benchmark_api/requirements.txt",
    ]


def test_nested_action_files_bundle_becomes_batch():
    action = _selected(
        {
            "action": {
                "files": [
                    {
                        "path": "nifdu_benchmark_api/app.py",
                        "content": "print('ok')\n",
                    },
                    {
                        "path": "nifdu_benchmark_api/requirements.txt",
                        "content": "Flask\npytest\n",
                    },
                ]
            }
        }
    )

    assert action is not None
    assert action["type"] == "batch"
    assert len(action["actions"]) == 2


def test_untyped_arbitrary_dictionary_is_not_executable():
    assert (
        adaptive._normalise_action(
            {
                "description": "not an executable action",
                "reasoning": "metadata only",
            }
        )
        is None
    )


def test_unknown_string_action_is_not_executable():
    assert (
        adaptive._normalise_action(
            {
                "action": "invent_database",
                "name": "example",
            }
        )
        is None
    )
