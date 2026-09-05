from sophyane import local_server


def test_pid_alive_none_is_false():
    assert local_server._pid_alive(None) is False


def test_pid_alive_zero_is_false():
    assert local_server._pid_alive(0) is False


def test_pid_alive_negative_is_false():
    assert local_server._pid_alive(-1) is False


def test_none_pid_contract_marker_exists():
    source = open(
        "src/sophyane/local_server.py",
        encoding="utf-8",
    ).read()

    assert "SOPHYANE_LOCAL_SERVER_NONE_PID_CONTRACT_V1" in source
    assert "if pid is None or pid <= 0:" in source
