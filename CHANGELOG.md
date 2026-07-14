# Changelog

## 11.0.0 — 2026-07-14

### Added

- Stateful autonomous software-build graph
- Plan, build, test, repair, verify, and report nodes
- Bounded retry loop and graph safety limit
- Inventory REST API reference workflow using Python and SQLite
- Repository and HTTP automated tests for generated projects
- Machine-readable build evidence in `benchmark_report.json`
- Acceptance-criteria and evidence-backed completion contract

### Changed

- Supported autonomous requests execute before conversational LLM routing
- Backend requests are no longer satisfied by browser-only `index.html` generation
- Completion claims now require commands, exit codes, test results, and verification
- Package description and metadata now reflect autonomous stateful execution

### Verified

The reference workflow was independently tested on Android 15 Termux/aarch64. It created the expected files, ran four automated tests successfully, recorded exit code `0`, produced no `index.html`, and passed every verification check.
