# Evaluation

Sophyane evaluates work with deterministic checks first and model judgement only where deterministic evidence is insufficient.

## Core dimensions

- Correctness and acceptance criteria
- Build and test results
- Browser behavior and accessibility
- Security and permission boundaries
- Performance and responsiveness
- Documentation and reproducibility

## Evidence order

1. Exit codes and test reports
2. File and syntax checks
3. Browser/runtime observations
4. Validator findings
5. Model-assisted review

A model statement such as “done” is never sufficient evidence by itself.

## Repository evaluation

```bash
sophyane-platform eval .
```

Reports should identify checks, evidence, failures, score and recommended next action. Failed checks can become COI repair tasks assigned to a bounded repair agent.

## Good evaluation contract

```text
Output: index.html
Checks:
- complete HTML document
- no external dependency
- keyboard controls
- touch controls
- score changes after food
- restart works after game over
- responsive at phone viewport
```

## Traceability

COI events and platform run traces record task ID, agent, provider, elapsed time, outputs and validator results. This provides a local observability layer without requiring LangSmith.
