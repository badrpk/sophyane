# Sophyane Guest Bootstrap Design

## Goal

Provide a minimal guest-side service that receives one host-approved RSI task,
executes it inside the Debian arm64 QEMU guest, and returns a bounded,
validated result bundle without granting the guest write access to the host
repository.

## Protocol

The host creates two 9P shares per run:

- `sophyane-input` — read-only; contains `task.json` and a read-only candidate
  tree under `candidate/`.
- `sophyane-output` — separate writable result directory; the guest may create
  only `result.json` and bounded diagnostic output there.

`task.json` contains a task id, an argv command, and the guest working
directory. The guest accepts only argv arrays, rejects empty or string commands,
rejects path traversal in the working directory, and applies a fixed command
allowlist. It never evaluates shell syntax or executes a host path.

`result.json` contains the task id, status, exit code, bounded stdout/stderr,
and a schema version. The host remains authoritative: a valid guest result is
evidence only and cannot bypass existing RSI gates.

## Guest service

Add:

- `guest/sophyane-bootstrap.sh` — strict shell bootstrap and one-shot runner.
- `guest/sophyane-bootstrap.service` — systemd oneshot service with bounded
  resource and dependency settings.
- `guest/README.md` — guest prerequisites and image installation instructions.

The service waits for the 9P mounts, validates the manifest, executes one task,
writes exactly one result, and exits. It does not enable networking for the
task and does not persist candidate changes.

## Image builder

Add a host-side builder that operates on a copy of a Debian arm64 image only.
It must:

1. Refuse a missing or non-regular source image.
2. Copy the image to a dedicated output path.
3. Install the service and bootstrap script into the guest filesystem using an
   explicitly configured image-editing tool (`virt-customize` or equivalent).
4. Enable the service and emit a manifest containing image path, architecture,
   and SHA-256 digest.
5. Never modify the active source image in place.

If the image-editing tool is unavailable, the builder fails with installation
instructions; it must not fall back to mounting or modifying the host tree.

## Host integration

The QEMU runner will place the manifest in the input share and expect the
guest service to create `result.json`. The runner will reject missing,
duplicate, malformed, or oversized results. Existing timeout, cleanup,
promotion, rollback, and health checks remain unchanged.

## Safety requirements

- No shell interpolation of task commands.
- No writable host-repository share.
- One task per guest boot.
- Bounded execution time and output size.
- Fail closed on unavailable image builder, service, mount, or result.
- Guest image is treated as an external artifact and verified by digest.

## Testing

- Manifest schema and argv allowlist tests.
- Bootstrap rejection tests for shell strings, traversal, empty argv, and
  oversized output.
- Service-file contract tests.
- Image-builder tests for copy-only behavior, missing tooling, and digest
  manifest generation.
- QEMU runner integration tests for missing and malformed guest results.

## Non-goals

- Automatically downloading arbitrary guest images.
- Enabling guest networking for RSI tasks.
- Giving the guest write access to the host checkout.
- Treating the guest service as a replacement for host-side promotion gates.

