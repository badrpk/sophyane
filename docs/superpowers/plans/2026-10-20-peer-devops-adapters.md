# Peer DevOps Adapters Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Register safe, locally executable DevOps adapters for Veyron, Huobz, Rangoons, and Shmry without inferring commands or enabling destructive deployment.

**Architecture:** Add explicit ecosystem manifests and a Sophyane-owned process-adapter module. The module validates repository roots and manifests, maps named capabilities to fixed argv vectors, bounds execution, sanitizes environment, and returns `PeerCapabilityResult` evidence. Runtime registration is gated by local readiness; remote metadata never registers an adapter.

**Tech Stack:** Python standard library (`subprocess`, `json`, `pathlib`, `threading`, `time`), pytest, existing peer adapter registry.

**Spec:** `docs/superpowers/specs/2026-10-20-peer-devops-adapters-design.md`

## Global Constraints

- Do not infer executable commands from README text.
- Do not use remote repositories as execution targets.
- Use fixed argv vectors, never shell strings or shell interpolation.
- Validate configured local roots, manifests, commands, timeouts, and output limits.
- Do not enable deployment, credential rotation, deletion, cloud provisioning, or arbitrary command execution.
- Never access `shmry_economy.db` or perform a production deployment in tests or verification.
- Preserve unrelated worktree changes and stage only files owned by this plan.

## Review Focus

- Missing or remote-only peer roots must remain unavailable and unregistered; test in Task 1.
- Malformed manifests and unsupported capabilities must fail closed; test in Task 1.
- Commands containing shell metacharacters must never be interpreted by a shell; test in Task 2.
- Timeouts and oversized output must return bounded structured failures; test in Task 2.
- A non-zero command exit or missing executable must not make the peer appear execution-ready; test in Task 3.

### Task 1: Manifest schema and local peer discovery

**Files:**
- Create: `/data/data/com.termux/files/home/badrpk-repos/huobz/ecosystem.json`
- Create: `/data/data/com.termux/files/home/badrpk-repos/rangoons/ecosystem.json`
- Modify: `src/sophyane/ecosystem_contract.py`
- Modify: `src/sophyane/ecosystem_capabilities.py`
- Test: `tests/test_peer_devops_adapters.py`

Peer manifest files are separate repository changes and are not staged in the
Sophyane repository commit. Inspect each peer worktree first and preserve any
existing peer changes.

**Interfaces:**
- `load_local_manifest(repository: str, root: Path) -> EcosystemManifest`
- `discover_badrpk_capabilities(workspace: str | Path | None = None) -> tuple[RepositoryCapability, ...]`

- [ ] **Step 1: Write failing manifest tests** for Huobz and Rangoons schema validity, local root discovery through `SOPHYANE_BADRPK_ROOT`, and remote-only peers remaining `execution_ready=False`.
- [ ] **Step 2: Run the focused tests to verify RED.**

  Run: `PYTHONPATH=src ./.venv/bin/python -m pytest -q tests/test_peer_devops_adapters.py -k 'manifest or discovery'`

  Expected: failures because the two manifests and explicit local-root readiness are missing.
- [ ] **Step 3: Add manifests** with roles, capabilities, peer metadata, and an `operations` object containing only named safe operations. Write each manifest in its peer repository, preserving unrelated peer changes; do not claim capabilities without a corresponding command contract.
- [ ] **Step 4: Implement manifest loading and local-root precedence** while preserving remote discovery as metadata-only.
- [ ] **Step 5: Run the focused tests to verify GREEN.**
- [ ] **Step 6: Commit** `feat: add local peer ecosystem manifests`.

### Task 2: Guarded fixed-argv process adapter

**Files:**
- Create: `src/sophyane/peer_process_adapter.py`
- Modify: `src/sophyane/ecosystem_peer_runtime.py`
- Test: `tests/test_peer_devops_adapters.py`

**Interfaces:**
- `ProcessOperation(argv: tuple[str, ...], timeout_seconds: float, max_output_bytes: int)`
- `LocalPeerProcessAdapter(repository: str, root: Path, operations: Mapping[str, ProcessOperation])`
- `LocalPeerProcessAdapter.invoke(capability: str, objective: str, workspace: str) -> PeerCapabilityResult`
- `register_local_peer_adapters() -> tuple[str, ...]`

- [ ] **Step 1: Write failing adapter tests** for successful fixed-argv execution, unknown capability, missing executable, non-zero exit, timeout, bounded output, sanitized environment, and shell metacharacters treated as literal arguments.
- [ ] **Step 2: Run the focused tests to verify RED.**

  Run: `PYTHONPATH=src ./.venv/bin/python -m pytest -q tests/test_peer_devops_adapters.py -k 'process or command or timeout or output'`

  Expected: failures because the process adapter and registration do not exist.
- [ ] **Step 3: Implement the adapter** with `subprocess.Popen(..., shell=False, cwd=root, env=clean_env)`, monotonic timeout enforcement, bounded stdout/stderr capture, and structured evidence containing repository, capability, argv basename, exit status, duration, and truncation state.
- [ ] **Step 4: Register only validated local adapters** from manifest operations; reject missing roots, missing executables, malformed operation definitions, and unsafe operation names.
- [ ] **Step 5: Run the focused tests to verify GREEN.**
- [ ] **Step 6: Commit** `feat: add guarded local peer process adapters`.

### Task 3: Four-repository operation contracts and runtime verification

**Files:**
- Modify: `/data/data/com.termux/files/home/badrpk-repos/Veyron/ecosystem.json`
- Modify: `/data/data/com.termux/files/home/badrpk-repos/huobz/ecosystem.json`
- Modify: `/data/data/com.termux/files/home/badrpk-repos/rangoons/ecosystem.json`
- Modify: `/data/data/com.termux/files/home/badrpk-repos/shmry/ecosystem.json`
- Modify: `src/sophyane/ecosystem_peer_runtime.py`
- Create: `scripts/verify_peer_devops_adapters.py`
- Test: `tests/test_peer_devops_adapters.py`

**Interfaces:**
- `peer_runtime_status() -> dict[str, Any]` returns registered adapters only for validated local contracts.
- `verify_peer_devops_adapters() -> dict[str, Any]` reports per-peer registration, capabilities, invocation status, and evidence.

- [ ] **Step 1: Write failing integration tests** asserting the runtime catalog contains only peers whose local manifest operations pass validation, and that each of the four peers returns structured status/test/build evidence using temporary fake executables.
- [ ] **Step 2: Run the focused tests to verify RED.**

  Run: `PYTHONPATH=src ./.venv/bin/python -m pytest -q tests/test_peer_devops_adapters.py -k 'registration or runtime or verification'`

  Expected: failures because operations and verification are not wired.
- [ ] **Step 3: Inspect each repository’s existing command surface** and encode only confirmed safe operations. Veyron may use its CMake/test and non-destructive publish check; Huobz may use confirmed local service/test commands; Rangoons may use its router tests/status; Shmry may use confirmed local status/test/build commands. If a peer lacks a confirmed safe command, report it as unavailable rather than registering a fabricated adapter. Do not enable cloud-launch, deployment, credential, deletion, or arbitrary scripts.
- [ ] **Step 4: Wire runtime initialization** so `initialize_peer_adapters()` calls local registration and leaves unsupported peers explicitly unavailable.
- [ ] **Step 5: Implement the verification script** with JSON output and temporary fixture roots; it must never access production databases or mutate real repositories.
- [ ] **Step 6: Run focused tests and verification to verify GREEN.**

  Run: `PYTHONPATH=src ./.venv/bin/python -m pytest -q tests/test_peer_devops_adapters.py`

  Run: `PYTHONPATH=src ./.venv/bin/python scripts/verify_peer_devops_adapters.py`

- [ ] **Step 7: Run relevant existing tests** for ecosystem discovery and peer adapters, then run `git diff --check` and inspect staged paths.
- [ ] **Step 8: Commit** `feat: register verified peer DevOps capabilities`.

### Task 4: Final verification and handoff

- [ ] **Step 1: Run the focused adapter suite and the existing ecosystem/peer tests.**
- [ ] **Step 2: Run the verification script with the actual configured local peer root, recording unavailable capabilities rather than fabricating success.**
- [ ] **Step 3: Confirm no production database path was opened and unrelated worktree changes remain unstaged.**
- [ ] **Step 4: Request final code review before claiming completion.**
