# Sophyane v13 integration compatibility

This matrix tests ten representative technologies commonly used around LangGraph. It is a compatibility target list, not a universal popularity ranking.

| # | Technology/package | Purpose | Offline CI | Service/live CI |
|---:|---|---|---|---|
| 1 | `langchain-core` | Runnable and tool interfaces | import + Runnable adapter | not required |
| 2 | `langsmith` | tracing and evaluation | import/version | API-key opt-in |
| 3 | `langchain-openai` | OpenAI chat models | import/version | `OPENAI_API_KEY` opt-in |
| 4 | `langchain-anthropic` | Claude chat models | import/version | `ANTHROPIC_API_KEY` opt-in |
| 5 | `langchain-google-genai` | Gemini chat models | import/version | `GOOGLE_API_KEY` opt-in |
| 6 | `langchain-tavily` | web-search tools | import/version | `TAVILY_API_KEY` opt-in |
| 7 | `langchain-mcp-adapters` | MCP tools/resources | import/version | external server opt-in |
| 8 | `langgraph-checkpoint-postgres` | durable checkpoints | import/version | PostgreSQL 16 service |
| 9 | `langgraph-checkpoint-redis` | Redis-backed persistence | import/version | Redis 7 service |
| 10 | `fastapi` | local/API serving | TestClient health endpoint | not required |

## What “compatible” means

The automated suite verifies that all ten packages resolve together in the same environment, their public modules import, a LangChain `Runnable` can be used through Sophyane's `InvokeAdapter`, Sophyane's real multi-agent runtime still completes in that environment, FastAPI serves a local endpoint, and real PostgreSQL/Redis service containers accept reads and writes.

It does **not** claim that paid provider calls succeeded unless the corresponding secret is configured and a live test artifact exists.

## Reproduce locally

```bash
python -m pip install -e ".[dev]"
python -m pip install -r requirements-integrations.txt
python -m pytest tests/test_integrations.py tests/test_multiagent.py
python benchmarks/integration_acceptance.py
```

With PostgreSQL and Redis available:

```bash
export POSTGRES_URI='postgresql://postgres:postgres@127.0.0.1:5432/postgres'
export REDIS_URL='redis://127.0.0.1:6379/0'
python benchmarks/service_acceptance.py
```

GitHub Actions runs the offline suite on Ubuntu, macOS, and Windows with Python 3.10 and 3.13, plus service-backed persistence checks on Ubuntu. Raw reports and resolved package versions are retained as workflow artifacts for 90 days.
