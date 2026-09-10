# Human Conversation Startup Mode Design

Date: 2026-09-10

## Goal

Add Human Conversation as a first-class Sophyane startup mode while preserving
the semantics and numbering of existing Modes 1–5.

The new startup menu becomes:

1. Sophyane — intelligently decide between available capabilities
2. SLI Graph — memory + internet, no LLM
3. Local LLM — llama.cpp / GGUF on-device model
4. External LLM — API / Browser / Codex CLI
5. Sophyane Learning — acquire + embed until saturation/Ctrl+C
6. Human Conversation — natural chat + voice/camera + repository execution

The prompt becomes:

Select [1-6, default 1]:

## Architecture

Human Conversation is an interaction surface, not a new LLM provider.

Startup policy selects the mode by setting:

SOPHYANE_SESSION_MODE=human_conversation

The mode must not invent or persist a new provider configuration.

The selected/current provider remains authoritative through the existing
provider construction and session environment mechanisms.

## Runtime Flow

The intended execution path is:

startup_policy.choose_startup_provider()
    -> SOPHYANE_SESSION_MODE=human_conversation
    -> cli_entry.main()
    -> sophyane.human_conversation_cli.main()

Human Conversation then retains its existing routing:

ordinary chat
    -> conversation_turn()

voice transcript
    -> same human-conversation router

camera input
    -> visual conversation path

explicit repository execution
    -> existing repository execution classifier
    -> canonical run_adaptive_loop execution path

## Startup Policy

Selecting option 6 must:

- set SOPHYANE_SESSION_MODE=human_conversation
- preserve the current provider/model configuration
- not persist provider changes
- clear incompatible SLI-only, learning, and strict-local flags
- leave explicit session provider/model/timeout authority intact when already
  present
- print a clear Human Conversation mode banner

Human Conversation must remain available independently of whether the current
provider is local, cloud, browser, Codex CLI, or another supported provider.

## CLI Handoff

cli_entry.main() owns the runtime handoff.

After startup selection and normal runtime initialization, if:

SOPHYANE_SESSION_MODE == "human_conversation"

then cli_entry.main() must call:

sophyane.human_conversation_cli.main()

directly in-process.

It must not spawn a second Python process.

It must not route Human Conversation through v13_cli.main() or tui_v2.

All other session modes retain their current dispatch behavior.

## Noninteractive Behavior

An explicitly configured process with:

SOPHYANE_SESSION_MODE=human_conversation

must bypass the startup selector and enter Human Conversation directly.

No interactive menu should overwrite an explicitly selected Human Conversation
session.

## Provider Authority

Human Conversation mode must not itself choose between Local, Cloud, NIFDU,
Codex, or AGY providers.

Provider authority continues to come from existing configuration and transient
session environment state.

The mode therefore separates:

interaction surface:
    human_conversation

from:

provider:
    local_gguf / cloud provider / nifdu_browser / codex_cli / agy / other
    supported provider

## Banner and Identity

The runtime identity should clearly identify Human Conversation without
misrepresenting the underlying provider.

Existing Mode 1–5 banner behavior must remain unchanged.

## Tests

Tests must prove:

1. Startup menu displays all six modes.
2. Prompt is Select [1-6, default 1]:.
3. Existing options 1–5 retain their current behavior.
4. Selecting 6 sets SOPHYANE_SESSION_MODE=human_conversation.
5. Selecting 6 clears stale SLI-only flags.
6. Selecting 6 clears stale learning flags.
7. Selecting 6 clears stale strict-local execution flags.
8. Selecting 6 does not persist provider configuration.
9. Selecting 6 does not overwrite an existing transient session provider,
   model, or timeout.
10. cli_entry.main() dispatches Human Conversation directly to
    human_conversation_cli.main().
11. Human Conversation dispatch does not call v13_cli.main().
12. Explicit noninteractive SOPHYANE_SESSION_MODE=human_conversation bypasses
    startup selection.
13. Existing startup-mode regression tests remain green.
14. Existing Human Conversation routing tests remain green.

## Files

Primary production files:

- src/sophyane/startup_policy.py
- src/sophyane/cli_entry.py

Primary tests:

- tests/test_startup_five_mode_menu.py
- tests/test_startup_policy_five_mode_menu.py
- tests/test_startup_policy_five_mode_behavior.py
- new focused Human Conversation startup/handoff tests if clearer than
  overloading legacy five-mode test files

Existing Human Conversation implementation should not be modified unless a
failing test demonstrates a genuine integration requirement.

## Safety and Compatibility

- Preserve Modes 1–5 numbering and semantics.
- Do not introduce provider persistence from Mode 6.
- Do not silently fall back to another interaction surface.
- Do not duplicate Human Conversation routing in tui_v2.
- Do not call execution_runtime.execute_action directly.
- Preserve canonical adaptive execution for repository tasks.
- Preserve camera isolation from accidental repository execution.
- Preserve voice transcript routing through the same classifier.
- Preserve the dirty working tree and unrelated changes.
- Do not perform broad rewrites of startup_policy.py or cli_entry.py.

## Success Condition

From a normal interactive Sophyane launch, selecting 6 enters:

Sophyane human conversation mode.

and permits normal chat, voice, camera, and the already-verified repository
execution routing without entering the regular v13/tui interface.
