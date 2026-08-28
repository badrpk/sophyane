from __future__ import annotations

from pathlib import Path

import sophyane.local_runtime as runtime


def _write_executable(
    path: Path,
    *,
    success: bool = True,
) -> Path:
    path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    exit_code = 0 if success else 1

    path.write_text(
        "#!/usr/bin/env sh\n"
        'if [ "${1:-}" = "--version" ]; then\n'
        '    echo "llama test runtime"\n'
        f"    exit {exit_code}\n"
        "fi\n"
        f"exit {exit_code}\n",
        encoding="utf-8",
    )

    path.chmod(
        0o755
    )

    return path


def test_install_llama_cpp_prefers_discovered_native_runtime(
    monkeypatch,
) -> None:
    expected = {
        "server": "/native/llama-server",
        "cli": "/native/llama-cli",
        "runtime": "/native",
    }

    monkeypatch.setattr(
        runtime,
        "_discover_native_llama_cpp",
        lambda: expected,
    )

    def forbidden_download(
        *_args,
        **_kwargs,
    ):
        raise AssertionError(
            "network download must not run "
            "when native runtime exists"
        )

    monkeypatch.setattr(
        runtime,
        "download_file",
        forbidden_download,
    )

    assert (
        runtime.install_llama_cpp()
        == expected
    )


def test_discovery_finds_portable_termux_build(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        runtime.Path,
        "home",
        lambda: tmp_path,
    )

    monkeypatch.setattr(
        runtime,
        "LLAMA_RUNTIME_DIR",
        tmp_path / "missing-runtime",
    )

    monkeypatch.setattr(
        runtime.shutil,
        "which",
        lambda _name: None,
    )

    server = _write_executable(
        tmp_path
        / "llama.cpp-termux"
        / "build-termux"
        / "bin"
        / "llama-server"
    )

    cli = _write_executable(
        server.parent
        / "llama-cli"
    )

    result = (
        runtime._discover_native_llama_cpp()
    )

    assert result is not None
    assert result["server"] == str(
        server
    )
    assert result["cli"] == str(
        cli
    )
    assert result["runtime"] == str(
        server.parent
    )


def test_broken_path_wrapper_is_not_trusted(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        runtime.Path,
        "home",
        lambda: tmp_path,
    )

    monkeypatch.setattr(
        runtime,
        "LLAMA_RUNTIME_DIR",
        tmp_path / "missing-runtime",
    )

    broken = _write_executable(
        tmp_path
        / "path-bin"
        / "llama-server",
        success=False,
    )

    monkeypatch.setattr(
        runtime.shutil,
        "which",
        lambda name: (
            str(broken)
            if name == "llama-server"
            else None
        ),
    )

    assert (
        runtime._discover_native_llama_cpp()
        is None
    )


def test_valid_path_server_can_be_reused(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        runtime.Path,
        "home",
        lambda: tmp_path,
    )

    monkeypatch.setattr(
        runtime,
        "LLAMA_RUNTIME_DIR",
        tmp_path / "missing-runtime",
    )

    server = _write_executable(
        tmp_path
        / "path-bin"
        / "llama-server"
    )

    monkeypatch.setattr(
        runtime.shutil,
        "which",
        lambda name: (
            str(server)
            if name == "llama-server"
            else None
        ),
    )

    result = (
        runtime._discover_native_llama_cpp()
    )

    assert result is not None
    assert result["server"] == str(
        server
    )
    assert result["runtime"] == str(
        server.parent
    )


def test_source_has_no_dated_backup_runtime_dependency() -> None:
    source = Path(
        runtime.__file__
    ).read_text(
        encoding="utf-8",
    )

    assert (
        "sophyane-pre-v62"
        not in source
    )
