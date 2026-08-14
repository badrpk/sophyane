from types import SimpleNamespace

import sophyane.sli_semantic_intelligence as sem


def chunk(text):
    return SimpleNamespace(text=text)


def admitted(text, capability):
    return sem._strict_has_discriminative_evidence(
        chunk(text),
        capability,
    )


def test_process_spawn_alone_is_not_supervision():
    assert not admitted(
        """
        import subprocess
        subprocess.Popen(
            ["gjslint"],
            stdout=subprocess.PIPE,
        )
        """,
        "process_supervision",
    )


def test_process_communicate_alone_is_not_supervision():
    assert not admitted(
        """
        import subprocess
        proc = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
        )
        stdout, stderr = proc.communicate()
        """,
        "process_supervision",
    )


def test_process_lifecycle_is_supervision():
    assert admitted(
        """
        import subprocess
        proc = subprocess.Popen(command)
        if proc.poll() is None:
            proc.terminate()
            proc.wait()
        """,
        "process_supervision",
    )


def test_plain_checked_command_is_not_safe_execution():
    assert not admitted(
        """
        import subprocess
        subprocess.run(
            ["pbcopy"],
            check=True,
        )
        """,
        "safe_command_execution",
    )


def test_controlled_command_execution_is_admitted():
    assert admitted(
        """
        import subprocess
        subprocess.run(
            command,
            shell=False,
            check=True,
            timeout=300,
        )
        """,
        "safe_command_execution",
    )


def test_log_reader_with_log_context_is_admitted():
    assert admitted(
        """
        text = log_path.read_text()
        tail = text.splitlines()[-100:]
        for log in tail:
            print(log)
        """,
        "log_diagnostics",
    )


def test_traceback_word_without_log_access_is_not_diagnostics():
    assert not admitted(
        """
        traceback = payload.get("traceback")
        return traceback
        """,
        "log_diagnostics",
    )


def test_unmodified_capability_retains_v1_behavior():
    assert admitted(
        """
        def validate(value):
            if value is None:
                raise ValueError("incorrect value")
        """,
        "rules_and_validation",
    )
