# Sophyane 18.8.0 — Validated Execution Learning

This release introduces Sophyane Learning Intelligence (SLI), a local,
dependency-free layer that learns from validated software executions.

## Added

- Source-aware SQLite experience memory.
- Trust-weighted action recommendations.
- Browser-artifact request classification.
- Validator-grounded multi-signal rewards.
- Structured failure categories.
- Per-execution trace storage.
- `sophyane-sli` statistics, trace and recommendation command.
- `sophyane-sli-train` indefinite local curriculum runner.
- Graceful `Ctrl+C` checkpointing.
- Isolated project workspaces and 100-loop project cap.
- Offline-only HTML validation and stagnation detection.
- Regression tests for ranking, rewards and classification.

## Safety model

SLI advice remains non-binding. The model cannot award itself success. Rewards
come from deterministic execution evidence. The curriculum runner does not run
model-generated shell commands, install dependencies, use cloud fallback, or
open generated applications automatically.

## Important distinction

The curriculum runner improves SLI memory and policy. It does not retrain or
fine-tune GGUF neural weights. Sophyane's existing opt-in continual C++ adapter
training remains a separate subsystem.

## Commands

```bash
sophyane-sli learning-stats
sophyane-sli recommend "make a responsive calculator"
sophyane-sli-train --max-projects 1 --max-loops-per-project 10
sophyane-sli-train --max-loops-per-project 100
```
