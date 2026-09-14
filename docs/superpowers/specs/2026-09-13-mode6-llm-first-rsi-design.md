# Mode 6 LLM-First Conversation + Guarded RSI Design

**Date:** 2026-09-13

## Goal

Mode 6 should use an LLM for natural conversation, reasoning,
troubleshooting, follow-ups, and explanation.

Sophyane remains the trusted control plane for runtime truth,
provider selection, authority, repository execution, and RSI.

## Core rule

**LLM handles language. Sophyane handles authority.**

Do not solve normal conversation with hard-coded phrases such as
"above reply", "explain that", "talk like human", or "what do you mean".

## Conversation session

Mode 6 keeps bounded recent conversation containing real:

- user turns;
- LLM assistant turns;
- deterministic Sophyane replies visible to the user.

The history is supplied to every conversational LLM request.

It is context only. It is never mutation or provider authority.

Empty input is ignored.

## Trusted context

Sophyane supplies structured trusted state separately from chat history:

- identity = Sophyane;
- runtime state;
- execution state;
- provider/capability state;
- authority policy;
- repository/task state when known.

The LLM may explain these facts naturally but must not contradict them.

## LLM contract

The Mode-6 responder should:

- identify as Sophyane;
- speak naturally;
- use recent conversation for follow-ups;
- adapt tone and complexity when requested;
- troubleshoot from supplied evidence;
- distinguish trusted state from conversation text;
- never grant itself provider or mutation authority.

## Repository authority

Original user intent remains the authority source.

Read-only work uses read-only authority.

Mutation and ambiguous repository work fail closed to source-mutation
authority.

Sophyane source mutation remains:

    codex_cli -> nifdu_browser -> DEFERRED_NO_CODING_PROVIDER

Local GGUF must not gain Sophyane source-mutation authority.

Conversation history, LLM plans, generated actions, and RSI observations
cannot change this rule.

## RSI alongside conversation

The LLM may optionally produce an improvement observation containing:

- problem;
- evidence;
- affected component;
- suggested direction;
- whether source mutation may be required.

An improvement observation is evidence, not authority.

It may enter Sophyane's guarded RSI workflow.

Actual source mutation still requires normal RSI validation, tests,
and coding-provider authority.

RSI observation must not block or replace the normal user-facing reply.

## Deterministic responsibilities

Keep deterministic code for:

- CLI commands;
- runtime fact collection;
- request authority classification;
- provider permissions;
- quota/cooldown state;
- repository safety;
- execution validation;
- RSI authority and promotion/rollback rules.

Do not make the LLM the security boundary.

## Required TDD proof

Tests must prove:

1. bounded multi-turn history reaches the LLM;
2. deterministic replies enter the same history;
3. normal follow-ups need no phrase classifier;
4. style corrections persist naturally;
5. empty input does not invoke the LLM;
6. trusted runtime facts cannot be replaced by chat history;
7. conversation cannot change provider/mutation authority;
8. LLM may emit an RSI observation;
9. RSI observation alone cannot mutate source;
10. mutation still routes Codex then NIFDU;
11. local GGUF remains denied source mutation.

## Migration

Preserve the current continuity tests and experimental work.

Replace the one-shot `previous_deterministic_reply` /
`previous_assistant_reply` mechanism with general bounded session history.

Do not discard existing RED/GREEN evidence.

## Likely implementation scope

Primary:

- `src/sophyane/human_conversation.py`
- `src/sophyane/human_conversation_cli.py`

Likely new focused module:

- `src/sophyane/mode6_session.py`

Possible RSI adapter if required:

- `src/sophyane/mode6_rsi.py`

Tests:

- existing Mode-6 continuity tests;
- new session-history tests;
- new RSI-observation tests;
- existing provider cascade;
- existing runtime introspection;
- existing RSI authority;
- existing request classifier.

## Safety constraints

Do not reset, restore, clean, stash, revert, or overwrite legitimate work.

Do not change canonical provider order.

Do not give local GGUF source-mutation authority.

Use bounded test groups on Termux.

Do not commit or push until fresh verification passes.

## Success condition

A conversation such as:

    User: How many agents are running?
    Sophyane: Right now it is just this conversation.

    User: What do you mean?
    Sophyane: Nothing is working in the background. Codex, NIFDU and
    the local model are capabilities I can use, not three agents.

    User: Talk normally.
    Sophyane: Sure. I'll keep it conversational.

must work from normal LLM conversation history, not hard-coded phrases.

At the same time, a user message asking local GGUF to modify Sophyane
must never alter source-mutation authority.
