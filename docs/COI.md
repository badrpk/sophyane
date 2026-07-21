# Collaborative Orchestration Interface (COI)

**Status: Implemented foundation; distributed scheduling remains experimental.**

COI is Sophyane's native protocol for coordinating agents, tasks, artifacts, permissions, validation and local traces. It is not a replacement for MCP: COI coordinates internal work, while MCP connects external tools and services.

## Task contract

A COI task records:

- task ID, parent and owner
- goal and priority
- workspace and repository
- permissions and dependencies
- expected outputs and validators
- timeout and creation time

```python
from sophyane.coi import TaskContract

task = TaskContract(
    goal="Build and validate a responsive snake game",
    workspace="./snake",
    permissions=["workspace.read", "workspace.write", "browser.run"],
    outputs=["index.html"],
    validation=["html.complete", "controls.keyboard", "controls.touch"],
)
```

## Agent manifest

Agents publish explicit capabilities rather than relying on hidden prompt assumptions.

```python
from sophyane.coi import AgentManifest

manifest = AgentManifest(
    name="browser-validator",
    role="validator",
    skills=["browser", "accessibility"],
    permissions=["workspace.read", "browser.run"],
    tools=["browser", "mcp:web_fetch"],
    max_steps=6,
)
```

## Orchestrator

```python
from sophyane.coi import COIOrchestrator

coi = COIOrchestrator()
coi.register(manifest, runner)
result = coi.run(task, agent="browser-validator", context={"artifact": "index.html"})
```

The orchestrator checks declared permissions, records task and agent events, bounds execution and writes structured results under `~/.sophyane/coi/`.

## Filesystem

```text
~/.sophyane/coi/
├── agents/
├── tasks/
├── runs/
├── events/
├── artifacts/
├── queues/
├── knowledge/
├── contracts/
├── permissions/
└── metrics/
```

## CLI

```bash
sophyane-coi status
sophyane-coi task "Review authentication changes" --repository .
sophyane-coi agent-manifest reviewer --role validator --skill security --permission workspace.read
```

## Design rules

1. Only the provider dispatcher selects models.
2. COI selects agents and task order.
3. Agents receive bounded contracts and least-privilege permissions.
4. Validators determine completion.
5. Events and artifacts are persisted locally.
6. Private model reasoning is not used as the orchestration protocol; agents exchange goals, evidence, artifacts and results.

## COI and MCP

```text
COI supervisor
 ├── repository agent
 ├── coding agent
 ├── validator agent
 └── MCP tools
      ├── filesystem
      ├── GitHub
      ├── databases
      └── remote services
```

MCP tools can be declared in an agent manifest as `mcp:<tool-or-server>`. Permission policy remains controlled by COI and the sandbox.
