# Phase 5B.1: GitHub-hosted candidate qualification

## Implementation status

This branch adds an independent `python_jsonl_v1` qualification class backed by a manually dispatched GitHub-hosted workflow. The hosted class is separate from the existing dedicated-runner verifier and does not change its security contract. It cannot approve production promotion.

The trusted workflow runs only from `main`, has `contents: read`, uses SHA-pinned checkout and artifact actions, and is not triggered by candidate pull requests. Candidate source is fetched anonymously at a full commit SHA and only the `ssee_candidate.py` blob is extracted. Trusted test fixtures and the harness come from the workflow checkout. No candidate source is checked out as a workflow or executed by the runner Python process.

The host harness runs candidate code in a disposable Docker container with a digest-pinned Python image, no network, read-only root, one read-only candidate file, no host credentials or Docker socket, UID 65532, dropped capabilities, default seccomp, no-new-privileges, 256 MiB memory, 0.5 CPU, 32 processes, bounded output and a per-case timeout. Evidence is written by the trusted host and is bound to request UUID, candidate SHA, workflow SHA and GitHub run ID. The dispatcher rechecks branch protection, run identity, artifact digest and report contents. Candidate output remains untrusted.

The container shares the GitHub VM kernel. This boundary limits ordinary process, filesystem, network and resource access; it does not claim protection from a container/kernel or GitHub VM escape. No repository write token, deployment secret, Samsung/Vivo key, or promotion-controller credential is sent to the candidate container. The workflow still uses a read-only GitHub token for trusted checkout/artifact actions; it is never passed to the candidate container.

## Current live status

Read-only checks found `badrpk/sophyane` is public, Actions are enabled, the authenticated account has repository administrator permission, and repository Actions default token permissions are read-only. The token has the `repo` scope, which is sufficient for the local dispatcher. `main` currently has no branch protection and no rulesets. The qualification workflow is not on `main`; therefore no live job was dispatched and no pass, fail, timeout or network-isolation result is claimed. Local Docker is unavailable in Termux; the workflow intentionally uses GitHub-hosted Linux.

## Required repository settings and approval

Before dispatch, an administrator must:

1. Protect `main` with pull requests required, at least one approval from someone other than the author, stale approvals dismissed, and enforcement applied to administrators. Prevent force-push and deletion. Require conversation resolution before merge.
2. Keep Actions `GITHUB_TOKEN` default permissions read-only. Actions are currently configured not to approve pull requests; keep that disabled and disable workflow access to create pull requests.
3. Restrict allowed actions and require full-length SHA pinning. Allow only the pinned `actions/checkout` and `actions/upload-artifact` actions in this workflow.
4. Review and merge this infrastructure branch through that protected process. Do not enable candidate execution or promotion outside `python_jsonl_v1`.

No settings, remote refs, or protected branches were changed by this implementation.

## Commands after protected merge

Run from the repository root. Obtain the current `main` commit SHA and substitute it as `WORKFLOW_SHA`; `CANDIDATE_SHA` must be a full immutable commit SHA containing `ssee_candidate.py` for the `candidate` fixture.

```sh
git ls-remote origin refs/heads/main
WORKFLOW_SHA=<40-character-main-sha>
CANDIDATE_SHA=<40-character-candidate-sha>
GH_TOKEN="$(gh auth token)" PYTHONPATH=src python tools/ssee_hosted_qualification_client.py dispatch \
  --candidate-sha "$CANDIDATE_SHA" --workflow-sha "$WORKFLOW_SHA" --fixture candidate
```

The dispatch prints a request UUID. Reuse the returned UUID and both SHAs:

```sh
GH_TOKEN="$(gh auth token)" PYTHONPATH=src python tools/ssee_hosted_qualification_client.py status \
  --request-id <request-uuid> --candidate-sha "$CANDIDATE_SHA" --workflow-sha "$WORKFLOW_SHA"
GH_TOKEN="$(gh auth token)" PYTHONPATH=src python tools/ssee_hosted_qualification_client.py evidence \
  --request-id <request-uuid> --candidate-sha "$CANDIDATE_SHA" --workflow-sha "$WORKFLOW_SHA"
GH_TOKEN="$(gh auth token)" PYTHONPATH=src python tools/ssee_hosted_qualification_client.py cancel \
  --request-id <request-uuid> --candidate-sha "$CANDIDATE_SHA" --workflow-sha "$WORKFLOW_SHA"
```

The harmless trusted fixtures can be selected as `pass`, `fail`, `timeout`, or `network` to exercise their independently expected outcomes. The same immutable `candidate_sha` can be used for these fixtures. An expected rejection fixture has a successful workflow conclusion only when its exact expected rejection/timeout evidence is observed; it does not mean the candidate passed.

## Verification

The added GitHub client and hosted qualification tests cover dispatch protection checks, SHA binding, status, cancellation, artifact integrity, malformed evidence, duplicate JSON keys, fixture trust separation and fixed container policy. The workflow is not live-qualified until the branch protection/settings above are applied and the reviewed workflow is merged to `main`.
