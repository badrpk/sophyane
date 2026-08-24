from pathlib import Path
import subprocess

from sophyane.evolution import (
    discover_validation_topology,
    execute_baseline,
    resolve_target,
)


def run(*args):
    return subprocess.run(
        args,
        check=True,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    ).stdout.strip()


def init_repo(
    repo: Path,
):
    repo.mkdir()

    run(
        "git",
        "init",
        str(repo),
    )

    run(
        "git",
        "-C",
        str(repo),
        "config",
        "user.name",
        "V2E",
    )

    run(
        "git",
        "-C",
        str(repo),
        "config",
        "user.email",
        "v2e@example.invalid",
    )


def test_validation_scope_exceeds_mutation_scope_and_baseline_isolated(
    tmp_path: Path,
):
    harness = tmp_path / "harness"
    repo = tmp_path / "rangoons"

    init_repo(harness)
    init_repo(repo)

    (
        repo
        / "apps"
    ).mkdir()

    external = (
        repo
        / "RangoonsCore"
        / "project"
    )

    external.mkdir(
        parents=True
    )

    (
        external
        / "package.json"
    ).write_text(
        "{\n"
        '  "scripts": {\n'
        '    "test": "node test.js"\n'
        "  }\n"
        "}\n",
        encoding="utf-8",
    )

    (
        external
        / "test.js"
    ).write_text(
        "process.exit(0);\n",
        encoding="utf-8",
    )

    run(
        "git",
        "-C",
        str(repo),
        "add",
        ".",
    )

    run(
        "git",
        "-C",
        str(repo),
        "commit",
        "-m",
        "fixture",
    )

    run(
        "git",
        "-C",
        str(harness),
        "commit",
        "--allow-empty",
        "-m",
        "fixture",
    )

    target = resolve_target(
        name="rangoons",
        harness_repo=harness,
        explicit_repo=repo,
    )

    topology = discover_validation_topology(
        target_name="rangoons",
        repo=repo,
    )

    nested = [
        node
        for node in topology.nodes
        if (
            node.kind == "npm-test"
            and node.cwd
            == external.resolve()
        )
    ]

    assert len(nested) == 1

    head = run(
        "git",
        "-C",
        str(repo),
        "rev-parse",
        "HEAD",
    )

    result = execute_baseline(
        target,
        topology,
    )

    if nested[0].runnable:
        assert result.status == "PASS"

    assert run(
        "git",
        "-C",
        str(repo),
        "rev-parse",
        "HEAD",
    ) == head
