# Guarded executable RSI bridge

## Scope

This design connects Mode-6 diagnostic observations to the existing guarded
RSI controller without changing the authority model. An observation remains
`trusted=False`, `instruction_authority=False`, and `mutation_authority=False`.
Recording an observation never grants execution authority.

The bridge validates non-empty, grounded evidence and a relevant component,
then constructs the existing `WeaknessRecord`. Only an explicit executor or
bounded campaign may invoke the existing controller. Normal Mode-6 chat only
records the improvement ledger and never starts an RSI loop.

## Authority

Source mutation remains restricted to `codex_cli` and `nifdu_browser`, in the
existing `CODING_PROVIDER_ORDER`. `local_gguf` remains read-only. Provider
selection remains owned by `CodingRouter`; a bridge cannot override its
provider or bypass `require(...)`. Stale Gemini/AGY configuration is not an
RSI mutation provider.

## Evidence and gates

The bridge preserves source evidence and rejects authority-bearing,
empty, ungrounded, or irrelevant observations. Mechanical weaknesses require
host-adjudicated genuine RED evidence: an already-green reproducer is not RED;
unrelated or flaky evidence is rejected; conceptual weaknesses may use
`RED_UNAVAILABLE` only with an independent measurable benchmark. The coding
provider cannot self-certify RED.

Acceptance requires authority, grounded weakness, valid RED, focused GREEN,
frozen holdout GREEN, no material regression, authorized files, and unchanged
authority. Rejected candidates never become the next accepted generation.
Evidence for accepted and rejected generations is retained.

## Frozen bounded campaigns

`run_campaign(..., max_generations=N)` is explicit and enforces `1 <= N <= 20`.
The benchmark manifest contains regression, holdout, meta-improvement checks,
and scoring weights. Its SHA-256 digest is fixed at campaign start and checked
before every generation; candidate code cannot rewrite it or benchmark paths.
Each generation records weakness, hypothesis, provider, RED/GREEN/holdout,
scores, meta-scores, verdict, reasons, fingerprints, and timing in a dedicated
JSONL campaign ledger and summary.

Stopping signals are deterministic where defensible: `PLATEAU` (three
attempts without meaningful improvement), `META_PLATEAU` (two accepted
generations with non-positive meta delta), `CYCLING`, `TEST_GAMING`,
`CODE_BLOAT`, `AUTHORITY_VIOLATION`, `REGRESSION`, `RSI_HANDOFF_BREAK`,
`NO_AUTONOMOUS_IMPROVEMENT`, `CONTEXT_DECAY`, `TOOL_PROTOCOL_FAILURE`, and
`MAX_GENERATIONS`. There is no unbounded loop.

## Claims

Self-repair means one accepted repair; recursive self-improvement requires
repeated accepted repairs and measurement. Evidence levels are 0 (no
autonomous modification), 1 (self-repair), 2 (repeated self-repair), 3
(measurable general capability improvement), and 4 (measurable improvement in
Sophyane's ability to improve itself). Level 4 is never inferred from the
existence of this engine, generation count, changed lines, or added tests.
