"""Bounded GitHub PR/check/artifact client for the X70 approval boundary.

The client never pushes a branch or merges a pull request. A caller supplies a
short-lived GitHub token; this module neither persists nor logs it.
"""
from __future__ import annotations

import hashlib
import io
import json
import re
import stat
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from .verifier import verify_github_report


class GitHubSSEEError(RuntimeError):
    pass


class X70ApprovalRequired(GitHubSSEEError):
    """Raised after verification; no merge operation is provided here."""


_SHA = re.compile(r"^(?:[0-9a-f]{40}|[0-9a-f]{64})$")
_BRANCH = re.compile(r"^rsi/[A-Za-z0-9._/-]{1,180}$")
_REPORT = "verification-report.json"
_DIGEST = "verification-report.sha256"


class GitHubSSEEClient:
    """Use GitHub's API for an existing ``rsi/**`` branch and its PR.

    ``token`` should be a caller-provided, least-privilege token. Creating a PR
    needs pull-request write permission; polling and artifact verification
    need read access. Workflow jobs themselves must use ``contents: read`` and
    no secrets.
    """

    def __init__(self, owner, repo, token, *, api_base="https://api.github.com",
                 timeout=15, max_response_bytes=8 * 1024 * 1024):
        parsed = urllib.parse.urlsplit(api_base)
        if (parsed.scheme != "https" or parsed.hostname != "api.github.com" or parsed.path
                or parsed.port not in (None, 443) or parsed.username or parsed.password
                or parsed.query or parsed.fragment):
            raise ValueError("GitHub API base must use the official api.github.com HTTPS origin")
        if not owner or not repo or not isinstance(token, str) or not token:
            raise ValueError("owner, repository, and caller-supplied token are required")
        if timeout < 1 or timeout > 60 or max_response_bytes < 1024:
            raise ValueError("invalid response bounds")
        self.owner, self.repo = owner, repo
        self._token = token
        self.api_base = api_base.rstrip("/")
        self.timeout = timeout
        self.max_response_bytes = max_response_bytes

    @property
    def _repo_api(self):
        return f"{self.api_base}/repos/{urllib.parse.quote(self.owner, safe='')}/{urllib.parse.quote(self.repo, safe='')}"

    def _api(self, method, path, *, body=None):
        url = self._repo_api + path
        data = None if body is None else json.dumps(body, separators=(",", ":")).encode()
        req = urllib.request.Request(url, data=data, method=method, headers={
            "Accept": "application/vnd.github+json",
            "Authorization": "Bearer " + self._token,
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "Sophyane-SSEE-X70",
            "Content-Type": "application/json",
        })
        try:
            with urllib.request.build_opener(_NoRedirect).open(req, timeout=self.timeout) as response:
                if response.status >= 300:
                    raise GitHubSSEEError(f"GitHub API returned HTTP {response.status}")
                if response.status == 204:
                    return None
                raw = response.read(self.max_response_bytes + 1)
        except urllib.error.HTTPError as exc:
            raise GitHubSSEEError(f"GitHub API returned HTTP {exc.code}") from None
        except (urllib.error.URLError, TimeoutError) as exc:
            raise GitHubSSEEError(f"GitHub API request failed: {type(exc).__name__}") from None
        if len(raw) > self.max_response_bytes:
            raise GitHubSSEEError("GitHub API response exceeded size limit")
        try:
            return json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise GitHubSSEEError("GitHub API returned invalid JSON") from None

    def submit_candidate_pr(self, *, branch, base, title, body):
        """Open a PR from an already-pushed candidate branch; never pushes."""
        if not _BRANCH.fullmatch(branch) or ".." in branch.split("/"):
            raise ValueError("candidate branch must be a safe rsi/** name")
        if (not isinstance(base, str) or not base or base.startswith("-")
                or not isinstance(title, str) or not title or len(title) > 256
                or not isinstance(body, str) or len(body) > 20_000):
            raise ValueError("invalid PR metadata")
        prs = self._api("GET", "/pulls?state=open&head=" + urllib.parse.quote(f"{self.owner}:{branch}", safe="") + "&base=" + urllib.parse.quote(base, safe=""))
        if not isinstance(prs, list):
            raise GitHubSSEEError("unexpected pull request listing")
        if prs:
            return self._pull_request(prs[0])
        result = self._api("POST", "/pulls", body={"head": branch, "base": base, "title": title, "body": body, "draft": True})
        return self._pull_request(result)

    @staticmethod
    def _pull_request(value):
        try:
            number, head_sha, branch = value["number"], value["head"]["sha"], value["head"]["ref"]
        except (TypeError, KeyError):
            raise GitHubSSEEError("malformed pull request response") from None
        if not isinstance(number, int) or not _SHA.fullmatch(head_sha) or not _BRANCH.fullmatch(branch):
            raise GitHubSSEEError("pull request head is not a valid rsi/** candidate")
        return {"number": number, "head_sha": head_sha, "branch": branch}

    def wait_for_exact_head_check(self, *, pull_number, expected_head_sha,
                                  check_name="SSEE offline QEMU verification",
                                  timeout_seconds=1800, poll_seconds=15):
        if not _SHA.fullmatch(expected_head_sha) or timeout_seconds < 1 or timeout_seconds > 7200 or poll_seconds < 1 or poll_seconds > 60:
            raise ValueError("invalid SHA or polling bounds")
        deadline = time.monotonic() + timeout_seconds
        while time.monotonic() < deadline:
            pr = self._api("GET", f"/pulls/{int(pull_number)}")
            try:
                current_sha = pr["head"]["sha"]
                branch = pr["head"]["ref"]
            except (TypeError, KeyError):
                raise GitHubSSEEError("malformed pull request response") from None
            if current_sha != expected_head_sha or not _BRANCH.fullmatch(branch):
                raise GitHubSSEEError("pull request head changed during verification")
            result = self._api("GET", f"/commits/{expected_head_sha}/check-runs?per_page=100")
            runs = result.get("check_runs", []) if isinstance(result, dict) else []
            if isinstance(result, dict) and result.get("total_count", len(runs)) > len(runs):
                raise GitHubSSEEError("check-run result is paginated; cannot verify complete exact-SHA status")
            matches = [run for run in runs if run.get("name") == check_name and run.get("head_sha") == expected_head_sha]
            if matches:
                matches.sort(key=lambda run: run.get("started_at") or run.get("created_at") or "", reverse=True)
                latest = matches[0]
            else:
                latest = None
            if latest and latest.get("status") == "completed":
                if latest.get("conclusion") != "success":
                    raise GitHubSSEEError("required exact-SHA check did not succeed")
                return latest
            time.sleep(min(poll_seconds, max(0, deadline - time.monotonic())))
        raise TimeoutError("timed out waiting for exact-head SSEE check")

    def fetch_verified_report(self, *, head_sha, check_run, workflow,
                              artifact_name="ssee-verification-report"):
        """Fetch the artifact from the successful workflow run bound to SHA."""
        if not _SHA.fullmatch(head_sha):
            raise ValueError("invalid candidate head SHA")
        if (not isinstance(check_run, dict) or check_run.get("head_sha") != head_sha
                or check_run.get("status") != "completed"
                or check_run.get("conclusion") != "success"
                or not isinstance(check_run.get("name"), str)):
            raise GitHubSSEEError("check run is not a successful exact-head check")
        # Check-run details are not trusted as an API path; discover runs via
        # the fixed workflow endpoint and require exact head/event/status.
        encoded_workflow = urllib.parse.quote(workflow, safe="")
        result = self._api("GET", f"/actions/workflows/{encoded_workflow}/runs?head_sha={head_sha}&per_page=100")
        runs = result.get("workflow_runs", []) if isinstance(result, dict) else []
        if isinstance(result, dict) and result.get("total_count", len(runs)) > len(runs):
            raise GitHubSSEEError("workflow run result is paginated; refusing ambiguous artifact selection")
        suite_id = (check_run.get("check_suite") or {}).get("id")
        if not isinstance(suite_id, int):
            raise GitHubSSEEError("check run has no trusted workflow suite binding")
        eligible = [r for r in runs if r.get("head_sha") == head_sha and r.get("event") == "pull_request" and r.get("status") == "completed" and r.get("conclusion") == "success" and r.get("check_suite_id") == suite_id]
        if len(eligible) != 1:
            raise GitHubSSEEError("expected exactly one successful pull_request workflow run for head SHA")
        run = eligible[0]
        run_id = run.get("id")
        if not isinstance(run_id, int):
            raise GitHubSSEEError("workflow run ID missing")
        artifact_result = self._api("GET", f"/actions/runs/{run_id}/artifacts?per_page=100")
        artifacts = artifact_result.get("artifacts", []) if isinstance(artifact_result, dict) else []
        if isinstance(artifact_result, dict) and artifact_result.get("total_count", len(artifacts)) > len(artifacts):
            raise GitHubSSEEError("artifact listing is paginated; refusing ambiguous artifact selection")
        found = [a for a in artifacts if a.get("name") == artifact_name and not a.get("expired")]
        if len(found) != 1:
            raise GitHubSSEEError("expected one unexpired SSEE report artifact")
        artifact = found[0]
        expected_zip_sha = artifact.get("digest", "")
        if not isinstance(expected_zip_sha, str) or not expected_zip_sha.startswith("sha256:"):
            raise GitHubSSEEError("GitHub artifact digest missing")
        zip_bytes = self._download_artifact(run_id, artifact.get("id"), expected_zip_sha[7:])
        report_bytes, report_digest = self._read_report_zip(zip_bytes)
        checked = verify_github_report(
            report_bytes=report_bytes, expected_report_sha256=report_digest,
            expected_head_sha=head_sha, expected_run_id=run_id,
            expected_workflow=workflow, expected_check_name=check_run.get("name"),
        )
        if not checked.accepted:
            raise GitHubSSEEError("verification report rejected: " + "; ".join(checked.reasons))
        return {"run_id": run_id, "report_sha256": checked.report_sha256, "report": checked.report}

    def _download_artifact(self, run_id, artifact_id, expected_zip_sha):
        if not isinstance(artifact_id, int) or not _SHA.fullmatch(expected_zip_sha):
            raise GitHubSSEEError("invalid artifact metadata")
        url = f"{self._repo_api}/actions/artifacts/{artifact_id}/zip"
        req = urllib.request.Request(url, headers={
            "Authorization": "Bearer " + self._token,
            "Accept": "application/vnd.github+json",
            "User-Agent": "Sophyane-SSEE-X70",
        })
        # GitHub returns a short-lived signed URL. Do not forward the token to
        # it; urllib's normal redirect handler is used only on this token-free
        # second request.
        no_redirect = urllib.request.build_opener(_NoRedirect)
        try:
            with no_redirect.open(req, timeout=self.timeout) as response:
                raw = response.read(1)
                raise GitHubSSEEError("artifact endpoint unexpectedly returned a body")
        except urllib.error.HTTPError as exc:
            if exc.code not in (301, 302, 303, 307, 308):
                raise GitHubSSEEError(f"artifact API returned HTTP {exc.code}") from None
            location = exc.headers.get("Location")
        except urllib.error.URLError as exc:
            # Some urllib versions surface redirects as URLError with HTTPError
            # as its reason; the normal path is HTTPError above.
            raise GitHubSSEEError("artifact download request failed") from None
        parsed = urllib.parse.urlsplit(location or "")
        if parsed.scheme != "https" or not parsed.netloc or parsed.username or parsed.password:
            raise GitHubSSEEError("artifact redirect is not a safe HTTPS URL")
        try:
            with urllib.request.urlopen(location, timeout=self.timeout) as response:
                data = response.read(8 * 1024 * 1024 + 1)
        except (urllib.error.URLError, TimeoutError):
            raise GitHubSSEEError("artifact blob download failed") from None
        if len(data) > 8 * 1024 * 1024:
            raise GitHubSSEEError("artifact ZIP exceeded size limit")
        if hashlib.sha256(data).hexdigest() != expected_zip_sha:
            raise GitHubSSEEError("GitHub artifact ZIP digest mismatch")
        return data

    @staticmethod
    def _read_report_zip(data):
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as archive:
                members = archive.infolist()
                if len(members) != 2 or {m.filename for m in members} != {_REPORT, _DIGEST}:
                    raise GitHubSSEEError("artifact must contain exactly the report and digest files")
                for member in members:
                    mode = member.external_attr >> 16
                    file_type = stat.S_IFMT(mode)
                    if member.is_dir() or file_type not in (0, stat.S_IFREG) or member.file_size > 1024 * 1024:
                        raise GitHubSSEEError("artifact contains a non-regular or oversized file")
                report = archive.read(_REPORT)
                digest_text = archive.read(_DIGEST).decode("ascii").strip()
        except (zipfile.BadZipFile, UnicodeDecodeError, KeyError):
            raise GitHubSSEEError("invalid report artifact ZIP") from None
        if not _SHA.fullmatch(digest_text):
            raise GitHubSSEEError("report digest sidecar is invalid")
        return report, digest_text

    def request_x70_approval(self, *, pull_number, verified, approval_callback):
        """Bind the final human gate to immutable PR, SHA, run, and report data.

        This method deliberately has no merge API. Approval only records that
        X70 accepted the evidence; a separately authorized operator action is
        still required for any merge.
        """
        if not isinstance(verified, dict) or not callable(approval_callback):
            raise ValueError("verified evidence and X70 approval callback are required")
        context = {"pull_number": int(pull_number), "head_sha": verified["report"]["head_sha"],
                   "run_id": verified["run_id"], "report_sha256": verified["report_sha256"]}
        current = self._api("GET", f"/pulls/{context['pull_number']}")
        if (current.get("head") or {}).get("sha") != context["head_sha"]:
            raise GitHubSSEEError("pull request head changed before X70 approval")
        if approval_callback(dict(context)) is not True:
            raise X70ApprovalRequired("candidate is halted at the X70 human approval gate")
        return context


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None
