# Guarded Recursive Kernel Improvement

Sophyane treats every language model as an unreliable proposal generator. The kernel, not the model, owns correctness.

## Objective

Convert weak, incomplete, contradictory, malformed, or low-confidence model output into the maximum mechanically useful result that can be produced within the user's hardware, time, memory, storage, operating-system, and toolchain constraints.

## Core loop

```text
user demand
  -> capability and hardware profile
  -> task decomposition
  -> bounded model proposal
  -> salvage useful fragments
  -> normalize into typed artifacts/actions
  -> deterministic verification
  -> classify failure
  -> targeted repair or smaller subtask
  -> verify again
  -> deliver only proven output
  -> record evidence and strategy outcome
```

The loop is recursive over smaller artifacts and checks, not recursive prompting without limits.

## Kernel responsibilities

1. **Constraint discovery**
   - CPU architecture, RAM, storage, battery state when available, OS, package manager, compiler/interpreter versions, browser capability, network availability, and model context/output limits.

2. **Task decomposition**
   - Split large software requests into independently verifiable files, modules, functions, UI regions, build steps, and tests.
   - Prefer one small generation contract per model call on constrained hardware.

3. **Output salvage**
   - Extract complete and partial source files, JSON fragments, shell arguments, tests, declarations, functions, markup, styles, and diagnostics.
   - Never discard a useful prefix only because the complete response is malformed.

4. **Normalization**
   - Convert provider-specific or malformed structures into typed internal actions.
   - Reject unsafe paths and commands before execution.

5. **Deterministic completion**
   - Complete mechanical boilerplate only where correctness can be derived without inventing product behavior: missing closing tags, generated manifests, project scaffolding, build files, imports, formatting, and known protocol wrappers.
   - Product logic must come from user requirements, existing artifacts, tests, or a model proposal and must pass verification.

6. **Verification-first repair**
   - Use parsers, compilers, linters, unit tests, browser checks, schema validation, HTTP checks, file hashes, and runtime assertions.
   - Repair prompts contain only the failing artifact, concise diagnostics, and the exact acceptance contract.

7. **Strategy memory**
   - Record which decomposition, prompt contract, model, token budget, verifier, and repair strategy worked for each environment and task class.
   - Reuse successful strategies; do not blindly repeat failed prompts.

8. **Escalation**
   - When the local model cannot finish a subtask, Sophyane may request external intelligence only when configured and authorized.
   - Repository-connected development assistance may propose kernel patches, but runtime customer tasks must not silently transmit private code or data.

## Recursive self-improvement gates

Sophyane may generate an improvement proposal, but it must not silently rewrite its active kernel. Every kernel change follows:

```text
failure evidence
  -> minimal reproducible case
  -> proposed patch in isolated branch/worktree
  -> static checks
  -> focused regression tests
  -> full available test suite
  -> benchmark comparison
  -> safety and compatibility checks
  -> human approval or explicitly configured policy
  -> atomic release with rollback point
```

Required invariants:

- no modification of the running kernel in place;
- no bypass of tests, workspace boundaries, or command policy;
- no claim of improvement without measured evidence;
- no regression accepted merely because one example succeeds;
- every deployed change has a known previous commit and rollback procedure;
- customer files, secrets, and prompts are excluded from improvement artifacts unless the user explicitly authorizes their inclusion.

## Failure taxonomy

The kernel classifies failures before choosing a strategy:

- provider timeout;
- context overflow;
- output truncation;
- malformed JSON/action schema;
- incomplete source file;
- syntax or type error;
- missing dependency/toolchain;
- build failure;
- test failure;
- runtime crash;
- UI rendered blank;
- missing local asset;
- requirement not implemented;
- resource limit exceeded;
- unsafe action;
- verifier uncertainty.

Each class maps to a deterministic next action. For example, context overflow triggers context reduction and task subdivision, not repetition of the same request.

## Hardware-aware policies

For small local models and constrained phones:

- compact system contracts;
- one artifact or function per call;
- short diagnostic-only repair prompts;
- staged generation rather than whole-project generation;
- incremental persistence of every valid artifact;
- model output budgets selected by artifact type;
- no simultaneous duplicate model loading;
- bounded retries and wall-clock budgets;
- deterministic templates for safe scaffolding;
- early compiler/parser checks before requesting more code.

## Definition of done

A customer request is complete only when the requested artifact exists and its acceptance checks pass. A model response, a file write, or a browser HTTP 200 response alone is not completion.
