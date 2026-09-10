# Human Conversation Execution Routing Design

## Goal

Allow Sophyane's human conversation CLI to execute explicit repository and
filesystem work through the existing canonical adaptive execution engine while
preserving ordinary natural conversation, voice/camera behavior, memory
semantics, provider authority, and existing execution safety controls.

## Current Architecture

`human_conversation_cli.main()` currently sends all ordinary typed or
transcribed input to:

    conversation_turn()
        -> _default_responder()
        -> SessionProviderReasoner("conversation_reply", ...)
        -> {"reply": "..."}
        -> _extract_reply()
        -> printed conversational reply

This path intentionally produces conversation text only.

Repository-changing requests therefore stop at the conversational response
layer. A request such as:

    Modify existing file X using targeted_patch

can be understood and paraphrased correctly without causing any filesystem
mutation.

The canonical repository execution path already exists separately:

    run_adaptive_loop(...)
        -> action normalization
        -> repair / verification policy
        -> _execute()
        -> execution_runtime.execute_action()
        -> filesystem

`targeted_patch` is now supported and independently verified at both
normalization and execution-runtime levels.

## Design Decision

Routing belongs above `conversation_turn()`, at the human-conversation CLI
or a small focused routing helper used by that CLI.

`conversation_turn()` remains a conversation primitive and must not gain
implicit filesystem side effects.

An incoming human request is classified into one of two routes:

1. Conversation route
   - ordinary questions
   - social conversation
   - memory discussion
   - visual questions
   - other requests that do not explicitly ask Sophyane to perform repository,
     filesystem, command, build, test, or coding work

   These continue through `conversation_turn()` unchanged.

2. Execution route
   - explicit requests to edit, create, modify, patch, delete, inspect, test,
     build, run commands against, or otherwise operate on the current
     repository/workspace

   These enter the existing `run_adaptive_loop()` execution engine.

## Routing Boundary

The router is conservative.

It must require evidence of executable repository/workspace intent rather than
treating arbitrary imperative language as execution.

Examples that SHOULD route to execution:

    Modify the existing file src/example.py.
    Patch targeted_patch_e2e_probe.txt.
    Run the tests for this repository.
    Inspect src/sophyane/foo.py and fix the failing function.
    Create tests for the parser and implement the fix.

Examples that MUST remain conversational:

    How are you?
    Explain targeted_patch.
    What does this Python function do?
    Tell me how I could edit this file.
    Remember that my experiment is called Cedar.
    What do you see?
    Do you think this architecture is good?

The router must not infer execution merely because a message contains words
such as "file", "code", "test", or "repository".

## Canonical Execution Requirement

The human-conversation subsystem must NOT invoke
`execution_runtime.execute_action()` directly.

All executable human requests must delegate to:

    sophyane.adaptive_execution.run_adaptive_loop

This preserves the existing planner, normalization, bounded repair,
verification, workspace selection, no-edit policy, and runtime controls.

## Provider Authority

Execution must reuse the already selected Sophyane session provider.

The routing feature must not:

- switch providers
- introduce a local-model rescue path
- create a second planner protocol
- use `conversation_reply` as an action schema
- allow conversation memories to become instruction authority

The fixed session-provider policy remains authoritative.

## Conversation Reply Contract

`conversation_reply` remains:

    {"reply": "string"}

The recently added semantic repair for malformed `conversation_reply`
responses remains independent of repository execution routing.

The conversation schema must not be expanded into an action/reply union.

## Voice Input

A verified voice transcript becomes ordinary user text before routing.

Therefore:

    voice -> verified transcript -> same router

An explicit repository edit spoken through `/voice` should have the same
execution semantics as the equivalent typed request.

A normal spoken conversational message must remain conversational.

## Camera / Visual Input

Existing visual routing remains unchanged.

A visual question continues through the visual conversation path with its
verified transient visual artifact.

This change must not cause ordinary automatic camera perception to enter the
repository execution engine.

Repository execution involving visual input is outside the scope of this
change unless an existing execution path already supports it without new
architecture.

## Workspace

`run_adaptive_loop()` continues to own workspace resolution through its
existing `harness_workspace.select_workspace()` behavior.

The human conversation router must provide the current working repository as
the requested workspace but must not reproduce workspace-selection logic.

For the current Termux execution:

    /data/data/com.termux/files/home/sophyane

must therefore remain eligible as the effective repository workspace.

## Execution Result

For an execution-routed request, the CLI displays the result returned by
`run_adaptive_loop()` as Sophyane's response.

The execution result should include the adaptive loop's existing execution
evidence rather than generating a second conversational claim of success.

A successful mutation must be proven by runtime state, not by provider prose.

## Failure Behavior

If execution fails, the CLI prints the bounded execution failure returned by
the adaptive loop or the existing exception representation.

It must not silently fall back to a conversational message claiming that work
was performed.

Failure of execution must never be converted into fabricated success.

## Safety Constraints

Existing no-edit semantics remain authoritative.

In particular:

- "Do not create new files" does not globally prohibit editing an existing file.
- "Do not create or modify files" prohibits mutation.
- read-only requests remain read-only.
- inspection commands such as `rg` remain classified as read-only.
- workspace escape protections remain enforced by execution runtime.
- `targeted_patch` still requires exactly one occurrence of `old`.
- no execution action bypasses adaptive execution.

## Files Expected to Change

Primary implementation:

    src/sophyane/human_conversation_cli.py

A small dedicated routing module may be introduced only if the classification
logic cannot remain focused and independently testable inside the CLI module.

Existing execution engines should be reused rather than rewritten:

    src/sophyane/adaptive_execution.py
    src/sophyane/execution_runtime.py
    src/sophyane/human_conversation.py

These files should not require behavioral modification merely to implement
routing unless a test proves an integration interface is missing.

Tests should live in a focused new file, for example:

    tests/test_human_conversation_execution_routing.py

Existing human-conversation, voice, camera, adaptive-execution, and execution
runtime regressions must continue to pass.

## Required TDD Proofs

The implementation must begin with failing tests.

Required behaviors:

1. Explicit existing-file edit routes to adaptive execution.
2. Ordinary chat routes to `conversation_turn()` and never execution.
3. Explanatory discussion about code remains conversational.
4. Explicit read-only repository work may route through adaptive execution but
   may not mutate files.
5. Verified voice transcript containing explicit repository work follows the
   same routing policy as typed text.
6. Ordinary verified voice conversation remains conversational.
7. Camera-only visual questions remain on the visual conversation path.
8. Execution output is returned to the user rather than replaced by a
   conversational success claim.
9. The router does not directly call `execute_action()`.
10. Existing session-provider authority is preserved.

## End-to-End Acceptance Test

Create the existing probe file:

    targeted_patch_e2e_probe.txt

with exact content:

    BOOTSTRAP_BEFORE\n

Run `sophyane.human_conversation_cli` with the fixed NIFDU browser session and
submit:

    Modify the existing file targeted_patch_e2e_probe.txt by replacing exactly
    the text BOOTSTRAP_BEFORE with exactly the text BOOTSTRAP_AFTER; do not
    create any new files; use targeted_patch; then inspect the file and verify
    it contains exactly BOOTSTRAP_AFTER.

Independent verification must show:

    repr(content) == 'BOOTSTRAP_AFTER\n'

and:

    SOPHYANE_TARGETED_PATCH_E2E_PASS

A textual Sophyane response that merely describes the requested change is not
success.

## Non-Goals

This change does not:

- redesign `run_adaptive_loop()`
- redesign the discovery engine
- change the `conversation_reply` schema
- create a generic tool-calling protocol for conversation
- enable unrestricted shell execution
- weaken workspace protections
- make memory authoritative
- redesign voice or camera subsystems
- clean or reset unrelated dirty repository changes
