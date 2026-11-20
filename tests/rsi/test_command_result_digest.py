import hashlib
from dataclasses import asdict


def test_command_result_digest_is_sha256_of_output():
    from sophyane.rsi.models import CommandResult

    result = CommandResult(("python3", "check"), 0, "stable output")

    assert result.digest == hashlib.sha256(b"stable output").hexdigest()
    assert result.digest == hashlib.sha256(b"stable output").hexdigest()
    assert set(asdict(result)) == {"command", "exit_code", "output", "cwd"}
