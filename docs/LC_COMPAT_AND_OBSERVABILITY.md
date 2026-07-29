# LangChain / LangGraph / LangSmith parity (local)

Implemented **inside Sophyane** (Python control plane):

| Area | Module |
|------|--------|
| Prompt templates | `sophyane.lc_compat.prompt_templates` |
| Output parsers | `sophyane.lc_compat.output_parsers` |
| Tools | `sophyane.lc_compat.tools` |
| Memory | `sophyane.lc_compat.memory` |
| Multi-provider LLM facade | `sophyane.lc_compat.llm` |
| Durable graph / HITL resume | `sophyane.lc_compat.durable_graph` |
| Streaming events | `sophyane.lc_compat.streaming` |
| Mermaid graph viz | `sophyane.lc_compat.graph_viz` |
| Traces | `sophyane.observability.tracing` |
| Token/cost | `sophyane.observability.accounting` |
| Datasets / eval / prompts / experiments | `sophyane.observability.datasets` |

**NIFDU**: optional native checkpoint directory mirror (see `docs/NATIVE_DURABLE_CHECKPOINT.md`).
**Neuron**: no LLM/eval features (SNN only).

Not included (intentionally cloud/SaaS): team collaboration UI, hosted LangSmith, enterprise tenancy.
