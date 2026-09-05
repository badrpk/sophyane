#!/usr/bin/env python3
"""Print merged GitHub PRs or GitLab MRs represented between two refs."""
import argparse, os, sys
import requests


def main():
    p = argparse.ArgumentParser()
    p.add_argument("provider", choices=("github", "gitlab"))
    p.add_argument("project", help="GitHub owner/repo or GitLab project ID/path")
    p.add_argument("base")
    p.add_argument("head")
    p.add_argument("--token", default=os.getenv("GIT_TOKEN"))
    p.add_argument("--url", help="GitLab base URL", default="https://gitlab.com")
    a = p.parse_args()
    headers = {"Accept": "application/json"}
    if a.token:
        headers["Authorization"] = f"Bearer {a.token}"
    s = requests.Session()
    s.headers.update(headers)
    if a.provider == "github":
        root = f"https://api.github.com/repos/{a.project}"
        compare = s.get(f"{root}/compare/{a.base}...{a.head}", timeout=30)
        compare.raise_for_status()
        commits = {c["sha"] for c in compare.json().get("commits", [])}
        r = s.get(f"{root}/pulls", params={"state": "closed", "base": a.head}, timeout=30)
        r.raise_for_status()
        items = [x for x in r.json() if x.get("merged_at") and x.get("merge_commit_sha") in commits]
        title = lambda x: f"{x['title']} (#{x['number']})"
    else:
        root = f"{a.url.rstrip('/')}/api/v4/projects/{requests.utils.quote(a.project, safe='')}"
        compare = s.get(f"{root}/repository/compare", params={"from": a.base, "to": a.head}, timeout=30)
        compare.raise_for_status()
        commits = {c["id"] for c in compare.json().get("commits", [])}
        r = s.get(f"{root}/merge_requests", params={"state": "merged", "per_page": 100}, timeout=30)
        r.raise_for_status()
        items = [x for x in r.json() if x.get("merge_commit_sha") in commits]
        title = lambda x: f"{x['title']} (!{x['iid']})"
    for item in sorted(items, key=lambda x: x.get("merged_at", "")):
        print(f"- {title(item)} — {item.get('web_url') or item.get('html_url', '')}")


if __name__ == "__main__":
    try:
        main()
    except requests.RequestException as e:
        print(f"API request failed: {e}", file=sys.stderr)
        sys.exit(1)
