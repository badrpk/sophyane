# Sophyane 20 — Platform Stabilization & Engineering Foundation

Sophyane 20 develops six workstreams together behind one executable release gate.

## Workstreams

1. **Runtime** — central provider state, truthful heartbeats, packaging and launcher verification.
2. **Repository** — indexing, symbols, checkpoints, rollback and compaction.
3. **COI** — task contracts, permission-aware agents, dependency queues, events and run records.
4. **Sandbox** — workspace-only paths, capability manifests and bounded execution contracts.
5. **Evaluation** — deterministic artifact checks and persisted reports.
6. **Prompting** — concise advice, explicit acceptance criteria and reusable task templates.

## Verified commands

```bash
sophyane --version
sophyane-platform status
sophyane-coi status
sophyane-release status
```

The universal installer creates explicit wrappers for these commands and refuses to complete an update if any launcher or import gate fails.

## Release gate

```bash
sophyane-release gate /path/to/sophyane
# or
sophyane-platform gate /path/to/sophyane
```

The gate checks required modules, installed commands, platform filesystem, current documentation, repository indexing, coded sandbox preparation, prompt advice and the evaluation engine. It emits machine-readable JSON and a score.

## Repository and sandbox

```bash
sophyane-platform index .
sophyane-platform checkpoint .
sophyane-platform rollback SNAPSHOT_ID .
sophyane-platform sandbox ./workspace
sophyane-platform eval .
sophyane-platform compact ~/.sophyane
```

## COI scheduling

```bash
sophyane-coi task "Implement login" --priority 80 --permission read --permission write --validate tests
sophyane-coi queue
sophyane-coi agent-manifest coder --role coding --permission read --permission write --tool filesystem
```

COI protocol version 2 persists priority queues, dependencies, permissions, events and completed run records. MCP remains the external tool interoperability layer.

## Provider truth

The dispatcher and TUI now share a thread-safe provider state. Validator rescue publishes the actual active provider, so heartbeat output can change from `local_gguf` to `gemini` while Gemini owns the repair sequence and return to local only when the sequence ends.

## Release policy

A release is not ready until launchers, imports, documentation and baseline engines pass together. The gate is an initial foundation; platform-specific CI, installer matrix tests and full benchmarks remain continuing stabilization work.
