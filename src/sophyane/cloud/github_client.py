"""GitHub REST API and Repository Client for Sophyane.

Supports:
  1) Reading user profile and repositories.
  2) Creating repositories, committing code, and managing PRs.
  3) Authentication via GITHUB_TOKEN, GH_TOKEN, or ~/.config/sophyane/github.env.
"""
from __future__ import annotations

import base64
import json
import os
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any


API_URL = "https://api.github.com"
ENV_FILE = Path.home() / ".config" / "sophyane" / "github.env"


@dataclass
class GitHubConfig:
    token: str
    username: str = ""

    @classmethod
    def from_env(cls, path: Path | None = None) -> "GitHubConfig":
        env: dict[str, str] = {}
        p = path or ENV_FILE
        if p.exists():
            for line in p.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip().strip('"').strip("'")
        for k in ("GITHUB_TOKEN", "GH_TOKEN", "GITHUB_USER", "GITHUB_USERNAME"):
            if os.environ.get(k):
                env[k] = os.environ[k].strip()
        token = env.get("GITHUB_TOKEN") or env.get("GH_TOKEN") or ""
        user = env.get("GITHUB_USER") or env.get("GITHUB_USERNAME") or ""
        return cls(token=token, username=user)


class GitHubClient:
    def __init__(self, config: GitHubConfig | None = None) -> None:
        self.config = config or GitHubConfig.from_env()

    def _headers(self) -> dict[str, str]:
        headers = {
            "Accept": "application/vnd.github+json",
            "User-Agent": "Sophyane-AI-Engine",
        }
        if self.config.token:
            headers["Authorization"] = f"Bearer {self.config.token}"
        return headers

    def _call(self, method: str, endpoint: str, data: dict[str, Any] | None = None) -> dict[str, Any]:
        url = f"{API_URL}/{endpoint.lstrip('/')}"
        payload = json.dumps(data).encode("utf-8") if data else None
        req = urllib.request.Request(url, data=payload, headers=self._headers(), method=method)
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                body = resp.read().decode("utf-8")
                return json.loads(body) if body else {}
        except urllib.error.HTTPError as e:
            err_body = e.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"GitHub API HTTP {e.code}: {err_body}")

    def get_authenticated_user(self) -> dict[str, Any]:
        return self._call("GET", "user")

    def list_user_repos(self, per_page: int = 50) -> list[dict[str, Any]]:
        return self._call("GET", f"user/repos?per_page={per_page}&sort=updated")

    def create_repo(self, name: str, description: str = "", private: bool = False) -> dict[str, Any]:
        data = {
            "name": name,
            "description": description,
            "private": private,
            "auto_init": True,
        }
        return self._call("POST", "user/repos", data=data)

    def commit_file(
        self,
        owner: str,
        repo: str,
        path: str,
        content: str,
        message: str,
        branch: str = "main",
        sha: str = "",
    ) -> dict[str, Any]:
        encoded = base64.b64encode(content.encode("utf-8")).decode("utf-8")
        data: dict[str, Any] = {
            "message": message,
            "content": encoded,
            "branch": branch,
        }
        if sha:
            data["sha"] = sha
        return self._call("PUT", f"repos/{owner}/{repo}/contents/{path.lstrip('/')}", data=data)

    def create_pull_request(
        self,
        owner: str,
        repo: str,
        title: str,
        head: str,
        base: str = "main",
        body: str = "",
    ) -> dict[str, Any]:
        data = {
            "title": title,
            "head": head,
            "base": base,
            "body": body,
        }
        return self._call("POST", f"repos/{owner}/{repo}/pulls", data=data)
