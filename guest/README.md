# Sophyane guest bootstrap

This directory contains the one-shot service installed into a Debian arm64
guest image used by QEMU RSI.

The image must provide Python 3, systemd, and 9P support. The host exposes
read-only `sophyane-input` and writable `sophyane-output` shares. The guest
mounts them at `/mnt/sophyane-input` and `/mnt/sophyane-output` before starting
`sophyane-bootstrap.service`.

The image builder installs `/etc/fstab.d/sophyane.conf` for those 9P tags and
creates both mount points. It leaves the source image unchanged; use the
derived image and its SHA-256 manifest for QEMU RSI.

The service accepts one argv-only task from `task.json`, never invokes a shell,
and atomically writes one bounded `result.json`. It is a oneshot service and
does not restart or enable networking.

Install through the copy-only image builder with an explicitly configured
`virt-customize`-compatible tool. Do not edit the active source image in place.
