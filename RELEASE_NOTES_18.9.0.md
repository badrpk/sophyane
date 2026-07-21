# Sophyane 18.9.0

Sophyane 18.9.0 completes the validated local-execution and learning path tested on Android/Termux with a local Qwen2.5 GGUF model.

## Highlights

- Adds **VELA** (`sophyane-vela`) for deterministic workspace validation and optional SLI recording.
- Adds automatic **interactive execution → SLI** learning records.
- Adds `sophyane-sli-migrate` to back up incompatible legacy SQLite databases and recreate the current schema safely.
- Fixes execution routing so explicit imperative build requests take precedence over an incorrect native `chat` classification.
- Preserves concise exact local-model responses such as `LOCAL_OK` instead of replacing them with expert fallback text.
- Adds regression tests for concise hybrid answers, SLI schema migration, and VELA HTML validation.

## New commands

```bash
sophyane-vela [workspace] --record
sophyane-sli-migrate
sophyane-sli learning-stats
```

## Validated end-to-end path

```text
Prompt
→ execution routing
→ local GGUF planning
→ bounded workspace tools
→ deterministic artifact verification
→ browser preview
→ SLI quality scoring
→ SQLite learning record
```

## Compatibility note

Older SLI databases may use an incompatible schema. Run `sophyane-sli-migrate` before recording new executions. The command preserves the old database as `sli.db.backup.<timestamp>`.
