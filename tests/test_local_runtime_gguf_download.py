from pathlib import Path

import sophyane.local_runtime as runtime


def _spec():
    return runtime.HfGgufSpec(
        key="test-model",
        repo="owner/repo",
        filename="test-model.gguf",
        size_mb=8,
        min_ram_mb=1,
        notes="test",
        github_mirrors=(
            (
                "owner/mirror",
                "v1",
                "test-model.gguf",
            ),
        ),
    )


def test_absent_gguf_invokes_downloader(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setattr(
        runtime,
        "GGUF_DIR",
        tmp_path,
    )

    calls = []

    def fake_download(
        urls,
        dest,
        *,
        progress=None,
        min_bytes=0,
    ):
        calls.append(
            (
                list(urls),
                Path(dest),
                min_bytes,
            )
        )
        return Path(dest)

    monkeypatch.setattr(
        runtime,
        "download_file",
        fake_download,
    )

    spec = _spec()

    result = runtime.download_hf_gguf(
        spec
    )

    assert result == (
        tmp_path
        / spec.filename
    )
    assert len(calls) == 1

    urls, dest, minimum = calls[0]

    assert dest == result
    assert spec.hf_urls()[0] in urls
    assert spec.github_urls()[0] in urls
    assert minimum >= 1024 * 1024


def test_existing_valid_gguf_is_reused(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setattr(
        runtime,
        "GGUF_DIR",
        tmp_path,
    )

    spec = _spec()
    target = (
        tmp_path
        / spec.filename
    )

    target.write_bytes(
        b"x"
        * (
            2
            * 1024
            * 1024
        )
    )

    def forbidden(*args, **kwargs):
        raise AssertionError(
            "existing GGUF must not redownload"
        )

    monkeypatch.setattr(
        runtime,
        "download_file",
        forbidden,
    )

    assert (
        runtime.download_hf_gguf(
            spec
        )
        == target
    )



def test_nano_smollm_catalog_points_to_public_gguf():
    spec = next(
        item
        for item in runtime.HF_GGUF_CATALOG["nano"]
        if item.key == "smollm2-135m"
    )

    assert (
        spec.repo
        == "bartowski/SmolLM2-135M-Instruct-GGUF"
    )
    assert (
        spec.filename
        == "SmolLM2-135M-Instruct-Q8_0.gguf"
    )

    urls = spec.hf_urls()

    assert urls
    assert (
        "bartowski/SmolLM2-135M-Instruct-GGUF"
        in urls[0]
    )
    assert (
        "SmolLM2-135M-Instruct-Q8_0.gguf"
        in urls[0]
    )
