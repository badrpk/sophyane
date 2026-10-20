# Peer DevOps Adapter Integration

## Goal

Allow Sophyane to invoke a bounded set of DevOps capabilities in the local
Veyron, Huobz, Rangoons, and Shmry repositories through explicit, auditable
peer adapters.

## Scope

The first integration is local-process based. It does not infer commands from
README text, use remote repositories as execution targets, or enable
destructive deployment operations. Each peer receives a local
`ecosystem.json` manifest declaring its role, capabilities, and adapter
operations. Sophyane only registers an adapter when the configured local root,
manifest, command executable, and repository contract are valid.

The local peer root is configured by `SOPHYANE_BADRPK_ROOT`, defaulting to the
repository's existing local peer directory when present. Remote discovery may
describe capabilities but never makes a peer execution-ready.

## Adapter contract

Each adapter accepts `(capability, objective, workspace)` and returns the
existing `PeerCapabilityResult` shape. Operations are allowlisted per peer and
map to fixed argv vectors, never shell strings. The adapter:

- validates the peer root is the expected directory;
- runs only declared commands with a bounded timeout and output size;
- uses a sanitized environment and never forwards credentials from the
  objective;
- records command, repository, exit status, duration, and bounded output as
  evidence;
- returns explicit unavailable, timeout, or failed results;
- rejects unknown capabilities and destructive operations by default.

The initial operations are read-only or verification-oriented: `status`,
`test`, `build`, and existing publish/configuration checks where the peer
already exposes a safe script. Deployment, credential rotation, deletion,
cloud provisioning, and arbitrary command execution remain disabled until a
separate reviewed contract exists.

## Repository contracts

- Veyron: use its CMake build/test surface and `deploy/publish-check.sh` only
  after confirming the script is non-destructive and local prerequisites exist.
- Huobz: select explicit existing service-manager or test commands from the
  repository, with no cloud-launch scripts enabled by default.
- Rangoons: use its router test/status surface and add a manifest describing
  the supported operations; do not treat arbitrary subprojects as services.
- Shmry: use explicit local status/test/build surfaces; require deployment
  configuration for runtime endpoints and never embed credentials.

If a peer lacks a stable safe command, its adapter remains registered only for
capabilities that can be verified, or is omitted with an evidence-backed
unavailable status. `registered_adapters` must not claim readiness merely from
metadata.

## Verification

Tests will use temporary fixture repositories and fake executables to verify:

- all four manifests validate;
- local-root discovery is distinct from remote metadata discovery;
- adapter registration is gated by executable and contract checks;
- success, non-zero exit, timeout, oversized output, unknown capability, and
  missing-root paths return structured results;
- no shell interpolation or credential leakage occurs;
- the runtime catalog contains only genuinely executable adapters;
- a verification script reports per-peer capability and invocation evidence.

No test or verification command may access `shmry_economy.db` or perform a
production deployment.
