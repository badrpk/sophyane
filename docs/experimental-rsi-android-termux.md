# Experimental RSI on Android / Termux

This execution track is separate from SSEE/Phase 4. A passing experimental
cycle is not a Phase 4 security decision and cannot satisfy its host-isolation,
signing, or promotion gates.

`tools/experimental_rsi_campaign.py` is opt-in (`--execute-candidates` is
required). It asks the configured Codex CLI for target-only proposals in a
read-only ephemeral workspace, allows one repair attempt per target, and stops
after three consecutive retained cycles or its resource budget. Each candidate
runs in a disposable ARM64 QEMU guest with no NIC, one vCPU, 512 MiB guest RAM,
bounded wall/CPU/RSS resources, a read-only candidate snapshot, a read-only
base guest disk with a disposable qcow2 overlay, and a fixed 16 MiB result disk.
Candidate code has no
Termux home, Git metadata, credentials, Android shared storage, production
services, or writable host directory mounted in the guest. The guest sees
only the explicit candidate snapshot through read-only 9p and returns results
on a fixed-size virtual disk. The QEMU build lacks its optional `-sandbox`
seccomp feature; therefore this is a bounded experimental VM run, not a
hardened Phase 4 isolation claim. Android's inherited app seccomp filter,
`-nic none`, a monitored 1 GiB QEMU RSS ceiling, and a 180-second host QEMU
CPU limit are additional controls. The base guest disk is an immutable
backing file; writes go to a disposable qcow2 overlay inside a 64 MiB per-run
budget. The whole campaign has a 512 MiB scratch cap, at most nine QEMU runs,
and at most two Codex proposals per cycle. Signing and GitHub promotion remain
independent and are not invoked by this controller.

The controller requires a median paired gain of at least 5%, six of seven
positive sample pairs, and a positive deterministic 90% bootstrap lower bound.
The current campaign began from the retained `rsi.benchmark.compare` change
and measured three distinct functions: `CommandResult.digest`,
`RSIMetrics.record`, and `RSIMetrics.level`. Each cycle runs its focused pytest
suite and seven benchmark repetitions in both baseline and candidate guests.
Cycle reports bind the next baseline to the previous retained source SHA-256.
Machine-readable evidence is saved as `experimental-rsi-report.json` in the
campaign's temporary run directory.
