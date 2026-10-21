# Sophyane Core Controller Design

**Status:** Approved design, pending implementation plan

## Goal

Create one authoritative request-to-execution control plane for Sophyane's six operational modes without granting language models direct execution or promotion authority.

## Scope

This milestone establishes the shared controller contract and adapts existing mode implementations behind it. It does not claim to complete provider authentication, the unified Sentry subsystem, or live 24/7 proof; those are later milestones that consume this contract.

The six controller modes are:

1. `race` — compare candidates and record evaluation evidence.
2. `sli_graph` — use structured knowledge and reasoning to produce a plan.
3. `local_llm` — use local inference only.
4. `external_llm` — use Codex CLI or the selected NIFDU/provider route.
5. `learning` — update bounded adaptation and knowledge state from evidence.
6. `human_conversation` — conduct interactive conversation through the shared external cascade.

## Architecture

The controller owns classification, mode selection, planning, provider admission, state transitions, and audit events. A mode adapter owns mode-specific preparation and result interpretation. A provider gateway and execution boundary are dependencies, not controller internals.

```text
Request
  -> CoreController.classify()
  -> ModeAdapter.prepare()
  -> ProviderGateway.admit()
  -> ExecutionBoundary.execute()
  -> ModeAdapter.interpret()
  -> CoreController.audit()
```

Models may propose plans, code, or tool actions. They cannot select their own permissions, bypass the execution boundary, or promote their own output.

## Interfaces

The controller introduces these typed concepts:

- `ModeName`: closed enum of the six modes.
- `ControllerRequest`: request text, caller/session identity, requested mode if any, and bounded context.
- `ModePlan`: selected mode, provider intent, requested capabilities, bounded payload, and trace ID.
- `ProviderDecision`: selected provider, fallback chain, readiness, and reason.
- `ModeResult`: disposition, response/artifact references, verification status, and failure boundary.
- `AuditEvent`: append-only event with trace ID, actor, mode, provider, disposition, and evidence references.

The mode adapter protocol is:

```python
prepare(request: ControllerRequest, context: ControllerContext) -> ModePlan
interpret(plan: ModePlan, execution: ExecutionResult) -> ModeResult
```

The controller entry point is:

```python
handle(request: ControllerRequest) -> ModeResult
```

All interfaces must be deterministic at the policy boundary and serializable for diagnostics.

## Mode selection

Selection precedence:

1. Explicit, permitted mode requested by the caller.
2. Session mode already bound to the conversation or task.
3. Deterministic classifier result.
4. Safe default: `human_conversation` for ordinary dialogue, `local_llm` only when explicitly requested.

An unavailable or unauthorized requested mode fails closed with a structured error. It must not silently switch to a mode with broader authority. Provider fallback is allowed only within the selected mode's declared provider policy.

## Authority boundaries

- Reasoning authority: providers and models generate proposals.
- Execution authority: the execution boundary validates capabilities, workspace, network, budgets, and isolation before running anything.
- Promotion authority: independent verification and promotion policy decide whether artifacts enter a trusted tree.

The controller may deny a plan, but it may not weaken execution or promotion policy to make a plan succeed.

## State and audit

Each request receives a trace ID. The controller records lifecycle events for classification, mode selection, provider admission, execution, verification, promotion/rollback, and terminal failure. Events are append-only and include bounded error text; secrets and raw credentials are never recorded.

Restart recovery must distinguish `running`, `completed`, `rejected`, `failed`, `paused`, and `unknown`. An unknown in-flight request is recovered as failed/needs-review, never as successfully promoted.

## Failure semantics

Failures are classified into stable boundaries:

- `request_invalid`
- `mode_unavailable`
- `provider_unavailable`
- `execution_denied`
- `workspace_containment`
- `verification_failed`
- `promotion_denied`
- `state_unavailable`
- `controller_internal`

Every failure returns a structured `ModeResult`, updates the trace, and preserves the last trusted state. Provider failure may trigger the declared fallback chain; policy, containment, verification, and promotion failures may not be bypassed by fallback.

## Acceptance criteria

The milestone is complete only when:

1. Every six modes can be selected through one controller entry point.
2. Explicit mode selection is honored or rejected with a reason; it is never silently changed.
3. A model-generated action cannot execute without an execution-boundary decision.
4. A model-generated result cannot promote itself.
5. Provider fallback remains inside the selected mode policy.
6. Controller state and audit traces survive process restart.
7. Each failure boundary has a deterministic test.
8. Existing mode-specific tests remain green, or any unrelated baseline failures are documented with exact commands and output.
9. The controller can run in a dry-run mode that performs classification, planning, admission, and audit without external mutation.

## Non-goals

- Claiming all eleven external providers are authenticated or healthy.
- Removing scheduler budgets or safety pauses from RSI.
- Replacing existing mode implementations wholesale.
- Introducing NVIDIA hardware dependencies.
- Treating passing unit tests as proof of continuous Android uptime.

## Verification strategy

Tests will cover the controller in isolation with deterministic adapters, then integration tests will exercise existing local, external, SLI, race, learning, and conversation entry points. Live provider checks will be reported separately from deterministic tests because credentials, browser sessions, network, and device state are external dependencies.
