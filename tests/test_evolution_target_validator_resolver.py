from pathlib import Path
import subprocess

from sophyane.evolution.badrpk_targets import (
    resolve_target,
)
from sophyane.evolution.target_journal import (
    write_profile_record,
)
from sophyane.evolution.target_policy import (
    build_target_policy,
)
from sophyane.evolution.target_validator_resolver import (
    resolve_repository_validators,
)


def git(
    repo: Path,
    *args: str,
) -> str:
    return subprocess.run(
        (
            "git",
            "-C",
            str(repo),
            *args,
        ),
        check=True,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    ).stdout.strip()


def init_repo(
    repo: Path,
) -> None:
    repo.mkdir(
        parents=True,
    )

    subprocess.run(
        (
            "git",
            "init",
            str(repo),
        ),
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    git(
        repo,
        "config",
        "user.name",
        "V2D",
    )

    git(
        repo,
        "config",
        "user.email",
        "v2d@example.invalid",
    )

    git(
        repo,
        "commit",
        "--allow-empty",
        "-m",
        "fixture",
    )


def test_nested_npm_project_is_discovered(
    tmp_path: Path,
):
    harness = tmp_path / "harness"
    repo = tmp_path / "rangoons"

    init_repo(harness)
    init_repo(repo)

    app = (
        repo
        / "apps"
        / "mart"
    )

    app.mkdir(
        parents=True,
    )

    (
        app
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
        app
        / "test.js"
    ).write_text(
        "process.exit(0);\n",
        encoding="utf-8",
    )

    target = resolve_target(
        name="rangoons",
        harness_repo=harness,
        explicit_repo=repo,
    )

    policy = build_target_policy(
        target
    )

    profile = resolve_repository_validators(
        target_name=target.name,
        repo=target.repo,
        policy=policy,
    )

    matches = [
        item
        for item in profile.candidates
        if (
            item.name == "npm-test"
            and item.cwd == app.resolve()
        )
    ]

    assert len(matches) == 1


def test_placeholder_npm_never_becomes_ready(
    tmp_path: Path,
):
    harness = tmp_path / "harness"
    repo = tmp_path / "xerus"

    init_repo(harness)
    init_repo(repo)

    (repo / "src").mkdir()

    (
        repo
        / "package.json"
    ).write_text(
        "{\n"
        '  "scripts": {\n'
        '    "test": "echo \\"Error: no test specified\\" && exit 1"\n'
        "  }\n"
        "}\n",
        encoding="utf-8",
    )

    target = resolve_target(
        name="xerus",
        harness_repo=harness,
        explicit_repo=repo,
    )

    policy = build_target_policy(
        target
    )

    profile = resolve_repository_validators(
        target_name=target.name,
        repo=target.repo,
        policy=policy,
    )

    npm = [
        item
        for item in profile.candidates
        if item.name == "npm-test"
    ]

    assert len(npm) == 1
    assert not npm[0].runnable
    assert profile.readiness == "NOT_READY"


def test_profile_journal_is_written_atomically(
    tmp_path: Path,
):
    harness = tmp_path / "harness"
    repo = tmp_path / "Droidra"

    init_repo(harness)
    init_repo(repo)

    (repo / "apps").mkdir()

    wrapper = repo / "gradlew"

    wrapper.write_text(
        "#!/usr/bin/env sh\n"
        "exit 0\n",
        encoding="utf-8",
    )

    wrapper.chmod(
        wrapper.stat().st_mode
        | 0o111
    )

    target = resolve_target(
        name="Droidra",
        harness_repo=harness,
        explicit_repo=repo,
    )

    policy = build_target_policy(
        target
    )

    profile = resolve_repository_validators(
        target_name=target.name,
        repo=target.repo,
        policy=policy,
    )

    journal = tmp_path / "journal"

    path = write_profile_record(
        profile,
        target_head=git(
            repo,
            "rev-parse",
            "HEAD",
        ),
        journal_dir=journal,
    )

    assert path.is_file()

    text = path.read_text(
        encoding="utf-8"
    )

    assert (
        '"schema": '
        '"sophyane.cross-badrpk.v2d.profile.v1"'
        in text
    )

    assert (
        '"target_name": "Droidra"'
        in text
    )
