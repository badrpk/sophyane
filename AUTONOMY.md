# Sophyane v13 bounded autonomy

Sophyane v13 now defaults to a 10-second confirmation window for safe, workspace-scoped actions. When no response is received before the window expires, the worker is instructed to continue autonomously and record that the action continued by timeout policy.

## Default behavior

```bash
sophyane --multi-agent "Build, lint, test and repair this project"
```

The default policy is:

- safe file creation inside the active workspace: continue after 10 seconds;
- formatting, compilation, linting and tests: continue after 10 seconds;
- verifier-driven repair: continue until requirements pass or a hard limit is reached;
- explicit human denial: stop the requested action;
- external installation, publishing or network actions: require explicit approval;
- destructive, privileged, secret-access or workspace-escape actions: blocked and never approved by timeout.

## Configure the timeout

```bash
sophyane --multi-agent --approval-timeout 20 "Build and verify the package"
```

Disable timeout continuation:

```bash
sophyane --multi-agent --no-auto-continue "Build and verify the package"
```

## Machine-readable evidence

With `--agent-json`, the run includes:

```json
{
  "autonomy": {
    "safe_auto_continue": true,
    "approval_timeout_seconds": 10.0,
    "dangerous_actions_auto_approved": false
  }
}
```

## Completion semantics

“Continue until complete” is verifier-driven, not unlimited. A task is complete only when its declared checks pass. Repair loops must also have a hard iteration, time or resource ceiling. If the ceiling is reached, Sophyane reports failure or partial completion rather than claiming success.
