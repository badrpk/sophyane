"""Copy-only builder for a Sophyane-enabled external guest image."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
from pathlib import Path
import shutil
import subprocess


class GuestImageError(RuntimeError):
    """Guest image preparation failed without modifying the source image."""


@dataclass(frozen=True)
class GuestImageManifest:
    image: Path
    architecture: str
    sha256: str
    manifest_path: Path


class GuestImageBuilder:
    def __init__(self, source_image, output_image, tool, asset_root):
        self.source_image = Path(source_image).resolve()
        self.output_image = Path(output_image).resolve()
        self.tool = Path(tool).resolve()
        self.asset_root = Path(asset_root).resolve()
        self.last_command: tuple[str, ...] = ()

    def validate(self) -> None:
        if not self.source_image.is_file():
            raise GuestImageError(f"source image must be a regular file: {self.source_image}")
        if self.source_image == self.output_image:
            raise GuestImageError("output image must be different from source image")
        if self.output_image.exists():
            raise GuestImageError(f"output image already exists: {self.output_image}")
        if not self.tool.is_file() or not self.tool.stat().st_mode & 0o111:
            raise GuestImageError(f"image tool is unavailable or not executable: {self.tool}")
        for name in (
            "sophyane-bootstrap.sh", "sophyane-bootstrap.service", "sophyane-fstab",
            "sophyane-init.sh",
            "mnt-sophyane\\x2dinput.mount", "mnt-sophyane\\x2doutput.mount",
        ):
            if not (self.asset_root / name).is_file():
                raise GuestImageError(f"guest asset is missing: {name}")

    def _digest(self) -> str:
        digest = hashlib.sha256()
        with self.output_image.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    def build(self) -> GuestImageManifest:
        self.validate()
        self.output_image.parent.mkdir(parents=True, exist_ok=True)
        try:
            shutil.copy2(self.source_image, self.output_image)
            self.last_command = (
                str(self.tool), "-a", str(self.output_image),
                "--mkdir", "/usr/local/lib/sophyane",
                "--mkdir", "/etc/fstab.d",
                "--upload", f"{self.asset_root / 'sophyane-bootstrap.sh'}:/usr/local/lib/sophyane/sophyane-bootstrap.sh",
                "--upload", f"{self.asset_root / 'sophyane-init.sh'}:/usr/local/lib/sophyane/sophyane-init.sh",
                "--upload", f"{self.asset_root / 'sophyane-bootstrap.service'}:/etc/systemd/system/sophyane-bootstrap.service",
                "--upload", f"{self.asset_root / 'sophyane-fstab'}:/etc/fstab.d/sophyane.conf",
                "--upload", f"{self.asset_root / 'mnt-sophyane\\x2dinput.mount'}:/etc/systemd/system/mnt-sophyane\\x2dinput.mount",
                "--upload", f"{self.asset_root / 'mnt-sophyane\\x2doutput.mount'}:/etc/systemd/system/mnt-sophyane\\x2doutput.mount",
                "--run-command", "chmod 0755 /usr/local/lib/sophyane/sophyane-bootstrap.sh",
                "--run-command", "chmod 0755 /usr/local/lib/sophyane/sophyane-init.sh",
                "--run-command", "mkdir -p /mnt/sophyane-input /mnt/sophyane-output",
                "--run-command", "sed -i '/[[:space:]]\\/boot\\/efi[[:space:]]/s/^/#/' /etc/fstab",
                "--run-command", "systemctl enable mnt-sophyane\\\\x2dinput.mount mnt-sophyane\\\\x2doutput.mount sophyane-bootstrap.service",
            )
            subprocess.run(self.last_command, check=True, capture_output=True, text=True)
        except (OSError, subprocess.CalledProcessError) as error:
            self.output_image.unlink(missing_ok=True)
            raise GuestImageError(f"image tool failed: {error}") from error
        manifest_path = self.output_image.with_name(self.output_image.name + ".manifest.json")
        manifest = GuestImageManifest(self.output_image, "aarch64", self._digest(), manifest_path)
        manifest_path.write_text(json.dumps(asdict(manifest), default=str, sort_keys=True), encoding="utf-8")
        return manifest
