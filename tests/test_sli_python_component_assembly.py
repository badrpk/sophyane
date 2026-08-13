from __future__ import annotations
import pytest

from types import SimpleNamespace

from sophyane.code_memory.compose import (
    compose_python_from_chunks,
)


def chunk(
    chunk_id: str,
    text: str,
    *,
    path: str,
    language: str = "python",
):
    return SimpleNamespace(
        id=chunk_id,
        text=text,
        path=path,
        language=language,
        meta={},
    )


def test_invalid_rich_compound_does_not_monopolize_python_assembly():
    rich = chunk(
        "rich",
        (
            "/* RICH CHUNK: project */\n"
            "/* part:abc path:/tmp/a.py */\n"
            + ("x" * 20000)
        ),
        path="compound::project",
    )

    process = chunk(
        "process",
        (
            "import subprocess\n\n"
            "def poll_process(argv):\n"
            "    proc = subprocess.Popen(argv)\n"
            "    return proc.poll()\n"
        ),
        path="process.py",
    )

    command = chunk(
        "command",
        (
            "import shlex\n"
            "import subprocess\n\n"
            "def safe_run(command):\n"
            "    argv = shlex.split(command)\n"
            "    return subprocess.run(\n"
            "        argv,\n"
            "        shell=False,\n"
            "        timeout=30,\n"
            "    )\n"
        ),
        path="command.py",
    )

    source, used = compose_python_from_chunks(
        [rich, process, command]
    )

    compile(source, "<assembled>", "exec")

    assert "rich" not in used
    assert "process" in used
    assert "command" in used

    assert "subprocess.Popen" in source
    assert "shell=False" in source


def test_invalid_python_chunk_is_skipped():
    invalid = chunk(
        "invalid",
        "/* definitely not python */\n",
        path="bad.py",
    )

    valid = chunk(
        "valid",
        "def main():\n    return 0\n",
        path="main.py",
    )

    source, used = compose_python_from_chunks(
        [invalid, valid]
    )

    compile(source, "<assembled>", "exec")

    assert used == ["valid"]


def test_oversized_first_component_does_not_block_later_components():
    huge = chunk(
        "huge",
        "VALUE = " + repr("x" * 50000) + "\n",
        path="huge.py",
    )

    useful = chunk(
        "useful",
        (
            "def main():\n"
            "    return 0\n"
        ),
        path="main.py",
    )

    source, used = compose_python_from_chunks(
        [huge, useful]
    )

    assert "huge" not in used
    assert "useful" in used

    compile(source, "<assembled>", "exec")


@pytest.mark.xfail(
    reason=(
        "Superseded by authoritative-root assembly contract; "
        "a flat candidate list cannot identify semantic roots."
    ),
    strict=True,
)
def test_python_assembly_rejects_incompatible_independent_component():
    process = chunk(
        "process",
        (
            "import subprocess\n\n"
            "def poll_process(argv):\n"
            "    proc = subprocess.Popen(argv)\n"
            "    return proc.poll()\n"
        ),
        path="/repo/process.py::poll_process",
    )
    process.meta = {
        "placement": "function",
        "provides": ["process_supervision"],
        "outputs": [
            {
                "name": "poll_process",
                "type": "function",
            },
        ],
    }

    command = chunk(
        "command",
        (
            "import subprocess\n\n"
            "def safe_run(argv):\n"
            "    return subprocess.run(\n"
            "        argv,\n"
            "        shell=False,\n"
            "        timeout=30,\n"
            "    )\n"
        ),
        path="/repo/command.py::safe_run",
    )
    command.meta = {
        "placement": "function",
        "provides": ["safe_command_execution"],
        "outputs": [
            {
                "name": "safe_run",
                "type": "function",
            },
        ],
    }

    unrelated = chunk(
        "unrelated",
        (
            "def calculate_invoice_total(items):\n"
            "    return sum(items)\n"
        ),
        path="/other/billing.py::calculate_invoice_total",
    )
    unrelated.meta = {
        "placement": "function",
        "provides": ["billing"],
        "outputs": [
            {
                "name": "calculate_invoice_total",
                "type": "function",
            },
        ],
    }

    source, used = compose_python_from_chunks(
        [process, command, unrelated]
    )

    compile(source, "<assembled>", "exec")

    assert "process" in used
    assert "command" in used

    # A syntactically valid retrieved component is not automatically
    # compositionally compatible with the requested Python component set.
    assert "unrelated" not in used
    assert "calculate_invoice_total" not in source


def test_python_assembly_honors_authoritative_root_ids():
    process = chunk(
        "process",
        (
            "import subprocess\n\n"
            "def poll_process(argv):\n"
            "    proc = subprocess.Popen(argv)\n"
            "    return proc.poll()\n"
        ),
        path="/repo/process.py::poll_process",
    )
    process.meta = {
        "placement": "function",
        "provides": ["process_supervision"],
        "requires": ["safe_command_execution"],
        "outputs": [
            {
                "name": "poll_process",
                "type": "function",
            },
        ],
    }

    command = chunk(
        "command",
        (
            "import subprocess\n\n"
            "def safe_run(argv):\n"
            "    return subprocess.run(\n"
            "        argv,\n"
            "        shell=False,\n"
            "        timeout=30,\n"
            "    )\n"
        ),
        path="/repo/command.py::safe_run",
    )
    command.meta = {
        "placement": "function",
        "provides": ["safe_command_execution"],
        "outputs": [
            {
                "name": "safe_run",
                "type": "function",
            },
        ],
    }

    unrelated = chunk(
        "unrelated",
        (
            "def calculate_invoice_total(items):\n"
            "    return sum(items)\n"
        ),
        path="/other/billing.py::calculate_invoice_total",
    )
    unrelated.meta = {
        "placement": "function",
        "provides": ["billing"],
        "outputs": [
            {
                "name": "calculate_invoice_total",
                "type": "function",
            },
        ],
    }

    # Semantic retrieval may have supplied all three candidates,
    # but only "process" is an authoritative semantic root.
    #
    # "command" is required transitively by that root.
    # "unrelated" is neither a root nor a dependency.
    source, used = compose_python_from_chunks(
        [process, command, unrelated],
        root_ids=["process"],
    )

    compile(source, "<assembled>", "exec")

    assert "process" in used
    assert "command" in used
    assert "unrelated" not in used

    assert "poll_process" in source
    assert "safe_run" in source
    assert "calculate_invoice_total" not in source
