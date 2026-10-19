from pathlib import Path
import hashlib

import pytest

from sophyane.rsi.guest_image import GuestImageBuilder, GuestImageError


def _assets(tmp_path):
    root = tmp_path / "assets"
    root.mkdir(exist_ok=True)
    (root / "sophyane-bootstrap.sh").write_text("script")
    (root / "sophyane-bootstrap.service").write_text("service")
    (root / "sophyane-fstab").write_text("fstab")
    return root


def _tool(tmp_path, code="exit 0"):
    tool = tmp_path / "virt-customize"
    tool.write_text(f"#!/bin/sh\n{code}\n")
    tool.chmod(0o755)
    return tool


def test_validate_rejects_missing_source_and_same_output(tmp_path):
    output = tmp_path / "output.img"
    with pytest.raises(GuestImageError, match="source image"):
        GuestImageBuilder(tmp_path / "missing.img", output, _tool(tmp_path), _assets(tmp_path)).validate()

    source = tmp_path / "source.img"
    source.write_bytes(b"image")
    with pytest.raises(GuestImageError, match="different"):
        GuestImageBuilder(source, source, _tool(tmp_path), _assets(tmp_path)).validate()


def test_validate_rejects_missing_image_tool(tmp_path):
    source = tmp_path / "source.img"
    source.write_bytes(b"image")

    with pytest.raises(GuestImageError, match="tool"):
        GuestImageBuilder(source, tmp_path / "output.img", tmp_path / "missing-tool", _assets(tmp_path)).validate()


def test_build_copies_source_invokes_tool_and_writes_digest_manifest(tmp_path):
    source = tmp_path / "source.img"
    source.write_bytes(b"image-bytes")
    output = tmp_path / "built.img"
    assets = _assets(tmp_path)
    tool = _tool(tmp_path)
    builder = GuestImageBuilder(source, output, tool, assets)

    manifest = builder.build()

    assert source.read_bytes() == b"image-bytes"
    assert output.read_bytes() == b"image-bytes"
    assert manifest.image == output.resolve()
    assert manifest.architecture == "aarch64"
    assert manifest.sha256 == hashlib.sha256(b"image-bytes").hexdigest()
    assert manifest.manifest_path.exists()
    assert "--upload" in builder.last_command
    assert "/etc/systemd/system/sophyane-bootstrap.service" in " ".join(builder.last_command)
    assert "/etc/fstab" in " ".join(builder.last_command)
    assert "mkdir -p /mnt/sophyane-input /mnt/sophyane-output" in " ".join(builder.last_command)


def test_build_failure_removes_partial_output_and_preserves_source(tmp_path):
    source = tmp_path / "source.img"
    source.write_bytes(b"image-bytes")
    output = tmp_path / "built.img"
    builder = GuestImageBuilder(source, output, _tool(tmp_path, "exit 7"), _assets(tmp_path))

    with pytest.raises(GuestImageError, match="image tool"):
        builder.build()

    assert source.read_bytes() == b"image-bytes"
    assert not output.exists()
