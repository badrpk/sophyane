# Sophyane v12 benchmark results

## Preliminary local quick-profile result

This reference run was executed on July 14, 2026 using:

- Sophyane `12.0.0`
- LangGraph `1.2.9`
- Python `3.13.5`
- Linux `6.6.119` x86-64
- 2 logical CPUs
- quick profile

Both runtimes passed the benchmark correctness checks for the compared workloads before performance figures were recorded.

| Workload | Sophyane | LangGraph | Observed difference |
|---|---:|---:|---:|
| 100-node DAG median latency | 0.322 ms | 57.614 ms | Sophyane 178.87× lower median overhead |
| 100-branch fan workload median latency | 0.0116 ms | 1.246 ms | Sophyane 107.77× lower median overhead |
| 100 concurrent workflows | 5,134 workflows/s | 369 workflows/s | Sophyane 13.92× higher throughput |
| SQLite checkpoint writes | 1,345 writes/s | 171 writes/s | Sophyane 7.85× higher write rate |
| SQLite checkpoint reads | 1,631 reads/s | 3,923 reads/s | LangGraph 2.40× higher read rate |
| Retained memory per iteration | 0.292 bytes | 9.800 bytes | Sophyane retained less Python-tracked memory |
| Three-second sustained run | 81,616 workflows/s | 457 workflows/s | Sophyane 178.45× higher throughput |

The real-tool environment check passed for local filesystem access, subprocess execution, and localhost HTTP. Both runtimes passed the tested human interrupt/resume behavior. Sophyane also recovered its stored state after a deliberately terminated child process.

## Cross-platform verification status

The repository workflow runs the quick profile five times on each of:

- Ubuntu
- macOS
- Windows

A separate scheduled workflow runs the standard profile five times on Ubuntu. Manual workflow dispatch supports quick, standard, and heavy profiles. Every run uploads raw JSON, while aggregate reports publish median, mean, minimum, maximum, and standard deviation.

The preliminary figures above should be replaced by the aggregate GitHub Actions result after all cross-platform jobs complete successfully.

## Reproduce

```bash
python -m pip install -e .
python -m pip install "langgraph==1.2.9" "langgraph-checkpoint-sqlite>=3,<4"
python benchmarks/comprehensive.py --profile quick --output benchmark-results/comprehensive
cat benchmark-results/comprehensive/REPORT.md
```

See [`BENCHMARKS.md`](BENCHMARKS.md) for standard and heavy profiles, methodology, coverage, and interpretation requirements.

## Responsible claim

A result from this suite supports the following scoped statement:

> On the published deterministic local orchestration benchmark, Sophyane v12 produced equivalent outputs and lower measured overhead than the tested LangGraph 1.2.9 implementation on most measured workloads. Exact results depend on workload, platform, persistence mode, and hardware.

It does not prove universal superiority. This suite does not compare hosted deployment, distributed queues, LangSmith, ecosystem maturity, third-party integrations, or LLM quality.
