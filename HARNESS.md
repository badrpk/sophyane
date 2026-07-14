# Sophyane v13 verified harness

The v13 harness exposes six first-class capabilities:

1. `ToolRegistry` — named callable registration, duplicate protection, lookup and invocation.
2. `ModelRegistry` — priority-based model selection with automatic fallback when a provider fails.
3. `ContextManager` — bounded conversation context that evicts oldest entries when the character budget is exceeded.
4. `Guardrails` — blocks destructive command patterns and requires explicit approval for dangerous tools.
5. `AgentHarness` loop — generate, verify, repair and retry with a fixed maximum iteration count.
6. `VerificationResult` — explicit pass/fail feedback recorded in the execution trace.

## Reproduce

```bash
python -m pytest tests/test_harness.py tests/test_multiagent.py
python benchmarks/harness_acceptance.py
cat benchmark-results/harness/REPORT.md
```

A passing acceptance run must demonstrate a primary-model failure, fallback-model selection, one failed verification, a repair iteration, a final verified output, tool execution, bounded context and a blocked destructive command.
