# Autonomous opportunistic RSI Implementation Plan

Goal: implement bounded background RSI while preserving the exact dirty tree.
Architecture: host-owned evidence and authority gates, isolated file snapshots,
persistent observations, injectable services and a resource-aware daemon.
Tech stack: existing Python standard library, pytest, existing provider/SLI APIs.
Spec: docs/superpowers/specs/2026-09-14-autonomous-opportunistic-rsi-design.md

For each task write behavioral tests, run intended RED, implement, run GREEN and
neighboring regressions. Execute inline. Do not commit or push.

- [ ] 1. campaign.py: separate verifier callback returning CampaignEvidence;
  ignore attempt gate/score claims; strengthen RED and conservative levels.
  Tests: test_rsi_campaign_engine.py and test_autonomous_campaign_boundary.py.
- [ ] 2. observation_bus.py and weakness_ledger.py: submit/drain bounded
  observations, stable fingerprints, occurrence counting, atomic JSON persistence,
  statuses and retry/rejection history. Tests: test_autonomous_observations.py.
- [ ] 3. resource_governor.py: ResourceSnapshot/Policy/Decision and injectable
  sample/decide; missing sensors, activity, pressure and budgets fail safely.
- [ ] 4. opportunity_scheduler.py: select bounded fair due opportunities,
  defer with exponential capped backoff; tests for starvation and duplicates.
- [ ] 5. local_intelligence.py: explicit role routing, bounded untrusted outputs,
  per-task measured competence; no local source-mutation authority.
- [ ] 6. candidate_workspace.py: snapshot current source into owned temporary
  directories; path/link checks and exact fingerprints; no real Git required.
- [ ] 7. experiment.py and pre_verifier.py: frozen host experiment registry and
  argv checks; repeated RED, GREEN, holdout, regression, scope and growth gates.
- [ ] 8. cloud_review.py: EvidencePackage, strict review schema and canonical
  Codex/NIFDU fallback; only host evidence can authorize promotion gates.
- [ ] 9. autonomous.py: bounded tick stage machine with injected dependencies,
  serializable records, duplicate suppression and fail-closed promotion.
- [ ] 10. mode6_rsi_handoff.py: publish existing observations and wake supervisor
  after ledger handoff without executing source edits in the conversation path.
- [ ] 11. supervisor.py and runtime entry points: default-on singleton daemon,
  kill switch, process lock, foreground priority, interruptible stop/backoff.
- [ ] 12. research.py: targeted SLI adapter emits source-bearing untrusted claims;
  online/resource gates; offline local experiments continue.
- [ ] 13. metrics.py: operational counters and frozen/versioned capability/meta
  measurements, conservative evidence levels and degradation backoff.
- [ ] 14. adversarial integration: all requested authority, forged evidence,
  failed holdout/reverification, duplicate, lifecycle and offline scenarios.
- [ ] 15. focused and broad regression, git diff --check.
- [ ] 16. one full .venv/bin/python -m pytest run; record actual totals and status.

Acceptance: no model self-certifies; no rejected baseline advance; normal startup
and Mode-6 read-only execution remain compatible. Report measured results only.
