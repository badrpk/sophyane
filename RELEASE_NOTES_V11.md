# Sophyane 11.0.0

Sophyane v11 introduces evidence-backed autonomous software execution.

## Major capabilities

- Stateful execution graph: plan → build → test → bounded repair → verify → report.
- Real local file creation instead of LLM-only code suggestions.
- Exact test-command, stdout, stderr, and process exit-code capture.
- Acceptance-criteria verification before completion is claimed.
- Machine-readable `benchmark_report.json` evidence.
- Android/Termux-compatible operation using the Python standard library.
- Autonomous workflows execute before generic conversational routing.
- REST API requests are never routed to an `index.html`-only generator.
- Repository analysis rules exclude caches, virtual environments, registries, and generated output.

## Verified benchmark profile

The included inventory API workflow creates and verifies:

- Python REST API
- SQLite storage
- CRUD operations
- HTTP and repository tests
- README documentation
- no `index.html`
- bounded repair support

The verified local benchmark completed with four passing tests and an independent exit code of zero.

## Scope and honesty

Version 11 establishes the autonomous execution architecture and a validated inventory REST API workflow. It does not claim that every arbitrary software request is supported yet. Requests outside a registered workflow continue through the provider layer and must not claim local execution without tool evidence.

## Upgrade

```bash
cd ~/.local/share/sophyane
git fetch origin main
git reset --hard origin/main
./.venv/bin/python -m pip install --force-reinstall -e .
./.venv/bin/python -m pytest -q
```

If a legacy root-level `sophyane.py` shadows the package, move it outside the repository before reinstalling.
