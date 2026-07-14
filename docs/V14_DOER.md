# Sophyane v14 — Goal-Driven Doer

Sophyane v14 changes the default CLI path from one-shot text generation to a bounded planner → executor → verifier loop.

## Runtime contract

1. Retrieve relevant persistent memory and recent conversation state.
2. Convert the request into an objective and measurable success criteria.
3. Select one best next action; do not return a menu when evidence supports a choice.
4. Execute approved actions inside the configured workspace.
5. Record file hashes, command arguments, exit codes, stdout, stderr and timing.
6. Ask an independent verifier whether every criterion is objectively satisfied.
7. Replan from the verifier's missing requirements until the goal is verified, user input is essential, or the maximum step limit is reached.

## Usage

```bash
sophyane --workspace "$PWD" --max-steps 12 \
  "Create a Python solar calculator, run it, and verify the result"
```

Machine-readable evidence:

```bash
sophyane --agent-json --workspace "$PWD" \
  "Safely inspect this project and run its tests"
```

Legacy v13 modes remain available explicitly:

```bash
sophyane --single-agent "Explain this function"
sophyane --multi-agent "Review and test this project"
```

## Safety boundaries

The doer automatically proceeds with workspace-confined file writes and allowlisted commands. Destructive or privileged commands such as `rm`, `sudo`, `mkfs`, shutdown operations and process-killing commands are blocked. Operations that require credentials, personal preference, destructive effects or essential missing information must stop and ask the user.

## Completion semantics

`GOAL_MET=true` is emitted only after the verifier confirms every success criterion. A textual claim by itself is not execution evidence. The process exits with status 0 only for verified completion; unverified or blocked objectives exit with status 2.

No agent can guarantee success for every possible request. v14's guarantee is narrower and testable: it does not label an objective complete unless the configured verifier confirms all stated criteria from the available observations and execution evidence.
