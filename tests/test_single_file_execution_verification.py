from sophyane import adaptive_execution as adaptive


def test_python_write_run_exact_output_contract_is_detected():
    request = """Create a file named hello.py that prints exactly:

SOPHYANE_TEST_OK

Then run the file and verify that the output is exactly SOPHYANE_TEST_OK.
"""

    action = {
        "type": "write_file",
        "path": "hello.py",
        "content": 'print("SOPHYANE_TEST_OK")\n',
    }

    verification = (
        adaptive._single_file_execution_verification(
            request,
            action,
        )
    )

    assert verification is not None

    command, expected = verification

    assert command.endswith(" hello.py")
    assert expected == "SOPHYANE_TEST_OK"


def test_plain_python_write_does_not_force_execution():
    request = (
        "Create a file named hello.py containing "
        'print("SOPHYANE_TEST_OK").'
    )

    action = {
        "type": "write_file",
        "path": "hello.py",
        "content": 'print("SOPHYANE_TEST_OK")\n',
    }

    assert (
        adaptive._single_file_execution_verification(
            request,
            action,
        )
        is None
    )


def test_non_python_write_does_not_force_python_execution():
    request = """Create hello.txt that prints exactly:

SOPHYANE_TEST_OK

Then run the file and verify the output.
"""

    action = {
        "type": "write_file",
        "path": "hello.txt",
        "content": "SOPHYANE_TEST_OK\n",
    }

    assert (
        adaptive._single_file_execution_verification(
            request,
            action,
        )
        is None
    )


def test_live_regression_contract_extracts_expected_stdout():
    request = """Create a file named hello.py that prints exactly:

SOPHYANE_TEST_OK

Then run the file and verify that the output is exactly SOPHYANE_TEST_OK.
"""

    verification = (
        adaptive._single_file_execution_verification(
            request,
            {
                "type": "write_file",
                "path": "hello.py",
                "content": '# hello.py\nprint("Hello, World!")\n',
            },
        )
    )

    assert verification is not None
    _, expected = verification

    assert expected == "SOPHYANE_TEST_OK"


def test_flow_runs_before_generic_workspace_mutation_completion():
    source = open(
        "src/sophyane/adaptive_execution.py",
        encoding="utf-8",
    ).read()

    flow = source.index(
        "SOPHYANE_SINGLE_FILE_EXECUTION_VERIFICATION_FLOW_V1"
    )

    mutation = source.index(
        "workspace_mutated = True",
        flow,
    )

    assert flow < mutation

    assert (
        "actual_stdout == expected_stdout"
        in source[flow:mutation]
    )

    assert (
        "Deterministic single-file execution verification failed."
        in source[flow:mutation]
    )


def test_singleton_batch_enters_python_execution_verification():
    request = """Create a file named hello.py that prints exactly:

SOPHYANE_TEST_OK

Then run the file and verify that the output is exactly SOPHYANE_TEST_OK.
"""

    child = {
        "type": "write_file",
        "path": "hello.py",
        "content": 'print("SOPHYANE_TEST_OK")\n',
    }

    verification = (
        adaptive._single_file_execution_verification(
            request,
            child,
        )
    )

    assert verification is not None
    command, expected = verification
    assert command.endswith(" hello.py")
    assert expected == "SOPHYANE_TEST_OK"


def test_live_flow_unwraps_singleton_batch_before_verification():
    source = open(
        "src/sophyane/adaptive_execution.py",
        encoding="utf-8",
    ).read()

    marker = source.index(
        "SOPHYANE_SINGLETON_BATCH_EXECUTION_VERIFICATION_V1"
    )

    section = source[
        marker:
        marker + 1800
    ]

    assert 'kind == "batch"' in section
    assert "len(children) == 1" in section
    assert "verification_action = children[0]" in section
    assert (
        "_single_file_execution_verification("
        in section
    )
