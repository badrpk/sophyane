# Sophyane Concrete Mode and Provider Integration Design

**Status:** Draft for review

## Goal

Connect the proven Core Controller contracts to Sophyane's existing six mode implementations and provider infrastructure without allowing a provider or model to bypass execution, verification, or promotion authority.

## Scope

This phase replaces contract-only default adapters with injected concrete handlers. It does not make all providers live, remove safety budgets, or claim Android uptime. Every live integration remains optional and is represented as unavailable when its dependencies are not ready.

## Concrete mode boundaries

| Mode | Existing implementation boundary | Controller result |
|---|---|---|
| `race` | `race_orchestrator.run_adaptive_race()` | candidate/evaluation artifact; never direct promotion |
| `sli_graph` | SLI graph/provider controller and semantic planning | structured plan plus evidence |
| `local_llm` | local runtime and llama-server interfaces | local inference artifact or bounded failure |
| `external_llm` | provider fallback/Codex/NIFDU adapters | provider response/artifact under selected policy |
| `learning` | observation bus, evidence pipeline, and bounded learning stores | recorded learning evidence; no self-authorized mutation |
| `human_conversation` | `human_conversation.conversation_turn()` and Mode 6 observation handoff | conversation response and untrusted improvement observation |

Handlers receive a `ModePlan` and an injected capability object. They must return an `ExecutionResult`; they must not directly call the controller's promotion path.

## Provider gateway

The provider gateway becomes the only controller-facing provider surface. It accepts a mode plan and returns a `ProviderDecision` containing the selected provider, readiness, permitted fallback chain, and reason. The gateway must:

- preserve the selected external provider until an explicit policy permits fallback;
- keep local-only mode local;
- keep Mode 6's Codex → NIFDU cascade distinct from ordinary external mode;
- report unavailable credentials, browser sessions, local servers, and timeouts as structured provider failures;
- avoid recording secrets in controller audit events.

Existing provider implementations remain behind gateway adapters; no provider module becomes an execution authority.

## Execution and promotion

Mode handlers may produce candidates, responses, observations, and evidence. The injected execution boundary decides whether requested capabilities may run. Independent verification supplies `verification_status`; promotion requires an explicit independent approval signal and cannot be inferred from provider output.

Race and RSI handlers must preserve their existing isolated workspace, RED/GREEN, rollback, and promotion gates. Learning and Mode 6 observations remain non-executing evidence until a later bounded curriculum task is independently proposed and verified.

## Availability and lifecycle

Each concrete handler exposes a readiness probe that is deterministic and side-effect free. A missing provider, browser session, local server, repository, or required scenario is `provider_unavailable` or `mode_unavailable`, not an implicit fallback to broader authority.

The controller must support dry-run preparation for every mode. Live calls occur only after provider admission and execution-boundary approval.

## Verification requirements

1. Each mode invokes its intended existing implementation through a fake injected dependency.
2. Local mode never calls an external provider.
3. External mode preserves provider selection and permitted fallback order.
4. Mode 6 records observations as untrusted evidence only.
5. Race candidates cannot promote themselves.
6. Learning handlers cannot mutate trusted source directly.
7. Missing provider/session/runtime readiness produces structured failure.
8. A live smoke test reports availability separately from deterministic tests.
9. Existing mode-specific suites remain green.

## Non-goals

- Authenticating or repairing every external provider in one change.
- Replacing existing mode implementations.
- Removing scheduler budgets or Android/Termux process protection requirements.
- Treating fake gateway tests as proof of real provider availability.
