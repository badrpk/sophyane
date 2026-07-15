# Sophyane — competitive parity

**Target:** Claude Code / Cursor agent loops (+ multi-channel OS differentiation)

| Surface | Implementation |
|---------|----------------|
| Full CLI agent OS | existing `sophyane` package (multi-provider, browser, messaging, payments) |
| HTTP agent control plane | `src/sophyane/competitive/agent_session_api.py` |
| Sessions + tools | `POST /v1/sessions`, `/v1/tools/execute` |
| Parallel subagents | `POST /v1/jobs` |
| Skills / budget / HITL | `/v1/skills`, `/v1/budget`, `/v1/hitl` |

```bash
PYTHONPATH=src python3 -m sophyane.competitive.agent_session_api
# or: python3 src/sophyane/competitive/agent_session_api.py
# http://127.0.0.1:8799/capabilities
```

Sophyane remains **ahead** of pure coding agents on Telegram/WhatsApp/email/payments channels.
