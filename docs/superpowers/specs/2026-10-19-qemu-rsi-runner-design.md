# QEMU RSI Runner Design

## Goal

Enable Sophyane to execute source-improvement candidates inside a dedicated
minimal Linux guest using QEMU software emulation (TCG) when Bubblewrap and
kernel namespaces are unavailable, while preserving fail-closed promotion
semantics.

## Context and constraints

- The current host is Termux Android on aarch64.
- `qemu-system-aarch64` is installed, but `/dev/kvm` is unavailable; execution
  will use TCG and may be slow.
- Bubblewrap cannot create its namespace inside the current `proot` Debian
  environment.
- Generated candidate code must not execute directly against the host
  repository or host filesystem.
- QEMU must be opt-in until the backend is fully verified.
- A missing, invalid, or incompatible guest image must stop execution rather
  than fall back to unrestricted host execution.

## Architecture

### Runner boundary

Add a focused `QemuRsiRunner` implementing the existing candidate-execution
boundary used by source promotion. It accepts an immutable candidate workspace,
an explicit test command, timeout, and guest-image configuration. It returns a
structured result containing exit status, stdout, stderr, timeout state, and a
run identifier.

The runner will construct QEMU arguments centrally and execute only the guest
bootstrap/runner protocol. It will not accept arbitrary host shell fragments.

### Guest image

The guest image is an external, user-provided artifact. Configuration must
identify its path and architecture. Startup validation checks that the image
exists, is a regular file, and matches the configured architecture metadata.
Image creation and distribution are outside this change.

### Candidate exchange

The host creates a temporary, read-only candidate bundle containing the
candidate source and an allowlisted task manifest. The guest receives this
bundle through the chosen QEMU transport and writes only a result bundle to a
separate host-owned output location. The host never exposes the live checkout
as a writable guest filesystem.

The initial transport will use two QEMU 9P shares: a read-only input share for
the candidate bundle and a separate output share for the guest result. The
guest image must provide a kernel/initrd with 9P support. The runner must
reject paths outside its designated scratch directory.

### Promotion flow

1. Validate runner configuration and guest image.
2. Freeze the candidate and create an isolated exchange bundle.
3. Boot QEMU with TCG and a bounded timeout.
4. Execute only the manifest command inside the guest.
5. Validate and parse the result bundle.
6. Run existing host-side promotion checks.
7. Promote only when all checks pass; otherwise discard the candidate and
   preserve the active commit.

No result from the guest is sufficient by itself to promote source. Existing
red/green, holdout, regression, benchmark, smoke, and health checks remain
authoritative.

## Safety requirements

- No host fallback if QEMU is unavailable or fails to boot.
- No writable bind of the live repository into the guest.
- No unrestricted host command execution through the runner API.
- Per-run timeout, output-size limit, and scratch-directory cleanup.
- Unique run identifiers and durable failure diagnostics.
- Explicit opt-in configuration flag for the QEMU backend.
- Reject malformed result bundles and non-zero guest bootstrap status.

## Testing strategy

Tests will be written before implementation and will cover:

- deterministic QEMU command construction with TCG flags;
- rejection of missing or non-regular guest images;
- rejection of exchange paths outside the runner scratch root;
- timeout and non-zero guest exit handling;
- malformed and oversized result bundles;
- successful result parsing without launching a real VM;
- integration with source promotion proving failed guest runs cannot change
  the active commit.

The real QEMU binary will be exercised only by an explicit opt-in integration
test and will not be required for the default test suite.

## Non-goals

- Building or downloading a guest image automatically.
- Enabling hardware acceleration on Android.
- Replacing the existing Bubblewrap backend.
- Treating model guardrails as a substitute for OS isolation.
- Making the QEMU runner the default execution backend in this change.
