# Sophyane v12 benchmark program

Sophyane publishes reproducible comparisons against LangGraph 1.2.9. The benchmark source is in `benchmarks/` and GitHub Actions uploads raw JSON plus a Markdown report for every run.

## Coverage

- Linear micrographs and conditional routing
- Large DAGs: 100, 500, or 1,000 nodes
- Fan-out/fan-in: 100, 250, or 1,000 branches
- SQLite checkpoint save and restore
- 100, 500, or 1,000 concurrent workflow invocations
- Memory growth over 2,000 to 50,000 executions
- Real local filesystem, subprocess, and localhost HTTP operations
- Human interrupt and resume
- Recovery from a deliberately terminated child process
- Sustained execution for 3, 15, or 60 seconds per runtime

## Profiles

| Profile | Intended use | Maximum DAG | Concurrency | Sustained run |
|---|---|---:|---:|---:|
| `quick` | Pull requests and low-power hardware | 100 | 100 | 3 seconds |
| `standard` | Weekly GitHub-hosted benchmark | 500 | 500 | 15 seconds |
| `heavy` | Manual release validation | 1,000 | 1,000 | 60 seconds |

## Run locally

```bash
python -m pip install -e .
python -m pip install 'langgraph==1.2.9' 'langgraph-checkpoint-sqlite>=3,<4'
python benchmarks/head_to_head.py
python benchmarks/comprehensive.py --profile quick
```

For a stronger release run:

```bash
python benchmarks/comprehensive.py --profile heavy
```

Results are written to `benchmark-results/comprehensive/results.json` and `benchmark-results/comprehensive/REPORT.md`.

## Reproducibility policy

Every published performance statement should identify:

1. exact Sophyane and LangGraph versions;
2. operating system, Python version, CPU count, and profile;
3. correctness status before latency results;
4. median and tail latency rather than only the fastest run;
5. whether persistence, HTTP, subprocesses, or LLM calls were included;
6. the raw JSON artifact from the same run.

## Responsible interpretation

These benchmarks test local deterministic orchestration. Sophyane is deliberately smaller and can have substantially lower overhead on these workloads. LangGraph provides a broader ecosystem and production integrations. Results must not be presented as proof that either project is universally superior.
