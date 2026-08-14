from types import SimpleNamespace

import pytest

import sophyane.sli_semantic_intelligence as sem


REQUEST = (
    "Build a Python terminal agent that monitors daemon processes, "
    "diagnoses out-of-memory failures and port-binding conflicts, "
    "reads crash logs, and executes safe corrective commands."
)


def chunk(text: str, path: str = "module.py"):
    return SimpleNamespace(
        text=text,
        path=path,
        source="unit",
        language="python",
        weight=1.0,
        placement="function",
        metadata={},
    )


@pytest.fixture
def plan():
    return sem.build_semantic_plan(REQUEST)


def requirement(plan, name):
    for item in plan.capabilities:
        if item.name == name:
            return item
    raise AssertionError(
        f"missing capability {name}; "
        f"have {[x.name for x in plan.capabilities]}"
    )


def score(plan, name, candidate):
    return sem._chunk_semantic_score(
        candidate,
        requirement(plan, name),
        plan,
    )


def test_network_diagnostic_beats_generic_http_timeout(plan):
    actual_port_probe = chunk(
        """
import socket

def port_available(host, port):
    sock = socket.socket()
    try:
        return sock.connect_ex((host, port)) == 0
    finally:
        sock.close()
"""
    )

    unrelated_http = chunk(
        """
import requests

def call_api(url, payload):
    return requests.post(
        url,
        json=payload,
        timeout=30,
    )
"""
    )

    assert (
        score(
            plan,
            "network_port_diagnostics",
            actual_port_probe,
        )
        >
        score(
            plan,
            "network_port_diagnostics",
            unrelated_http,
        )
    )


def test_resource_diagnostic_beats_generic_process_launch(plan):
    actual_resource_probe = chunk(
        """
import psutil

def memory_pressure(pid):
    process = psutil.Process(pid)
    rss = process.memory_info().rss
    return rss
"""
    )

    unrelated_launcher = chunk(
        """
import subprocess

def launch(command):
    return subprocess.Popen(command)
"""
    )

    assert (
        score(
            plan,
            "resource_diagnostics",
            actual_resource_probe,
        )
        >
        score(
            plan,
            "resource_diagnostics",
            unrelated_launcher,
        )
    )


def test_safe_execution_beats_http_timeout(plan):
    safe_runner = chunk(
        """
import subprocess

ALLOWED = {"systemctl", "journalctl"}

def run_safe(argv):
    if not argv or argv[0] not in ALLOWED:
        raise ValueError("command not allowed")

    return subprocess.run(
        argv,
        shell=False,
        timeout=20,
        check=True,
        capture_output=True,
        text=True,
    )
"""
    )

    http_timeout = chunk(
        """
import requests

def send(url):
    return requests.post(
        url,
        timeout=20,
    )
"""
    )

    assert (
        score(
            plan,
            "safe_command_execution",
            safe_runner,
        )
        >
        score(
            plan,
            "safe_command_execution",
            http_timeout,
        )
    )


def test_log_diagnostic_beats_generic_debug_print(plan):
    crash_reader = chunk(
        """
from pathlib import Path

def read_crash_log(path):
    text = Path(path).read_text()
    return [
        line
        for line in text.splitlines()
        if "error" in line.lower()
        or "exception" in line.lower()
        or "oom" in line.lower()
    ]
"""
    )

    generic_debug = chunk(
        """
import sys

def debug(value):
    print(
        "DEBUG",
        value,
        file=sys.stderr,
    )
"""
    )

    assert (
        score(
            plan,
            "log_diagnostics",
            crash_reader,
        )
        >
        score(
            plan,
            "log_diagnostics",
            generic_debug,
        )
    )


def test_executable_bonus_cannot_overrule_capability_behavior(plan):
    unrelated_small_function = chunk(
        """
def helper(value):
    return str(value)
"""
    )

    port_probe = chunk(
        """
import socket

def probe_port(host, port):
    with socket.socket() as sock:
        return sock.connect_ex((host, port))
"""
    )

    assert (
        score(
            plan,
            "network_port_diagnostics",
            port_probe,
        )
        >
        score(
            plan,
            "network_port_diagnostics",
            unrelated_small_function,
        )
    )


def test_capability_evidence_is_contrastive(plan):
    candidate = chunk(
        """
import socket

def probe_port(host, port):
    sock = socket.socket()
    try:
        return sock.connect_ex((host, port))
    finally:
        sock.close()
"""
    )

    network = score(
        plan,
        "network_port_diagnostics",
        candidate,
    )

    resource = score(
        plan,
        "resource_diagnostics",
        candidate,
    )

    assert network > resource
