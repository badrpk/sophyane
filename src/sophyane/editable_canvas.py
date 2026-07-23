"""Persistent, reversible visual-document editing for Sophyane.

This module owns a scene rather than repeatedly rebuilding an entire prompt or
HTML document. It provides stable element identifiers, revisions, undo/redo,
structured edits and a rendered browser preview.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
import html
import json
from pathlib import Path
import re
from typing import Any
from uuid import uuid4


SCENE_FILE = "scene.json"
PREVIEW_FILE = "index.html"
HISTORY_DIR = ".sophyane-canvas-history"


def _slug(value: str) -> str:
    text = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return text or "element"


def _normalise_colour(value: str) -> str:
    value = value.strip()
    aliases = {
        "brown": "#7a4b2a",
        "dark brown": "#4a2b18",
        "light brown": "#a8754f",
        "black": "#111827",
        "white": "#ffffff",
        "green": "#15803d",
        "blue": "#2563eb",
        "red": "#dc2626",
        "beige": "#e8dcc8",
        "cream": "#f4ead7",
        "gold": "#b68b2e",
    }
    return aliases.get(value.lower(), value)


def default_scene(title: str = "Editable Portrait") -> dict[str, Any]:
    return {
        "document_id": f"canvas-{uuid4().hex[:10]}",
        "revision": 0,
        "title": title,
        "canvas": {
            "width": 900,
            "height": 900,
            "background": "#e8dcc8",
        },
        "elements": [
            {
                "id": "subject",
                "type": "portrait",
                "person": "Portrait subject",
                "attire": "formal attire",
                "pose": "standing",
                "x": 450,
                "y": 400,
                "width": 380,
                "height": 580,
                "colour": "#d6b08c",
                "z": 10,
            }
        ],
    }


def _element(scene: dict[str, Any], element_id: str) -> dict[str, Any]:
    for item in scene.get("elements", []):
        if str(item.get("id")) == element_id:
            return item
    raise KeyError(f"Unknown element: {element_id}")


def _subject(scene: dict[str, Any]) -> dict[str, Any]:
    try:
        return _element(scene, "subject")
    except KeyError:
        subject = {
            "id": "subject",
            "type": "portrait",
            "person": "Portrait subject",
            "attire": "formal attire",
            "pose": "standing",
            "x": 450,
            "y": 400,
            "width": 380,
            "height": 580,
            "colour": "#d6b08c",
            "z": 10,
        }
        scene.setdefault("elements", []).append(subject)
        return subject


def infer_operations(
    request: str,
    scene: dict[str, Any],
) -> list[dict[str, Any]]:
    """Translate common visual requests into bounded scene operations."""

    raw = request.strip()
    text = " ".join(raw.lower().split())
    operations: list[dict[str, Any]] = []

    if not text:
        return operations

    subject = _subject(scene)

    if "jinnah" in text:
        operations.append(
            {
                "op": "set",
                "element_id": subject["id"],
                "path": "person",
                "value": "Muhammad Ali Jinnah",
            }
        )

    if any(
        phrase in text
        for phrase in (
            "pakistani attire",
            "pakistani clothes",
            "pakistani clothing",
            "sherwani",
        )
    ):
        attire = (
            "traditional Pakistani sherwani"
            if "sherwani" in text or "pakistani" in text
            else "Pakistani attire"
        )
        operations.append(
            {
                "op": "set",
                "element_id": subject["id"],
                "path": "attire",
                "value": attire,
            }
        )

    if any(
        word in text
        for word in (
            "sit",
            "sits",
            "sitting",
            "seated",
            "seat",
            "seats",
        )
    ):
        operations.append(
            {
                "op": "set",
                "element_id": subject["id"],
                "path": "pose",
                "value": "seated",
            }
        )

    if "chair" in text:
        colour = "#7a4b2a"

        for candidate in (
            "dark brown",
            "light brown",
            "brown",
            "black",
            "white",
            "blue",
            "green",
            "red",
        ):
            if candidate in text:
                colour = _normalise_colour(candidate)
                break

        existing_ids = {
            str(item.get("id"))
            for item in scene.get("elements", [])
        }

        if "chair" in existing_ids:
            operations.append(
                {
                    "op": "set",
                    "element_id": "chair",
                    "path": "colour",
                    "value": colour,
                }
            )
        else:
            operations.append(
                {
                    "op": "add",
                    "element": {
                        "id": "chair",
                        "type": "chair",
                        "x": 450,
                        "y": 665,
                        "width": 440,
                        "height": 250,
                        "colour": colour,
                        "z": 4,
                    },
                }
            )

        operations.append(
            {
                "op": "set",
                "element_id": subject["id"],
                "path": "pose",
                "value": "seated",
            }
        )

    background_match = re.search(
        r"(?:background|backdrop)\s+(?:to\s+|is\s+|should\s+be\s+)?"
        r"(dark brown|light brown|brown|black|white|blue|green|red|beige|cream)",
        text,
    )

    if background_match:
        operations.append(
            {
                "op": "set_canvas",
                "path": "background",
                "value": _normalise_colour(
                    background_match.group(1)
                ),
            }
        )

    if "move" in text:
        delta_x = 0
        delta_y = 0

        if "left" in text:
            delta_x = -80
        elif "right" in text:
            delta_x = 80

        if "up" in text or "higher" in text:
            delta_y = -80
        elif "down" in text or "lower" in text:
            delta_y = 80

        if delta_x or delta_y:
            target = "chair" if "chair" in text else subject["id"]
            operations.append(
                {
                    "op": "move",
                    "element_id": target,
                    "dx": delta_x,
                    "dy": delta_y,
                }
            )

    if any(word in text for word in ("larger", "bigger", "increase size")):
        target = "chair" if "chair" in text else subject["id"]
        operations.append(
            {
                "op": "scale",
                "element_id": target,
                "factor": 1.15,
            }
        )

    if any(word in text for word in ("smaller", "reduce size")):
        target = "chair" if "chair" in text else subject["id"]
        operations.append(
            {
                "op": "scale",
                "element_id": target,
                "factor": 0.85,
            }
        )

    return operations


def apply_operations(
    scene: dict[str, Any],
    operations: list[dict[str, Any]],
) -> dict[str, Any]:
    updated = deepcopy(scene)

    for operation in operations:
        kind = str(operation.get("op") or "").strip()

        if kind == "add":
            element = deepcopy(operation.get("element") or {})
            element_id = str(element.get("id") or "").strip()

            if not element_id:
                element["id"] = _slug(
                    str(element.get("type") or "element")
                )

            ids = {
                str(item.get("id"))
                for item in updated.setdefault("elements", [])
            }

            if element["id"] in ids:
                raise ValueError(
                    f"Duplicate element ID: {element['id']}"
                )

            updated["elements"].append(element)

        elif kind == "remove":
            element_id = str(operation["element_id"])
            updated["elements"] = [
                item
                for item in updated.get("elements", [])
                if str(item.get("id")) != element_id
            ]

        elif kind == "set":
            item = _element(
                updated,
                str(operation["element_id"]),
            )
            item[str(operation["path"])] = deepcopy(
                operation.get("value")
            )

        elif kind == "set_canvas":
            updated.setdefault("canvas", {})[
                str(operation["path"])
            ] = deepcopy(operation.get("value"))

        elif kind == "move":
            item = _element(
                updated,
                str(operation["element_id"]),
            )
            item["x"] = int(item.get("x", 0)) + int(
                operation.get("dx", 0)
            )
            item["y"] = int(item.get("y", 0)) + int(
                operation.get("dy", 0)
            )

        elif kind == "scale":
            item = _element(
                updated,
                str(operation["element_id"]),
            )
            factor = float(operation.get("factor", 1.0))
            item["width"] = max(
                20,
                round(float(item.get("width", 100)) * factor),
            )
            item["height"] = max(
                20,
                round(float(item.get("height", 100)) * factor),
            )

        else:
            raise ValueError(f"Unsupported canvas operation: {kind}")

    return updated


def render_scene(scene: dict[str, Any]) -> str:
    canvas = scene.get("canvas", {})
    width = int(canvas.get("width", 900))
    height = int(canvas.get("height", 900))
    background = html.escape(
        str(canvas.get("background", "#e8dcc8"))
    )
    revision = int(scene.get("revision", 0))
    title = html.escape(str(scene.get("title", "Editable Canvas")))

    elements = sorted(
        scene.get("elements", []),
        key=lambda item: int(item.get("z", 0)),
    )

    rendered: list[str] = []

    for item in elements:
        element_id = html.escape(str(item.get("id", "element")))
        kind = str(item.get("type", "shape"))
        x = float(item.get("x", width / 2))
        y = float(item.get("y", height / 2))
        element_width = float(item.get("width", 200))
        element_height = float(item.get("height", 200))
        colour = html.escape(
            str(item.get("colour", "#64748b"))
        )
        left = x - element_width / 2
        top = y - element_height / 2
        z = int(item.get("z", 1))

        base_style = (
            f"left:{left}px;top:{top}px;"
            f"width:{element_width}px;height:{element_height}px;"
            f"z-index:{z};"
        )

        if kind == "portrait":
            person = html.escape(
                str(item.get("person", "Portrait subject"))
            )
            attire = html.escape(
                str(item.get("attire", "formal attire"))
            )
            pose = html.escape(
                str(item.get("pose", "standing"))
            )

            rendered.append(
                f"""
                <article class="element portrait"
                         data-element-id="{element_id}"
                         style="{base_style}">
                  <div class="portrait-head" style="background:{colour}">
                    <span class="portrait-hair"></span>
                    <span class="portrait-face">
                      <span class="eye left"></span>
                      <span class="eye right"></span>
                      <span class="portrait-line"></span>
                    </span>
                  </div>
                  <div class="portrait-body">
                    <div class="attire">{attire}</div>
                    <div class="pose">{pose}</div>
                  </div>
                  <strong>{person}</strong>
                </article>
                """
            )

        elif kind == "chair":
            rendered.append(
                f"""
                <div class="element chair"
                     data-element-id="{element_id}"
                     style="{base_style};--chair:{colour}">
                  <div class="chair-back"></div>
                  <div class="chair-seat"></div>
                  <div class="chair-leg left"></div>
                  <div class="chair-leg right"></div>
                  <span>Chair</span>
                </div>
                """
            )

        else:
            rendered.append(
                f"""
                <div class="element generic"
                     data-element-id="{element_id}"
                     style="{base_style};background:{colour}">
                  {html.escape(kind)}
                </div>
                """
            )

    scene_json = json.dumps(
        scene,
        ensure_ascii=False,
    ).replace("</", "<\\/")

    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{title}</title>
<style>
*{{box-sizing:border-box}}
html,body{{margin:0;min-height:100%;font-family:system-ui,-apple-system,Segoe UI,sans-serif;background:#111827;color:#f8fafc}}
body{{display:grid;grid-template-rows:auto 1fr;min-height:100vh}}
.toolbar{{position:sticky;top:0;z-index:1000;display:flex;align-items:center;gap:.75rem;padding:.8rem 1rem;background:#0f172ae8;backdrop-filter:blur(12px);border-bottom:1px solid #ffffff22}}
.toolbar strong{{margin-right:auto}}
.badge{{padding:.35rem .65rem;border-radius:999px;background:#ffffff14;font-size:.82rem}}
.help{{color:#cbd5e1;font-size:.82rem}}
.stage-wrap{{display:grid;place-items:center;padding:24px;overflow:auto}}
.stage{{position:relative;width:{width}px;height:{height}px;max-width:94vw;aspect-ratio:{width}/{height};background:{background};overflow:hidden;border-radius:20px;box-shadow:0 26px 80px #0009;border:1px solid #ffffff2a}}
.element{{position:absolute;transform-origin:center;user-select:none}}
.element:hover{{outline:3px solid #38bdf8;outline-offset:4px}}
.portrait{{display:flex;flex-direction:column;align-items:center;justify-content:flex-end;text-align:center}}
.portrait-head{{position:absolute;top:4%;width:44%;aspect-ratio:.78;border-radius:48% 48% 45% 45%;box-shadow:inset 0 -18px 28px #0002}}
.portrait-hair{{position:absolute;inset:-5% 4% 66%;border-radius:70% 70% 30% 30%;background:#20242a}}
.portrait-face{{position:absolute;inset:24% 12% 8%;border-radius:45%;background:#d8b18d}}
.eye{{position:absolute;top:38%;width:9%;height:4%;border-radius:100%;background:#252525}}
.eye.left{{left:24%}}.eye.right{{right:24%}}
.portrait-line{{position:absolute;left:35%;right:35%;bottom:22%;height:3%;background:#704536;border-radius:999px}}
.portrait-body{{width:84%;height:62%;display:flex;flex-direction:column;align-items:center;justify-content:center;padding:1rem;border-radius:40% 40% 12% 12%;background:linear-gradient(145deg,#172033,#374151);box-shadow:0 22px 44px #0004}}
.attire{{font-size:clamp(.8rem,2vw,1.3rem);font-weight:800}}
.pose{{margin-top:.45rem;color:#cbd5e1;text-transform:capitalize}}
.portrait strong{{position:absolute;bottom:3%;padding:.45rem .8rem;border-radius:999px;background:#0009}}
.chair{{color:white;text-align:center}}
.chair-back{{position:absolute;left:10%;right:10%;top:0;height:62%;border-radius:28px 28px 12px 12px;background:var(--chair);box-shadow:inset 0 0 0 8px #ffffff12}}
.chair-seat{{position:absolute;left:2%;right:2%;bottom:18%;height:27%;border-radius:18px;background:color-mix(in srgb,var(--chair) 85%,black)}}
.chair-leg{{position:absolute;bottom:0;width:11%;height:25%;background:color-mix(in srgb,var(--chair) 68%,black)}}
.chair-leg.left{{left:16%}}.chair-leg.right{{right:16%}}
.chair span{{position:absolute;bottom:31%;left:0;right:0;font-weight:800}}
.generic{{display:grid;place-items:center;border-radius:18px}}
@media(max-width:700px){{
  .stage{{transform-origin:top center}}
  .help{{display:none}}
}}
</style>
</head>
<body>
<header class="toolbar">
  <strong>{title}</strong>
  <span class="badge">Revision {revision}</span>
  <span class="badge">{len(elements)} elements</span>
  <span class="help">Edit the same scene with /edit, /undo and /redo</span>
</header>
<main class="stage-wrap">
  <section class="stage" id="stage">
    {''.join(rendered)}
  </section>
</main>
<script>
window.SOPHYANE_SCENE={scene_json};
document.querySelectorAll('[data-element-id]').forEach(element => {{
  element.addEventListener('click', () => {{
    document.querySelectorAll('[data-element-id]').forEach(item => {{
      item.style.outline='';
    }});
    element.style.outline='4px solid #fbbf24';
    element.style.outlineOffset='5px';
    console.log('Selected Sophyane element:', element.dataset.elementId);
  }});
}});
</script>
</body>
</html>
"""


@dataclass
class CanvasSession:
    workspace: Path
    scene: dict[str, Any] = field(default_factory=default_scene)
    undo_stack: list[dict[str, Any]] = field(default_factory=list)
    redo_stack: list[dict[str, Any]] = field(default_factory=list)

    @property
    def scene_path(self) -> Path:
        return self.workspace / SCENE_FILE

    @property
    def preview_path(self) -> Path:
        return self.workspace / PREVIEW_FILE

    @property
    def history_path(self) -> Path:
        return self.workspace / HISTORY_DIR

    @classmethod
    def open(
        cls,
        workspace: Path | str,
        title: str = "Editable Portrait",
    ) -> "CanvasSession":
        root = Path(workspace).expanduser().resolve()
        root.mkdir(parents=True, exist_ok=True)
        scene_path = root / SCENE_FILE

        if scene_path.is_file():
            scene = json.loads(
                scene_path.read_text(encoding="utf-8")
            )
        else:
            scene = default_scene(title)

        session = cls(workspace=root, scene=scene)
        session.save_snapshot("open")
        session.persist()
        return session

    def save_snapshot(self, reason: str) -> Path:
        self.history_path.mkdir(parents=True, exist_ok=True)
        revision = int(self.scene.get("revision", 0))
        path = self.history_path / f"{revision:06d}-{_slug(reason)}.json"
        path.write_text(
            json.dumps(
                self.scene,
                indent=2,
                ensure_ascii=False,
            )
            + "\n",
            encoding="utf-8",
        )
        return path

    def persist(self) -> None:
        self.workspace.mkdir(parents=True, exist_ok=True)

        scene_temp = self.scene_path.with_suffix(".json.tmp")
        scene_temp.write_text(
            json.dumps(
                self.scene,
                indent=2,
                ensure_ascii=False,
            )
            + "\n",
            encoding="utf-8",
        )
        scene_temp.replace(self.scene_path)

        preview_temp = self.preview_path.with_suffix(".html.tmp")
        preview_temp.write_text(
            render_scene(self.scene),
            encoding="utf-8",
        )
        preview_temp.replace(self.preview_path)

    def apply(
        self,
        operations: list[dict[str, Any]],
        reason: str = "edit",
    ) -> dict[str, Any]:
        if not operations:
            return self.scene

        self.undo_stack.append(deepcopy(self.scene))
        self.redo_stack.clear()

        self.scene = apply_operations(
            self.scene,
            operations,
        )
        self.scene["revision"] = (
            int(self.scene.get("revision", 0)) + 1
        )

        self.save_snapshot(reason)
        self.persist()
        return self.scene

    def edit(self, request: str) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        operations = infer_operations(request, self.scene)

        if not operations:
            raise ValueError(
                "No bounded visual edit could be inferred from the request."
            )

        return self.apply(operations, request), operations

    def undo(self) -> dict[str, Any]:
        if not self.undo_stack:
            raise ValueError("Nothing to undo.")

        self.redo_stack.append(deepcopy(self.scene))
        self.scene = self.undo_stack.pop()
        self.scene["revision"] = (
            int(self.scene.get("revision", 0)) + 1
        )
        self.save_snapshot("undo")
        self.persist()
        return self.scene

    def redo(self) -> dict[str, Any]:
        if not self.redo_stack:
            raise ValueError("Nothing to redo.")

        self.undo_stack.append(deepcopy(self.scene))
        self.scene = self.redo_stack.pop()
        self.scene["revision"] = (
            int(self.scene.get("revision", 0)) + 1
        )
        self.save_snapshot("redo")
        self.persist()
        return self.scene

    def status(self) -> dict[str, Any]:
        return {
            "workspace": str(self.workspace),
            "document_id": self.scene.get("document_id"),
            "revision": self.scene.get("revision", 0),
            "elements": [
                item.get("id")
                for item in self.scene.get("elements", [])
            ],
            "scene_file": str(self.scene_path),
            "preview_file": str(self.preview_path),
            "undo_depth": len(self.undo_stack),
            "redo_depth": len(self.redo_stack),
        }
