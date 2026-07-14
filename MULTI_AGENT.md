# Sophyane v13 multi-agent runtime

Sophyane v13 adds a real supervisor-worker execution layer. Worker roles are not merely labels in one response: each worker receives a separate backend invocation, has a unique ID, lifecycle state, retry counter, messages and durable SQLite records.

## Routing

`auto` mode uses a deterministic complexity score. Narrow tasks remain single-agent. Tasks involving several domains, independent verification, production scope or explicit parallelism are escalated.

```text
request -> complexity router
              | low score       | high score
              v                 v
         executor worker     supervisor
                              |-- planner
                              |-- coder
                              |-- database/security/test/docs/ops as needed
                              `-- reviewer + merger
```

## Commands

```bash
sophyane "Fix one Python syntax error"
sophyane --multi-agent "Build an API with database, tests and documentation"
sophyane --single-agent "Handle this task with one worker"
sophyane --multi-agent --agent-json "Build and review a calculator"
sophyane --inspect-run RUN_ID
```

Normal output exposes runtime evidence:

```text
EXECUTION_MODE=multi_agent
AGENT_COUNT=5
ACTUAL_WORKERS_LAUNCHED=5
SUPERVISOR_ID=supervisor-...
RUN_ID=run-...
AGENT_ROLES=planner,coder,tester,documentation,reviewer
```

## Durability and observability

The default database is the Sophyane data directory's `multiagent.db`. It stores:

- runs and routing assessments;
- worker IDs, roles, status, attempts, output and errors;
- supervisor-to-worker and worker-to-supervisor messages;
- ordered lifecycle events;
- final merged output.

SQLite uses WAL mode and a busy timeout for concurrent worker writes.

## Failure behavior

Each worker has bounded retry attempts. A permanently failed specialist does not discard successful peer outputs. The reviewer merges completed work, the run is marked `completed_with_failures`, and failed worker IDs remain visible in the trace.

## Safety and resource limits

- `--max-workers` caps concurrency (default 6).
- `--agent-attempts` caps retry attempts (default 2).
- Simple tasks default to one worker to reduce cost and latency.
- Existing internal commands such as `/remember` bypass multi-agent routing.
- Provider credentials remain managed by the existing Sophyane provider layer.

## Verification

Run the offline acceptance suite without an API key:

```bash
python -m pytest tests/test_multiagent.py
python benchmarks/multiagent_acceptance.py
```

A successful acceptance run reports **Class B — true coordinated multi-agent runtime** and proves unique worker identities, parallel execution threads, persistent lifecycle records, supervisor events, independent reviewer completion and automatic single/multi routing.
