# QEMU RSI execution

Sophyane can execute source-promotion verification in an aarch64 Linux guest
with QEMU software emulation (TCG). This backend is opt-in and is intended for
hosts such as Termux Android where Bubblewrap cannot create Linux namespaces.

## Requirements

- `qemu-system-aarch64` must be installed and available, or configured with
  `SOPHYANE_RSI_QEMU_EXECUTABLE`.
- A user-provided aarch64 guest disk image must be configured with
  `SOPHYANE_RSI_QEMU_IMAGE`.
- The guest kernel/initrd must support QEMU 9P mounts and the Sophyane guest
  bootstrap protocol. The input share is mounted read-only; the output share
  contains `result.json`.
- `/dev/kvm` is optional. Without it QEMU uses TCG and will be substantially
  slower.

## Enablement

```sh
export SOPHYANE_RSI_EXECUTION_BACKEND=qemu
export SOPHYANE_RSI_QEMU_IMAGE=/path/to/aarch64-guest.img
export SOPHYANE_RSI_QEMU_EXECUTABLE=qemu-system-aarch64
```

Optional limits:

```sh
export SOPHYANE_RSI_QEMU_TIMEOUT=300
export SOPHYANE_RSI_QEMU_OUTPUT_LIMIT=1048576
export SOPHYANE_RSI_QEMU_SCRATCH="$HOME/.local/state/sophyane/qemu-scratch"
```

If the backend is not explicitly set to `qemu`, Sophyane returns no QEMU
runner and retains the normal execution path. If QEMU, the guest image, or the
exchange configuration is invalid, the run fails closed; it never falls back
to unrestricted host execution.

## Result statuses

- `passed`: guest exited successfully and returned a valid passed result.
- `failed`: QEMU could not start or the guest returned a non-zero status.
- `timeout`: the bounded guest timeout expired and QEMU was terminated.
- `invalid`: the result bundle or diagnostics exceeded validation limits or
  did not match the required schema.

These statuses are evidence only. Existing RSI red/green, holdout, regression,
benchmark, smoke, health, authority, and isolation gates still decide whether
source promotion is allowed.

