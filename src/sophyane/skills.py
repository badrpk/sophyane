"""Reusable agent skills (named prompt+tool bundles), like Cursor/Claude skills."""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from sophyane.version import __version__

SKILLS_DIR = Path.home() / ".local" / "share" / "sophyane" / "skills"
BUILTIN: dict[str, dict[str, Any]] = {
    "code-review": {
        "name": "code-review",
        "description": "Review a diff for bugs, security, and tests",
        "system": (
            "You are a senior code reviewer. Find bugs, security issues, missing tests, "
            "and suggest minimal patches. Be specific with file:line."
        ),
        "tools": ["search_code", "read_file", "run_tests"],
    },
    "debug": {
        "name": "debug",
        "description": "Root-cause failing tests or stack traces",
        "system": (
            "You are a debugger. Reproduce the failure path, identify root cause, "
            "propose the smallest fix, and verify with tests."
        ),
        "tools": ["run_tests", "read_file", "shell"],
    },
    "research": {
        "name": "research",
        "description": "Web research + cite sources into memory",
        "system": "Research thoroughly, cite URLs, separate facts from speculation.",
        "tools": ["web_fetch", "memory_write"],
    },
    "refactor": {
        "name": "refactor",
        "description": "Safe refactor with tests green",
        "system": "Refactor for clarity without behavior change; keep tests green.",
        "tools": ["search_code", "apply_patch", "run_tests"],
    },
    "security-audit": {
        "name": "security-audit",
        "description": "Threat-model and find vulns in code/config",
        "system": "Security auditor: OWASP top risks, secrets, injection, authz.",
        "tools": ["search_code", "read_file"],
    },
    "docs": {
        "name": "docs",
        "description": "Write or update project documentation",
        "system": "Write clear docs with examples; match project voice.",
        "tools": ["read_file", "write_file"],
    },
}


@dataclass
class Skill:
    name: str
    description: str
    system: str
    tools: list[str] = field(default_factory=list)
    source: str = "builtin"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _load_user_skills() -> dict[str, Skill]:
    out: dict[str, Skill] = {}
    SKILLS_DIR.mkdir(parents=True, exist_ok=True)
    for path in SKILLS_DIR.glob("*.json"):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            name = str(data.get("name") or path.stem)
            out[name] = Skill(
                name=name,
                description=str(data.get("description") or ""),
                system=str(data.get("system") or ""),
                tools=list(data.get("tools") or []),
                source=str(path),
            )
        except Exception:  # noqa: BLE001
            continue
    for path in SKILLS_DIR.glob("*.md"):
        text = path.read_text(encoding="utf-8", errors="replace")
        name = path.stem
        desc_m = re.search(r"^#\s+(.+)$", text, re.M)
        out[name] = Skill(
            name=name,
            description=(desc_m.group(1) if desc_m else name),
            system=text[:8000],
            tools=[],
            source=str(path),
        )
    return out


def list_skills() -> list[dict[str, Any]]:
    skills = {k: Skill(**{**v, "source": "builtin"}) for k, v in BUILTIN.items()}
    skills.update(_load_user_skills())
    return [s.to_dict() for s in sorted(skills.values(), key=lambda s: s.name)]


def get_skill(name: str) -> Skill | None:
    if name in BUILTIN:
        b = BUILTIN[name]
        return Skill(name=b["name"], description=b["description"], system=b["system"], tools=list(b["tools"]), source="builtin")
    return _load_user_skills().get(name)


def install_skill(name: str, description: str, system: str, tools: list[str] | None = None) -> dict[str, Any]:
    SKILLS_DIR.mkdir(parents=True, exist_ok=True)
    safe = re.sub(r"[^a-zA-Z0-9._-]+", "-", name).strip("-") or "skill"
    path = SKILLS_DIR / f"{safe}.json"
    payload = {"name": safe, "description": description, "system": system, "tools": tools or []}
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return {"ok": True, "path": str(path), "skill": payload}


def apply_skill_prompt(skill_name: str, user_prompt: str) -> dict[str, Any]:
    skill = get_skill(skill_name)
    if not skill:
        return {"ok": False, "error": f"unknown skill: {skill_name}", "available": [s["name"] for s in list_skills()]}
    return {
        "ok": True,
        "skill": skill.to_dict(),
        "system": skill.system,
        "prompt": user_prompt,
        "version": __version__,
    }
