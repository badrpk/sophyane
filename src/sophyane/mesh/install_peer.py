"""Install / clone Sophyane onto a discovered peer (network SSH or Android ADB)."""

from __future__ import annotations

import os
import shlex
import subprocess
import textwrap
from dataclasses import asdict, dataclass
from typing import Any

from sophyane.mesh.discovery import PeerInfo


INSTALL_SNIPPET = r"""
set -e
export SOPHYANE_HOME="${SOPHYANE_HOME:-$HOME/.local/share/sophyane}"
export PATH="$HOME/.local/bin:$PATH"
if command -v curl >/dev/null 2>&1; then
  curl -fsSL https://raw.githubusercontent.com/badrpk/sophyane/main/install.sh | sh
elif command -v wget >/dev/null 2>&1; then
  wget -qO- https://raw.githubusercontent.com/badrpk/sophyane/main/install.sh | sh
else
  echo "curl or wget required" >&2
  exit 1
fi
# start mesh API if possible
nohup sophyane --mesh-serve >/tmp/sophyane-mesh.log 2>&1 &
echo "SOPHYANE_CLONE_OK"
"""


@dataclass
class InstallResult:
    ok: bool
    peer_id: str
    transport: str
    message: str
    log: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def install_on_peer(
    peer: PeerInfo,
    *,
    ssh_user: str = "",
    approve: bool = False,
) -> InstallResult:
    """Clone Sophyane onto peer. Requires explicit approve=True."""
    if not approve:
        return InstallResult(
            False,
            peer.peer_id,
            peer.transport,
            "Refused: pass approve=True / --yes to install a Sophyane clone on a peer",
        )

    if peer.transport == "adb":
        return _install_adb(peer)
    if peer.transport in {"lan", "manual"} and peer.addresses:
        return _install_ssh(peer, ssh_user=ssh_user or os.environ.get("USER", "root"))
    if peer.transport == "usb":
        return InstallResult(
            False,
            peer.peer_id,
            peer.transport,
            "USB serial peers need a gateway OS with SSH/ADB. "
            "Connect the device as a Linux/Android host, then re-run discovery.",
            log=str(peer.capabilities),
        )
    return InstallResult(False, peer.peer_id, peer.transport, "Unsupported transport for install")


def _install_ssh(peer: PeerInfo, *, ssh_user: str) -> InstallResult:
    host = peer.addresses[0]
    target = f"{ssh_user}@{host}" if ssh_user else host
    remote = textwrap.dedent(INSTALL_SNIPPET)
    cmd = [
        "ssh",
        "-o",
        "BatchMode=yes",
        "-o",
        "StrictHostKeyChecking=accept-new",
        "-o",
        "ConnectTimeout=8",
        target,
        "bash",
        "-s",
    ]
    try:
        completed = subprocess.run(
            cmd,
            input=remote,
            text=True,
            capture_output=True,
            timeout=600,
            check=False,
        )
    except FileNotFoundError:
        return InstallResult(False, peer.peer_id, "lan", "ssh client not available")
    except subprocess.TimeoutExpired:
        return InstallResult(False, peer.peer_id, "lan", "ssh install timed out")

    log = (completed.stdout or "") + "\n" + (completed.stderr or "")
    ok = completed.returncode == 0 and "SOPHYANE_CLONE_OK" in log
    return InstallResult(
        ok,
        peer.peer_id,
        "lan",
        "Installed Sophyane clone over SSH" if ok else f"SSH install failed (exit {completed.returncode})",
        log=log[-4000:],
    )


def _install_adb(peer: PeerInfo) -> InstallResult:
    serial = peer.addresses[0] if peer.addresses else peer.hostname
    # Prefer Termux bootstrap if present; otherwise push install script for user shell.
    script = textwrap.dedent(
        """
        export PREFIX="${PREFIX:-/data/data/com.termux/files/usr}"
        export HOME="${HOME:-/data/data/com.termux/files/home}"
        export PATH="$PREFIX/bin:$PATH"
        if command -v pkg >/dev/null 2>&1; then
          pkg install -y curl git python 2>/dev/null || true
        fi
        curl -fsSL https://raw.githubusercontent.com/badrpk/sophyane/main/install.sh | sh
        echo SOPHYANE_CLONE_OK
        """
    )
    try:
        push = subprocess.run(
            ["adb", "-s", serial, "shell", "sh", "-s"],
            input=script,
            text=True,
            capture_output=True,
            timeout=600,
            check=False,
        )
    except FileNotFoundError:
        return InstallResult(False, peer.peer_id, "adb", "adb not installed on this host")
    except subprocess.TimeoutExpired:
        return InstallResult(False, peer.peer_id, "adb", "adb install timed out")

    log = (push.stdout or "") + "\n" + (push.stderr or "")
    ok = push.returncode == 0 and "SOPHYANE_CLONE_OK" in log
    return InstallResult(
        ok,
        peer.peer_id,
        "adb",
        "Installed Sophyane clone via ADB/Termux" if ok else "ADB install failed — is Termux installed?",
        log=log[-4000:],
    )
