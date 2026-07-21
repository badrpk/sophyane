# Sophyane 18.10.0

## Validator-triggered cloud rescue

Sophyane now distinguishes between two provider failure modes:

1. transport/API failure, handled by the normal fallback chain; and
2. responsive but repeatedly validator-rejected local output.

When a local GGUF or Ollama model receives repeated repair prompts, Sophyane can make one bounded request to a configured cloud provider, use that provider's corrected artifact or action, and automatically return to the local provider on the next call.

## Default behavior

- Primary provider remains local.
- Escalation occurs after two recognized repair prompts.
- Only providers with valid configured credentials are eligible.
- Cloud rescue is one-shot; it does not permanently switch the active provider.
- If no cloud provider is configured, bounded local recovery continues unchanged.

## Configuration

The following optional keys may be added to `~/.config/sophyane/llm.json`:

```json
{
  "allow_quality_escalation": true,
  "quality_escalation_after": 2,
  "quality_rescue_provider": "gemini"
}
```

Set `allow_quality_escalation` to `false` to keep a strictly local-only runtime.

## Motivation

This release addresses cases where a small local model repeatedly produced structurally valid but incomplete browser projects, such as a snake game without keyboard or touch controls. Instead of spending all bounded repair attempts on the same incapable model, Sophyane now requests temporary expert help and then resumes local execution and validation.

## Other behavior retained

- VELA deterministic validation
- automatic interactive SLI recording
- safe SLI schema migration
- workspace preservation on failure
- local-first provider selection
