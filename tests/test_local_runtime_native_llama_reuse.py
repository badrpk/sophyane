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

    result = runtime.install_llama_cpp()

    assert result["server"] == expected["server"]
    assert result["cli"] == expected["cli"]
    assert result["runtime"] == expected["runtime"]
    assert result["acquisition"] == "reused"


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



class _FakeResponse:
    def __init__(
        self,
        payload: str,
    ) -> None:
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(
        self,
        exc_type,
        exc,
        tb,
    ):
        return False

    def read(self) -> bytes:
        return self.payload.encode(
            "utf-8"
        )


def _profile(
    *,
    os_name: str,
    arch: str = "aarch64",
) -> runtime.HardwareProfile:
    return runtime.HardwareProfile(
        arch=arch,
        cpus=8,
        ram_mb=8192,
        disk_free_mb=20000,
        os_name=os_name,
        virtualization="unknown",
    )


def test_stable_release_resolves_advertised_binary_build(
    monkeypatch,
) -> None:
    latest = {
        "tag_name": "v0.4.0",
        "assets": [],
        "body": (
            "Nightly build: "
            "https://github.com/ggml-org/llama.cpp/"
            "releases/tag/b10809"
        ),
    }

    build = {
        "tag_name": "b10809",
        "assets": [
            {
                "name": (
                    "llama-b10809-bin-"
                    "android-arm64.tar.gz"
                ),
                "browser_download_url": (
                    "https://example.invalid/"
                    "llama-b10809-bin-"
                    "android-arm64.tar.gz"
                ),
            },
        ],
    }

    def fake_urlopen(
        url,
        timeout=30,
    ):
        del timeout
        url = str(url)

        if url.endswith(
            "/releases/latest"
        ):
            return _FakeResponse(
                __import__("json").dumps(
                    latest
                )
            )

        if url.endswith(
            "/releases/tags/b10809"
        ):
            return _FakeResponse(
                __import__("json").dumps(
                    build
                )
            )

        raise AssertionError(
            f"unexpected URL: {url}"
        )

    monkeypatch.setattr(
        runtime,
        "_urlopen",
        fake_urlopen,
    )

    tag, asset, url = (
        runtime._resolve_llama_cpp_binary_release(
            _profile(
                os_name="android"
            )
        )
    )

    assert tag == "b10809"
    assert (
        asset
        == "llama-b10809-bin-android-arm64.tar.gz"
    )
    assert (
        "ubuntu-arm64"
        not in asset
    )
    assert url.endswith(
        asset
    )


def test_android_arm64_asset_is_not_ubuntu() -> None:
    asset = runtime._llama_cpp_asset_name(
        _profile(
            os_name="android"
        ),
        "b10809",
    )

    assert (
        asset
        == "llama-b10809-bin-android-arm64.tar.gz"
    )
    assert "ubuntu-arm64" not in asset


def test_linux_arm64_asset_uses_ubuntu_build() -> None:
    assert (
        runtime._llama_cpp_asset_name(
            _profile(
                os_name="linux"
            ),
            "b10809",
        )
        == "llama-b10809-bin-ubuntu-arm64.tar.gz"
    )


def _configure_fake_install(
    tmp_path,
    monkeypatch,
    *,
    binary_success: bool,
) -> None:
    models = tmp_path / "models"
    llama_dir = models / "llama.cpp"
    runtime_dir = llama_dir / "runtime"
    bin_dir = tmp_path / "bin"

    monkeypatch.setattr(
        runtime,
        "MODELS_DIR",
        models,
    )
    monkeypatch.setattr(
        runtime,
        "LLAMA_DIR",
        llama_dir,
    )
    monkeypatch.setattr(
        runtime,
        "LLAMA_RUNTIME_DIR",
        runtime_dir,
    )
    monkeypatch.setattr(
        runtime,
        "BIN_DIR",
        bin_dir,
    )
    monkeypatch.setattr(
        runtime,
        "profile_hardware",
        lambda: _profile(
            os_name="android"
        ),
    )
    monkeypatch.setattr(
        runtime,
        "_resolve_llama_cpp_binary_release",
        lambda _profile: (
            "b10809",
            "llama-b10809-bin-android-arm64.tar.gz",
            "https://example.invalid/runtime.tar.gz",
        ),
    )

    def fake_download(
        urls,
        destination,
        **kwargs,
    ):
        del urls, kwargs
        destination.parent.mkdir(
            parents=True,
            exist_ok=True,
        )
        destination.write_bytes(
            b"x" * (1024 * 101)
        )
        return destination

    monkeypatch.setattr(
        runtime,
        "download_file",
        fake_download,
    )

    real_run = runtime._run

    def fake_run(
        cmd,
        *,
        timeout=None,
        env=None,
    ):
        if cmd and cmd[0] == "tar":
            server = _write_executable(
                runtime_dir
                / "llama-server",
                success=binary_success,
            )
            _write_executable(
                server.parent
                / "llama-cli",
                success=binary_success,
            )

            return __import__(
                "subprocess"
            ).CompletedProcess(
                cmd,
                0,
                "",
                "",
            )

        return real_run(
            cmd,
            timeout=timeout,
            env=env,
        )

    monkeypatch.setattr(
        runtime,
        "_run",
        fake_run,
    )


def test_newly_acquired_runtime_is_classified_installed(
    tmp_path,
    monkeypatch,
) -> None:
    _configure_fake_install(
        tmp_path,
        monkeypatch,
        binary_success=True,
    )

    result = runtime.install_llama_cpp(
        force=True
    )

    assert result["acquisition"] == "installed"
    assert Path(
        result["server"]
    ).is_file()
    assert Path(
        result["cli"]
    ).is_file()


def test_acquired_runtime_with_failing_version_is_rejected(
    tmp_path,
    monkeypatch,
) -> None:
    _configure_fake_install(
        tmp_path,
        monkeypatch,
        binary_success=False,
    )

    try:
        runtime.install_llama_cpp(
            force=True
        )
    except RuntimeError as error:
        assert (
            "failed --version"
            in str(error)
        )
    else:
        raise AssertionError(
            "incompatible llama.cpp runtime was accepted"
        )


def _ensure_action_for_acquisition(
    tmp_path,
    monkeypatch,
    acquisition: str,
) -> list[str]:
    profile = _profile(
        os_name="android"
    )

    spec = runtime.HfGgufSpec(
        key="test",
        repo="example/test",
        filename="test.gguf",
        size_mb=1,
        min_ram_mb=1,
        notes="test",
    )

    gguf = tmp_path / "test.gguf"
    gguf.write_bytes(
        b"gguf"
    )

    monkeypatch.setattr(
        runtime,
        "profile_hardware",
        lambda: profile,
    )
    monkeypatch.setattr(
        runtime,
        "choose_hf_gguf",
        lambda _profile: spec,
    )
    monkeypatch.setattr(
        runtime,
        "download_hf_gguf",
        lambda _spec, progress=None: gguf,
    )
    monkeypatch.setattr(
        runtime,
        "install_llama_cpp",
        lambda progress=None: {
            "server": "/fake/server",
            "cli": "/fake/cli",
            "runtime": "/fake",
            "acquisition": acquisition,
        },
    )
    monkeypatch.setattr(
        runtime,
        "start_llama_server",
        lambda *args, **kwargs: None,
    )
    monkeypatch.setattr(
        runtime,
        "persist_gguf_state",
        lambda **kwargs: None,
    )
    monkeypatch.setattr(
        runtime,
        "persist_local_provider",
        lambda *args, **kwargs: None,
    )
    monkeypatch.setattr(
        runtime,
        "_http_json",
        lambda *args, **kwargs: {},
    )

    result = (
        runtime.ensure_hf_gguf_runtime()
    )

    assert result.ok is True
    return result.actions


def test_ensure_runtime_reports_reuse_truthfully(
    tmp_path,
    monkeypatch,
) -> None:
    actions = (
        _ensure_action_for_acquisition(
            tmp_path,
            monkeypatch,
            "reused",
        )
    )

    assert "llama_cpp_reused" in actions
    assert (
        "llama_cpp_installed"
        not in actions
    )


def test_ensure_runtime_reports_install_truthfully(
    tmp_path,
    monkeypatch,
) -> None:
    actions = (
        _ensure_action_for_acquisition(
            tmp_path,
            monkeypatch,
            "installed",
        )
    )

    assert "llama_cpp_installed" in actions
    assert (
        "llama_cpp_reused"
        not in actions
    )
