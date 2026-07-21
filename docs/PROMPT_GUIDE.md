# Prompt guide

Sophyane works best when a request names the outcome and how success will be checked.

## Recommended pattern

```text
Goal:
Constraints:
Context/files:
Acceptance criteria:
Tests:
```

Example:

```text
Goal: Build a responsive snake game in index.html.
Constraints: One self-contained file, offline, mobile-first.
Context/files: Use the current project workspace.
Acceptance criteria: Keyboard and touch controls, score, restart, full-screen layout.
Tests: Open in browser; verify arrows/WASD, swipe/buttons, collision and restart.
```

## Short advice shown during work

- Name the exact file or repository when known.
- State what must remain unchanged.
- Prefer measurable acceptance criteria.
- Include the command or browser behavior that proves completion.
- Ask for a checkpoint before risky repository-wide edits.
- Use `/new` for an unrelated project and `/inspect` to review the current plan and files.

Avoid vague requests such as “fix it” or “make it better” unless the current project already contains enough context. Sophyane may infer missing details, but explicit constraints produce faster and more reliable evaluation.

## Agent-ready prompts

COI converts a strong prompt into a task contract containing goal, workspace, permissions, outputs and validators. Do not include hidden reasoning instructions. Agents should exchange evidence, artifacts, failures and results.
