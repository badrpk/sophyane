# Sophyane v13 integration compatibility

Sophyane maintains a 30-technology compatibility matrix split into a lightweight base bundle and an optional extended ecosystem bundle. The list represents high-value companion technologies used around agent runtimes; it is not a universal popularity ranking.

## Base bundle: 10 targets

| Technology/package | Purpose |
|---|---|
| `langchain-core` | Runnable and tool interfaces |
| `langsmith` | tracing and evaluation |
| `langchain-openai` | OpenAI chat models |
| `langchain-anthropic` | Claude chat models |
| `langchain-google-genai` | Gemini chat models |
| `langchain-tavily` | web-search tools |
| `langchain-mcp-adapters` | MCP tools and resources |
| `langgraph-checkpoint-postgres` | PostgreSQL checkpoints |
| `langgraph-checkpoint-redis` | Redis persistence |
| `fastapi` | API serving |

## Extended bundle: 20 additional targets

| Technology/package | Category | Typical use |
|---|---|---|
| `langchain-aws` | Model/cloud | AWS Bedrock models |
| `langchain-cohere` | Model | Cohere generation and embeddings |
| `langchain-mistralai` | Model | Mistral models |
| `langchain-groq` | Model | Groq-hosted inference |
| `langchain-ollama` | Model/local | Local Ollama models |
| `langchain-huggingface` | Model/local | Hugging Face models and embeddings |
| `langchain-pinecone` | Vector store | Pinecone retrieval |
| `langchain-qdrant` | Vector store | Qdrant retrieval |
| `langchain-weaviate` | Vector store | Weaviate retrieval |
| `langchain-chroma` | Vector store | Chroma local/remote retrieval |
| `langchain-elasticsearch` | Vector/search | Elasticsearch retrieval |
| `langchain-mongodb` | Vector/database | MongoDB Atlas retrieval |
| `langgraph-checkpoint-sqlite` | Persistence | local durable checkpoints |
| `opentelemetry-api` | Observability | vendor-neutral traces and metrics |
| `celery` | Task queue | distributed background workers |
| `confluent-kafka` | Event streaming | Kafka events and workflow messaging |
| `SQLAlchemy` | Database | portable relational persistence |
| `streamlit` | User interface | interactive data/agent apps |
| `gradio` | User interface | shareable model interfaces |
| `llama-index-core` | Framework interop | document and retrieval pipelines |

## What compatible means

The automated suite verifies that packages resolve together, public modules import, versions are recorded, sync and async invoke-style objects can be adapted as Sophyane backends, Sophyane's real multi-agent runtime remains operational, and FastAPI serves locally. PostgreSQL and Redis receive separate service-backed tests.

Import compatibility is not the same as a paid live-service test. Provider, hosted vector-database, Kafka, Celery, and observability claims require credentials or service URLs and a corresponding live artifact.

## Installation

Base bundle:

```bash
python -m pip install -r requirements-integrations.txt
```

All 30 targets:

```bash
python -m pip install -r requirements-integrations.txt
python -m pip install -r requirements-integrations-extended.txt
```

## Reproduce acceptance locally

```bash
python -m pip install -e ".[dev]"
python -m pip install -r requirements-integrations.txt
python -m pip install -r requirements-integrations-extended.txt
python -m pytest tests/test_integrations.py tests/test_multiagent.py
python benchmarks/integration_acceptance.py
```

GitHub Actions runs the 30-target import and adapter suite on Ubuntu, macOS, and Windows with Python 3.10 and 3.13. Raw reports and resolved package versions are retained for 90 days.
