# Sophyane Learning Intelligence (SLI)

Sophyane 18.8.0 adds a dependency-free execution-learning layer backed by SQLite.
SLI stores validated state-action-outcome experience and uses it to rank future
actions. It does **not** modify LLM weights, trust model self-reports, or bypass
permissions, validators, workspace boundaries, or bounded retries.

## Components

- `sophyane.sli` — source-aware SQLite memory and action recommendation.
- `sophyane.sli_learner` — browser-task classification, quality rewards and
  structured failure categories.
- `sophyane-sli` — statistics, trace inspection and recommendations.
- `sophyane-sli-train` — local-only curriculum loop for offline single-file
  browser applications.

## Inspect learning

```bash
sophyane-sli learning-stats
sophyane-sli trace --limit 10
sophyane-sli recommend "make a responsive calculator"
```

The default database is:

```text
~/.local/state/sophyane/sli.db
```

## Local curriculum loop

Start with a bounded test:

```bash
sophyane-sli-train --max-projects 1 --max-loops-per-project 10
```

Then run continuously:

```bash
sophyane-sli-train --max-loops-per-project 100
```

Press `Ctrl+C` once to request a safe stop. State is checkpointed under:

```text
~/.local/state/sophyane/sli-training/checkpoint.json
```

Generated projects are kept under:

```text
~/.sophyane/sli-training/projects
```

The curriculum runner:

- uses `LocalGgufProvider` directly;
- has no cloud-provider fallback;
- creates one isolated workspace per project;
- accepts only complete offline `index.html` artifacts;
- does not execute model-generated shell commands;
- does not install packages or access remote resources;
- records validator-grounded rewards and failure categories;
- stops a project early after verified success;
- caps each project at 100 loops;
- detects repeated unchanged artifacts;
- pauses when free disk drops below the configured threshold.

## Quality rewards

Successful traces earn reward from concrete evidence such as:

- successful execution status;
- a created browser artifact;
- structural validation;
- verified runtime delivery;
- absence of detected runtime errors.

Failures are categorized as empty response, unusable response, invalid schema,
no action, validation failure, execution error, exhausted repair, or unknown.
Safe preservation of prior work reduces the failure penalty.

## Trust weighting

Execution and validator memories outrank scanned logs and synthetic data:

| Source | Weight |
|---|---:|
| execution | 1.00 |
| validator | 0.95 |
| user feedback | 0.90 |
| manual | 0.80 |
| seed | 0.60 |
| unknown | 0.35 |
| scanned log | 0.15 |
| synthetic | 0.10 |

This prevents large volumes of weak or duplicated observations from
out-ranking a smaller number of real validated executions.
