import json

from sophyane.adaptive_execution import run_adaptive_loop


class Response:
    def __init__(self, payload):
        self.text = json.dumps({"action": payload})
        self.provider_id = "test"


def test_unmet_terminal_condition_cannot_false_green(tmp_path):
    initial = json.dumps(
        {
            "action": {
                "type": "write_file",
                "path": "poll_status.py",
                "content": 'print("STATUS: IN_PROGRESS")\n',
            }
        }
    )

    command = (
        "python -c 'import subprocess; "
        "[(print(subprocess.run([\"python\",\"poll_status.py\"],"
        "capture_output=True,text=True).stdout,end=\"\")) "
        "for _ in range(5)]; "
        "open(\"loop_test.log\",\"w\").write("
        "\"Loop limit exceeded\\n\")'"
    )

    replies = iter(
        [
            Response(
                {
                    "type": "run_command",
                    "command": command,
                }
            ),
            Response(
                {
                    "type": "respond",
                    "message": (
                        "STATUS: COMPLETE was not produced; "
                        "Loop limit exceeded."
                    ),
                }
            ),
        ]
    )

    result = run_adaptive_loop(
        initial_text=initial,
        original_request=(
            "Create a script `poll_status.py` that outputs "
            "`STATUS: IN_PROGRESS` and returns exit code 0. "
            "Run this script repeatedly until it outputs "
            "`STATUS: COMPLETE`. If `STATUS: COMPLETE` is not "
            "produced after 5 consecutive executions, log "
            "\"Loop limit exceeded\" to `loop_test.log` and "
            "exit cleanly."
        ),
        ask=lambda _prompt: next(replies),
        workspace=tmp_path,
        max_steps=3,
    )

    assert (
        "Project implementation and verification completed successfully."
        not in result
    )
    assert "STATUS: COMPLETE" in result or "Loop limit exceeded" in result
