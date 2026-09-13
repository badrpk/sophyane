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

Mode 6 establishes transient Codex-first authority with the bounded cascade
`codex_cli -> nifdu_browser -> local_gguf`. Gemini is excluded from
Mode 6; explicit Mode-4 selections remain unchanged.

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
- preserve persistent provider/model configuration
- not persist provider changes
- clear incompatible SLI-only, learning, and strict-local flags
- replace stale transient authority with `codex_cli` / `codex-default`
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

Mode 6 owns exactly `codex_cli -> nifdu_browser -> local_gguf`, implemented by
`providers/human_conversation.py`. Every independent request starts at Codex.
Provider-internal retries and same-provider semantic repair precede failover.
Only availability/transport failures advance the cascade. Cancellation,
programming errors, authority violations and invalid contracts are terminal.

`provider_switching_allowed` remains false. Structured status exposes
`provider_failover_order` and `bounded_provider_failover: true`. Neither
fallback success nor startup selection writes provider/model configuration
or `llm.json`.

Verified camera artifacts are sent only through a provider with image transport.
Codex and Local currently lack that transport, so visual requests report their
unavailability and use NIFDU; no image is silently discarded.

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
9. Selecting 6 establishes transient Codex-first authority even after Gemini.
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
