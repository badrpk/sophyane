# Sophyane benchmarking

Sophyane distinguishes between three different benchmark layers:

1. **Deterministic platform checks** — repository operations, language execution, orchestration, permissions, persistence and validator behavior.
2. **Live provider checks** — whether the configured model can produce a complete artifact under the same acceptance contract.
3. **Head-to-head engineering harnesses** — two systems receive the same model, task, timeout, workspace isolation and scoring rules.

These layers should not be mixed into one unsupported ranking.

## Bundled product benchmark

Run:

```bash
sophyane-benchmark
```

Write the report to disk:

```bash
sophyane-benchmark --output ~/sophyane-tests/sophyane-baseline.json
```

Include a configured provider:

```bash
sophyane-benchmark --live --output ~/sophyane-tests/sophyane-live.json
```

## Current recorded offline baseline

The recorded Sophyane 21.x baseline produced:

```text
passed: 21
failed: 0
skipped: 2
score: 100.0
```

The two skipped checks were environment-dependent:

- Node.js execution when Node was unavailable on the host.
- Live provider generation when `--live` was not supplied.

This score applies only to the bundled checks that actually ran. It is not a universal measure of coding intelligence.

## Covered capabilities

The bundled suite checks:

- Complete browser-product artifacts
- Responsive viewport behavior
- Game controls and visible state
- Accessibility and touch-target requirements
- Python execution
- Node execution when available
- C++ compilation and execution when available
- Repository symbol discovery
- Requested edits
- Snapshot rollback
- Verification execution
- Deterministic repository evaluation
- Planner-to-coder COI collaboration
- Permission boundaries
- Detection of incomplete interactive artifacts
- Escalation after severe local-provider failure
- Acceptance of a completed rescue artifact
- Persistence of provider sequence memory
- MCP-style tool discovery
- A real platform tool call
- Resume state after interruption
- Optional live-provider generation

## Fair comparison with LangGraph or another harness

LangGraph is primarily an orchestration framework. Sophyane is an integrated software-engineering runtime. A fair comparison must therefore define the layer under test.

### A. Graph-runtime test

Measure only:

- Graph construction
- Conditional routing
- State updates
- Checkpoint overhead
- Interrupt/resume behavior
- Raw latency

This test favors focused orchestration libraries and does not measure complete product delivery.

### B. End-to-end engineering test

Use identical tasks such as:

1. Build a missing-letter browser game.
2. Build a Snake game with safe direction handling.
3. Repair malformed but structurally complete HTML.
4. Fix a failing repository test.
5. Resume after interruption.
6. Reject an unauthorized filesystem action.
7. Verify a browser artifact over HTTP.

For each system, record:

- Completion status
- Acceptance tests passed
- Total elapsed time
- Provider calls
- Repair calls
- Timeouts
- Tokens when available
- Files changed
- Test execution
- Rollbacks
- HTTP verification
- Final artifact fingerprint

### Required controls

A defensible head-to-head run must use:

- The same model and model configuration
- The same prompts
- The same maximum response time
- The same machine
- Fresh isolated workspaces
- The same network conditions
- The same acceptance tests
- The same retry budget
- Multiple runs per task
- Raw logs preserved for audit

## Suggested score

A practical engineering score can be weighted as follows:

| Component | Weight |
|---|---:|
| Acceptance-test correctness | 40% |
| Successful verified delivery | 20% |
| Recovery from injected defects | 15% |
| Repository safety and rollback | 10% |
| Efficiency and provider calls | 10% |
| Reproducibility and trace quality | 5% |

Do not award delivery points merely because a file exists. For browser products, require structural validation and an HTTP 200 response for the exact current workspace artifact.

## Interpreting results

- A framework may win raw graph latency while losing end-to-end delivery.
- A system may produce visually attractive output but fail acceptance tests.
- A high offline score does not guarantee live-provider reliability.
- One successful example is evidence of capability, not a statistically reliable ranking.
- Claims in README files and release notes should cite the exact benchmark mode and task set.
