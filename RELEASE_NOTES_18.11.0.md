# Sophyane 18.11.0

## Startup provider policy

Interactive startup now reports the configured local model and cloud APIs before entering the TUI. When both are available, Sophyane asks whether to start local-first or use the configured cloud provider directly.

Local-first remains the recommended mode. It keeps the local model primary and retains one configured cloud provider for one-shot validator-triggered rescue.

## Input recovery

Typing `sophyane` inside an already-running Sophyane session is handled locally and returns a short command guide instead of being sent to an LLM. `/help`, `help`, `clear`, and `cls` are also intercepted locally.

## Correct sequence

1. Report configured local and cloud providers.
2. Ask local-first or cloud when both are available.
3. Start the selected runtime.
4. Keep cloud rescue temporary in local-first mode.
5. Recover harmless mistaken shell input without consuming API calls.
