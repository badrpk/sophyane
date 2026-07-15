# Sophyane verified harness (v16.1.0)

## Capabilities

1. `ToolRegistry` — named callable registration, duplicate protection, lookup and invocation.
2. `ModelRegistry` — priority-based model selection with automatic fallback when a provider fails.
3. `ContextManager` — bounded conversation context that evicts oldest entries when the character budget is exceeded.
4. `Guardrails` — blocks destructive command patterns (including pipe-to-shell) and requires explicit approval for dangerous tools.
5. `AgentHarness` loop — generate, verify, repair and retry with timing in the trace.
6. `VerificationResult` — explicit pass/fail feedback recorded in the execution trace.
7. `SandboxRunner` — timed shell/python execution with output caps and soft resource limits.
8. `FallbackProvider` — multi-provider LLM chain + automatic open-model rescue.
9. `local_runtime` — hardware profiling, Ollama install/serve, tier-fit model pull.
10. Grok-style TUI — slash commands, spinner, session scrollback, `/local` bootstrap.
11. `/daemon-tick` — processes the local SQLite task queue without requiring cloud LLM when idle.

## Reproduce

```bash
python -m pytest tests/ -q
python benchmarks/harness_acceptance.py
sophyane --status
sophyane /daemon-tick
sophyane /local
```
