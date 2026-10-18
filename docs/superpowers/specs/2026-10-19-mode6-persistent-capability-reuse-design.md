# Mode 6 Persistent Capability Reuse

## Goal

When a Mode-6 task is authoritatively classified as a missing reusable capability, Sophyane must develop and independently verify a bounded capability, promote it through the existing host-owned boundary, retry the original task, and retain the verified capability for later matching tasks after process restart.

## Constraints

- Provider proposals remain untrusted bytes; only the existing verifier and promoter may grant trust.
- Capability records are scoped to the canonical workspace path and capability class.
- A persisted record is usable only when its exact promoted file bytes still match the workspace.
- Security, authorization, provider-availability, and sandbox failures must not enter capability development.
- Persistence must be atomic, bounded, and free of prompts, credentials, or provider responses.

## Design

Add a small JSON-backed `CapabilityStore` implementation in the failure-driven RSI module. The store keeps only the capability class, canonical workspace identity, provider label, trusted status, bounded file contents, and fingerprint. The Mode-6 controller will use this store by default, while tests can inject an in-memory store. The existing development graph remains authoritative for verification, promotion, and original-request retry; persistence occurs only after the promoter returns a trusted candidate.

On startup, records are loaded defensively. Invalid, oversized, malformed, cross-workspace, or non-trusted records are ignored. Writes use an atomic replacement and restrictive permissions where supported. The Mode-6 controller will pass its resolved workspace to the store so a capability promoted in one workspace cannot execute in another.

## Success criteria

1. A verified promoted capability is retried immediately and returns success only when the retry verifier succeeds.
2. A new controller instance can reuse that capability without invoking a provider or development worker.
3. A different workspace cannot reuse the record.
4. Corrupt persistence fails closed without crashing the task path.
