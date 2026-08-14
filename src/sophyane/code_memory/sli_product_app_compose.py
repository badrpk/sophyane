"""Bounded browser-product synthesis after SLI acquisition failure.

This capability does NOT weaken strict internet acquisition.

Execution policy:

1. SLI memory/acquisition gets first opportunity to reuse validated code.
2. If acquisition cannot produce a validated browser product, this module
   constructs a deterministic functional product shell.
3. The local GGUF model may propose bounded visual/product direction only.
4. Deterministic validation remains authoritative.
5. The finished artifact is browser/CDP validated before success.

The current email implementation is a functional browser prototype.
It intentionally does not claim to provide real SMTP/IMAP delivery,
remote account authentication or production mail-server infrastructure.
"""
from __future__ import annotations

from dataclasses import dataclass
import html
import json
import os
import re
from pathlib import Path
from typing import Callable


Progress = Callable[[str], None]


@dataclass(frozen=True)
class ProductDesign:
    generated: bool
    concept: str
    accent: str
    accent2: str
    density: str
    mood: str
    reason: str = ""


_EMAIL_PRODUCT_CUES = (
    "email service",
    "email app",
    "mail app",
    "mail service",
    "gmail",
    "inbox",
    "webmail",
)


_PRODUCT_BUILD_CUES = (
    "make",
    "create",
    "build",
    "develop",
    "generate",
    "implement",
    "design",
)


def is_product_app_request(
    request: str,
) -> bool:
    text = " ".join(
        str(
            request
            or ""
        ).casefold().split()
    )

    constructive = any(
        cue in text
        for cue in _PRODUCT_BUILD_CUES
    )

    email_product = any(
        cue in text
        for cue in _EMAIL_PRODUCT_CUES
    )

    # SOPHYANE_CANONICAL_PRODUCT_PREDICATE_V2
    #
    # Explicit browser/web application nouns are already strong positive
    # evidence of a browser product when paired with a construction verb.
    # Do not require an additional noun such as "dashboard" or "client".
    #
    # More generic nouns such as "application" and "service" still require
    # a second product-oriented cue so backend/API/service construction
    # cannot accidentally become a browser product.
    explicit_browser_product = any(
        cue in text
        for cue in (
            "web app",
            "browser app",
        )
    )

    broader_product = (
        any(
            cue in text
            for cue in (
                "website",
                "application",
                "service",
            )
        )
        and any(
            cue in text
            for cue in (
                "dashboard",
                "workspace",
                "client",
                "platform",
                "management",
                "crm",
                "calendar",
                "chat",
                "messaging",
            )
        )
    )

    return constructive and (
        email_product
        or explicit_browser_product
        or broader_product
    )


def _email_request(
    request: str,
) -> bool:
    text = " ".join(
        str(
            request
            or ""
        ).casefold().split()
    )

    return any(
        cue in text
        for cue in _EMAIL_PRODUCT_CUES
    )


def _extract_json(
    value: str,
) -> dict:
    text = str(
        value
        or ""
    ).strip()

    fenced = re.search(
        r"```(?:json)?\s*(\{.*\})\s*```",
        text,
        flags=re.I | re.S,
    )

    if fenced:
        text = fenced.group(1)

    start = text.find(
        "{"
    )

    end = text.rfind(
        "}"
    )

    if (
        start < 0
        or end <= start
    ):
        return {}

    try:
        parsed = json.loads(
            text[
                start:
                end + 1
            ]
        )
    except json.JSONDecodeError:
        return {}

    return (
        parsed
        if isinstance(
            parsed,
            dict,
        )
        else {}
    )


def _clean_text(
    value,
    *,
    limit: int,
) -> str:
    return " ".join(
        str(
            value
            or ""
        ).strip().split()
    )[:limit]


def _valid_colour(
    value: str,
    fallback: str,
) -> str:
    candidate = str(
        value
        or ""
    ).strip()

    if re.fullmatch(
        r"#[0-9a-fA-F]{6}",
        candidate,
    ):
        return candidate

    return fallback



_CLAIM_FORBIDDEN_PHRASES = (
    "gmail",
    "all gmail",
    "all features",
    "all services",
    "every feature",
    "every service",
    "as good as",
    "fully featured",
    "full-featured",
    "complete email service",
    "production email",
    "production mail",
    "smtp",
    "imap",
)


def _design_claim_problem(
    concept: str,
    mood: str,
) -> str:
    """Reject bounded design metadata that overclaims product capability."""
    combined = " ".join(
        (
            str(concept or ""),
            str(mood or ""),
        )
    ).casefold()

    for phrase in _CLAIM_FORBIDDEN_PHRASES:
        if phrase in combined:
            return (
                "local design metadata contains "
                "unsupported capability claim: "
                + phrase
            )

    return ""


def _deterministic_design(
    *,
    reason: str = "",
) -> ProductDesign:
    return ProductDesign(
        generated=False,
        concept="Focused Mail Workspace",
        accent="#5b7cfa",
        accent2="#8d63ff",
        density="comfortable",
        mood="calm productivity",
        reason=reason,
    )


def _local_design(
    request: str,
    progress: Progress,
) -> ProductDesign:
    """Allow local GGUF to vary only bounded presentation metadata."""
    disabled = str(
        os.environ.get(
            "SOPHYANE_DISABLE_GENERATIVE_PRODUCT_DESIGN",
            "",
        )
    ).strip().casefold() in {
        "1",
        "true",
        "yes",
        "on",
    }

    if disabled:
        return _deterministic_design(
            reason="generative product design disabled"
        )

    try:
        from sophyane.providers.local_gguf import (
            LocalGgufProvider,
        )

        provider = LocalGgufProvider(
            timeout=90,
            temperature=0.45,
            max_tokens=300,
        )

        prompt = f"""
Create bounded visual direction for this browser product:

{request}

The product is an email workspace.

Return ONE JSON object only:

{{
  "concept": "short product concept",
  "accent": "#RRGGBB",
  "accent2": "#RRGGBB",
  "density": "compact|comfortable|spacious",
  "mood": "short visual mood"
}}

Rules:
- no HTML
- no JavaScript
- no URLs
- no external assets
- no factual claims
- do not remove or redefine product functionality
- exactly those five keys
""".strip()

        response = provider.generate(
            prompt,
            (
                "You are Sophyane's bounded local product-design worker. "
                "Return JSON only. Functional behavior remains deterministic."
            ),
        )

        payload = _extract_json(
            response
        )

        concept = _clean_text(
            payload.get(
                "concept"
            ),
            limit=80,
        )

        mood = _clean_text(
            payload.get(
                "mood"
            ),
            limit=100,
        )

        density = _clean_text(
            payload.get(
                "density"
            ),
            limit=20,
        ).casefold()

        if density not in {
            "compact",
            "comfortable",
            "spacious",
        }:
            density = "comfortable"

        if not concept:
            raise ValueError(
                "local design concept missing"
            )

        if not mood:
            raise ValueError(
                "local design mood missing"
            )

        claim_problem = _design_claim_problem(
            concept,
            mood,
        )

        if claim_problem:
            raise ValueError(
                claim_problem
            )

        design = ProductDesign(
            generated=True,
            concept=concept,
            accent=_valid_colour(
                payload.get(
                    "accent"
                ),
                "#5b7cfa",
            ),
            accent2=_valid_colour(
                payload.get(
                    "accent2"
                ),
                "#8d63ff",
            ),
            density=density,
            mood=mood,
        )

        progress(
            "SLI product synthesis: accepted bounded "
            f"local design '{design.concept}'"
        )

        return design

    except Exception as error:
        progress(
            "SLI product synthesis: local design unavailable "
            "or rejected; deterministic product design retained"
        )

        return _deterministic_design(
            reason=(
                f"{type(error).__name__}: {error}"
            ),
        )


def _email_document(
    request: str,
    design: ProductDesign,
) -> str:
    concept = html.escape(
        design.concept
    )

    mood = html.escape(
        design.mood
    )

    request_text = html.escape(
        request[:500]
    )

    density_gap = {
        "compact": "7px",
        "comfortable": "11px",
        "spacious": "16px",
    }.get(
        design.density,
        "11px",
    )

    return f"""<!doctype html>
<html lang="en"
  data-product-family="email-workspace"
  data-design-generated="{str(design.generated).lower()}"
  data-design-density="{html.escape(design.density, quote=True)}">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="description"
 content="Functional Sophyane browser email workspace prototype">
<title>Sophyane Mail — {concept}</title>

<style>
:root {{
  --bg:#f7f8fc;
  --panel:#ffffff;
  --panel2:#f0f2f8;
  --text:#1c2130;
  --muted:#6b7280;
  --line:#e1e4ec;
  --accent:{design.accent};
  --accent2:{design.accent2};
  --danger:#c83f49;
  --gap:{density_gap};
  --radius:17px;
}}

* {{
  box-sizing:border-box;
}}

html,
body {{
  margin:0;
  min-height:100%;
  font-family:
    Inter,
    ui-sans-serif,
    system-ui,
    -apple-system,
    "Segoe UI",
    sans-serif;
  background:var(--bg);
  color:var(--text);
}}

body.dark {{
  --bg:#11131a;
  --panel:#191c25;
  --panel2:#222631;
  --text:#f5f7fb;
  --muted:#a2a8b5;
  --line:#303542;
}}

button,
input,
textarea,
select {{
  font:inherit;
}}

button {{
  cursor:pointer;
}}

.app {{
  min-height:100vh;
  display:grid;
  grid-template-columns:250px minmax(0,1fr);
}}

.sidebar {{
  border-right:1px solid var(--line);
  background:var(--panel);
  padding:16px;
  display:flex;
  flex-direction:column;
  gap:12px;
}}

.brand {{
  display:flex;
  gap:10px;
  align-items:center;
  padding:6px 5px 14px;
  font-weight:900;
  font-size:1.08rem;
}}

.logo {{
  width:36px;
  height:36px;
  display:grid;
  place-items:center;
  border-radius:12px;
  color:white;
  background:
    linear-gradient(
      135deg,
      var(--accent),
      var(--accent2)
    );
}}

.compose-btn {{
  border:0;
  color:white;
  padding:13px 15px;
  border-radius:14px;
  font-weight:800;
  background:
    linear-gradient(
      135deg,
      var(--accent),
      var(--accent2)
    );
  box-shadow:
    0 10px 30px
    color-mix(
      in srgb,
      var(--accent) 25%,
      transparent
    );
}}

.nav-list {{
  display:grid;
  gap:5px;
}}

.nav-item {{
  border:0;
  background:transparent;
  color:inherit;
  display:flex;
  align-items:center;
  justify-content:space-between;
  text-align:left;
  padding:10px 12px;
  border-radius:11px;
}}

.nav-item:hover,
.nav-item.active {{
  background:var(--panel2);
}}

.nav-item.active {{
  color:var(--accent);
  font-weight:800;
}}

.sidebar-foot {{
  margin-top:auto;
  color:var(--muted);
  font-size:.78rem;
  line-height:1.5;
}}

.shell {{
  min-width:0;
  display:grid;
  grid-template-rows:auto auto minmax(0,1fr);
}}

.topbar {{
  background:var(--panel);
  border-bottom:1px solid var(--line);
  padding:12px 18px;
  display:flex;
  align-items:center;
  gap:12px;
}}

.search-wrap {{
  flex:1;
  max-width:720px;
  position:relative;
}}

.search {{
  width:100%;
  border:1px solid var(--line);
  border-radius:14px;
  background:var(--panel2);
  color:inherit;
  padding:12px 15px;
  outline:none;
}}

.search:focus {{
  border-color:var(--accent);
}}

.icon-btn {{
  border:1px solid var(--line);
  background:var(--panel);
  color:inherit;
  width:42px;
  height:42px;
  border-radius:12px;
}}

.toolbar {{
  display:flex;
  gap:8px;
  align-items:center;
  padding:10px 18px;
  border-bottom:1px solid var(--line);
  background:var(--panel);
  overflow:auto;
}}

.tool-btn {{
  border:1px solid var(--line);
  color:inherit;
  background:var(--panel);
  border-radius:10px;
  padding:8px 11px;
  white-space:nowrap;
}}

.content {{
  min-height:0;
  display:grid;
  grid-template-columns:minmax(320px,44%) minmax(0,1fr);
}}

.list-pane {{
  min-width:0;
  border-right:1px solid var(--line);
  background:var(--panel);
  overflow:auto;
}}

.list-head {{
  padding:18px;
  border-bottom:1px solid var(--line);
}}

.list-head h1 {{
  margin:0 0 5px;
  font-size:1.35rem;
}}

.list-head p {{
  margin:0;
  color:var(--muted);
  font-size:.86rem;
}}

.message-list {{
  display:grid;
}}

.message {{
  display:grid;
  grid-template-columns:auto 1fr auto;
  gap:10px;
  padding:13px 14px;
  border-bottom:1px solid var(--line);
  cursor:pointer;
  background:var(--panel);
}}

.message:hover {{
  background:var(--panel2);
}}

.message.active {{
  box-shadow:
    inset 3px 0 var(--accent);
  background:var(--panel2);
}}

.message.unread .sender,
.message.unread .subject {{
  font-weight:800;
}}

.star {{
  border:0;
  background:transparent;
  color:#b4bac6;
  padding:2px;
  font-size:1.1rem;
}}

.star.on {{
  color:#e7a928;
}}

.msg-main {{
  min-width:0;
}}

.msg-row {{
  display:flex;
  gap:8px;
  align-items:center;
}}

.sender {{
  overflow:hidden;
  text-overflow:ellipsis;
  white-space:nowrap;
}}

.subject {{
  margin-top:4px;
  overflow:hidden;
  text-overflow:ellipsis;
  white-space:nowrap;
}}

.snippet {{
  margin-top:4px;
  color:var(--muted);
  overflow:hidden;
  text-overflow:ellipsis;
  white-space:nowrap;
  font-size:.84rem;
}}

.time {{
  color:var(--muted);
  font-size:.72rem;
  white-space:nowrap;
}}

.reader {{
  min-width:0;
  overflow:auto;
  background:var(--bg);
  padding:clamp(18px,4vw,42px);
}}

.reader-card {{
  max-width:830px;
  margin:auto;
  background:var(--panel);
  border:1px solid var(--line);
  border-radius:20px;
  padding:clamp(20px,4vw,38px);
}}

.reader-empty {{
  color:var(--muted);
  text-align:center;
  padding:80px 20px;
}}

.reader h2 {{
  margin:0 0 16px;
  font-size:clamp(1.6rem,3vw,2.35rem);
}}

.mobile-back {{
  display:none;
  margin-bottom:16px;
}}

.mail-meta {{
  display:flex;
  gap:12px;
  align-items:center;
  margin-bottom:25px;
}}

.avatar {{
  width:44px;
  height:44px;
  display:grid;
  place-items:center;
  flex:0 0 auto;
  border-radius:50%;
  color:white;
  background:
    linear-gradient(
      135deg,
      var(--accent),
      var(--accent2)
    );
  font-weight:900;
}}

.mail-body {{
  line-height:1.75;
  white-space:pre-wrap;
}}

.tag {{
  display:inline-flex;
  padding:4px 8px;
  margin-left:6px;
  color:var(--accent);
  background:
    color-mix(
      in srgb,
      var(--accent) 12%,
      transparent
    );
  border-radius:999px;
  font-size:.7rem;
}}

.modal {{
  position:fixed;
  inset:0;
  z-index:80;
  display:none;
  place-items:end center;
  background:rgba(0,0,0,.34);
  padding:18px;
}}

.modal.open {{
  display:grid;
}}

.compose-card {{
  width:min(700px,100%);
  max-height:90vh;
  display:grid;
  grid-template-rows:auto auto auto minmax(220px,1fr) auto;
  background:var(--panel);
  border:1px solid var(--line);
  border-radius:20px;
  overflow:hidden;
  box-shadow:0 30px 90px rgba(0,0,0,.28);
}}

.compose-head {{
  display:flex;
  justify-content:space-between;
  align-items:center;
  padding:13px 16px;
  background:var(--panel2);
  font-weight:800;
}}

.compose-field {{
  width:100%;
  border:0;
  border-bottom:1px solid var(--line);
  background:var(--panel);
  color:inherit;
  padding:13px 16px;
  outline:none;
}}

.compose-body {{
  resize:none;
  border:0;
  background:var(--panel);
  color:inherit;
  padding:16px;
  outline:none;
  min-height:220px;
}}

.compose-actions {{
  display:flex;
  justify-content:space-between;
  align-items:center;
  padding:13px 16px;
  border-top:1px solid var(--line);
}}

.send-btn {{
  border:0;
  background:var(--accent);
  color:white;
  padding:10px 22px;
  border-radius:11px;
  font-weight:800;
}}

.close-btn {{
  border:0;
  background:transparent;
  color:inherit;
  font-size:1.3rem;
}}

.toast {{
  position:fixed;
  right:18px;
  bottom:18px;
  padding:12px 16px;
  background:#111827;
  color:white;
  border-radius:12px;
  opacity:0;
  transform:translateY(15px);
  pointer-events:none;
  transition:.25s;
  z-index:100;
}}

.toast.show {{
  opacity:1;
  transform:none;
}}

.settings {{
  position:fixed;
  inset:0 0 0 auto;
  width:min(390px,92vw);
  z-index:70;
  padding:22px;
  background:var(--panel);
  border-left:1px solid var(--line);
  transform:translateX(102%);
  transition:.3s;
}}

.settings.open {{
  transform:none;
}}

.settings label {{
  display:grid;
  gap:7px;
  margin:18px 0;
}}

.settings select {{
  border:1px solid var(--line);
  background:var(--panel2);
  color:inherit;
  border-radius:10px;
  padding:10px;
}}

.scope-note {{
  margin-top:14px;
  padding:12px;
  border:1px solid var(--line);
  border-radius:12px;
  color:var(--muted);
  font-size:.75rem;
  line-height:1.55;
}}

@media(max-width:860px) {{
  .app {{
    grid-template-columns:78px minmax(0,1fr);
  }}

  .sidebar {{
    padding:12px 9px;
  }}

  .brand span,
  .nav-label,
  .sidebar-foot {{
    display:none;
  }}

  .compose-btn {{
    width:56px;
    height:56px;
    margin-inline:auto;
    padding:0;
    display:grid;
    place-items:center;
    font-size:1.5rem;
    overflow:hidden;
  }}

  .compose-btn span {{
    display:none;
  }}

  .nav-item {{
    justify-content:center;
  }}

  .nav-count {{
    display:none;
  }}
}}

@media(max-width:650px) {{
  .content {{
    grid-template-columns:1fr;
  }}

  .reader {{
    display:none;
    padding:12px;
  }}

  .reader.mobile-open {{
    display:block;
  }}

  .list-pane.mobile-hidden {{
    display:none;
  }}

  .mobile-back {{
    display:inline-flex;
    align-items:center;
    gap:6px;
  }}

  .reader-card {{
    border-radius:14px;
    padding:18px;
  }}

  .topbar {{
    padding-inline:10px;
  }}

  .toolbar {{
    padding-inline:10px;
  }}
}}

@media(prefers-reduced-motion:reduce) {{
  * {{
    scroll-behavior:auto!important;
    transition:none!important;
  }}
}}
</style>
</head>

<body>

<div class="app">

<aside class="sidebar">
  <div class="brand">
    <div class="logo">M</div>
    <span>Sophyane Mail</span>
  </div>

  <button
    class="compose-btn"
    id="composeButton"
  >
    ＋ <span>Compose</span>
  </button>

  <nav
    class="nav-list"
    id="folders"
    aria-label="Mailbox folders"
  ></nav>

  <div class="sidebar-foot">
    <strong>{concept}</strong><br>
    {mood}
    <div class="scope-note">
      Browser product prototype. Mail transport,
      remote authentication and production SMTP/IMAP
      infrastructure are not simulated as completed services.
    </div>
  </div>
</aside>

<section class="shell">

  <header class="topbar">

    <div class="search-wrap">
      <input
        class="search"
        id="search"
        type="search"
        placeholder="Search mail"
        aria-label="Search mail"
      >
    </div>

    <button
      class="icon-btn"
      id="themeButton"
      title="Theme"
      aria-label="Toggle theme"
    >
      ◐
    </button>

    <button
      class="icon-btn"
      id="settingsButton"
      title="Settings"
      aria-label="Open settings"
    >
      ⚙
    </button>

  </header>

  <div class="toolbar">

    <button
      class="tool-btn"
      id="refreshButton"
    >
      ↻ Refresh
    </button>

    <button
      class="tool-btn"
      id="markReadButton"
    >
      Mark read
    </button>

    <button
      class="tool-btn"
      id="archiveButton"
    >
      Archive
    </button>

    <button
      class="tool-btn"
      id="spamButton"
    >
      Spam
    </button>

    <button
      class="tool-btn"
      id="deleteButton"
    >
      Delete
    </button>

  </div>

  <main class="content">

    <section
      class="list-pane"
      id="listPane"
    >

      <div class="list-head">
        <h1 id="folderTitle">
          Inbox
        </h1>

        <p id="folderSummary">
          Your messages
        </p>
      </div>

      <div
        class="message-list"
        id="messageList"
      ></div>

    </section>

    <section
      class="reader"
      id="reader"
    >

      <div class="reader-empty">
        Select a message to read it.
      </div>

    </section>

  </main>

</section>
</div>


<section
  class="modal"
  id="composeModal"
  aria-label="Compose message"
>

  <div class="compose-card">

    <div class="compose-head">
      <span>New message</span>

      <button
        class="close-btn"
        id="closeCompose"
        aria-label="Close compose"
      >
        ×
      </button>
    </div>

    <input
      class="compose-field"
      id="composeTo"
      placeholder="Recipients"
      aria-label="Recipients"
    >

    <input
      class="compose-field"
      id="composeSubject"
      placeholder="Subject"
      aria-label="Subject"
    >

    <textarea
      class="compose-body"
      id="composeBody"
      placeholder="Write a message…"
      aria-label="Message body"
    ></textarea>

    <div class="compose-actions">

      <button
        class="send-btn"
        id="sendButton"
      >
        Send
      </button>

      <button
        class="tool-btn"
        id="saveDraftButton"
      >
        Save draft
      </button>

    </div>

  </div>

</section>


<aside
  class="settings"
  id="settingsPanel"
>

  <button
    class="close-btn"
    id="closeSettings"
    aria-label="Close settings"
  >
    ×
  </button>

  <h2>Settings</h2>

  <label>
    Inbox density
    <select id="densitySelect">
      <option>comfortable</option>
      <option>compact</option>
      <option>spacious</option>
    </select>
  </label>

  <label>
    Default category
    <select id="categorySelect">
      <option>Primary</option>
      <option>Updates</option>
      <option>Social</option>
    </select>
  </label>

  <div class="scope-note">
    Request captured by Sophyane:<br>
    {request_text}
  </div>

</aside>


<div
  class="toast"
  id="toast"
  role="status"
></div>


<script>
const STORE='sophyane-mail-state-v1';

const seed={{
  activeFolder:'inbox',
  selected:null,
  dark:false,
  messages:[
    {{
      id:1,
      folder:'inbox',
      sender:'Product Team',
      email:'product@example.com',
      subject:'Welcome to your new mail workspace',
      body:'This browser product demonstrates mailbox navigation, search, reading, starring, archive, spam, delete, compose, drafts and sent-mail workflows.\\n\\nProduction SMTP/IMAP transport would be implemented as a separate backend service.',
      time:'09:40',
      unread:true,
      starred:true,
      labels:['Primary']
    }},
    {{
      id:2,
      folder:'inbox',
      sender:'Design Review',
      email:'design@example.com',
      subject:'Interface review notes',
      body:'The mailbox is responsive and keeps state locally. Try starring this message, searching for it, or moving it to Archive.',
      time:'08:22',
      unread:true,
      starred:false,
      labels:['Updates']
    }},
    {{
      id:3,
      folder:'inbox',
      sender:'Aisha',
      email:'aisha@example.com',
      subject:'Lunch tomorrow?',
      body:'Are we still meeting tomorrow? Reply when you get a chance.',
      time:'Yesterday',
      unread:false,
      starred:false,
      labels:['Primary']
    }},
    {{
      id:4,
      folder:'sent',
      sender:'Me',
      email:'team@example.com',
      subject:'Project status',
      body:'The current browser prototype is ready for product review.',
      time:'Mon',
      unread:false,
      starred:false,
      labels:['Sent']
    }},
    {{
      id:5,
      folder:'drafts',
      sender:'Draft',
      email:'partner@example.com',
      subject:'Partnership follow-up',
      body:'Thanks for the discussion. I wanted to follow up regarding…',
      time:'Draft',
      unread:false,
      starred:false,
      labels:['Draft']
    }}
  ]
}};

let state=load();
let query='';

const folders=[
  ['inbox','Inbox','📥'],
  ['starred','Starred','★'],
  ['sent','Sent','➤'],
  ['drafts','Drafts','📝'],
  ['archive','Archive','▣'],
  ['spam','Spam','!'],
  ['trash','Trash','🗑']
];

function load(){{
  try{{
    return JSON.parse(localStorage.getItem(STORE))||structuredClone(seed);
  }}catch(_e){{
    return structuredClone(seed);
  }}
}}

function save(){{
  localStorage.setItem(STORE,JSON.stringify(state));
}}

function toast(message){{
  const el=document.querySelector('#toast');
  el.textContent=message;
  el.classList.add('show');
  setTimeout(()=>el.classList.remove('show'),1800);
}}

function currentMessages(){{
  let items=[...state.messages];

  if(state.activeFolder==='starred'){{
    items=items.filter(item=>item.starred);
  }}else{{
    items=items.filter(
      item=>item.folder===state.activeFolder
    );
  }}

  if(query){{
    const q=query.toLowerCase();

    items=items.filter(
      item=>
        (
          item.sender+' '+
          item.email+' '+
          item.subject+' '+
          item.body+' '+
          item.labels.join(' ')
        )
        .toLowerCase()
        .includes(q)
    );
  }}

  return items;
}}

function unreadCount(){{
  return state.messages.filter(
    item=>
      item.folder==='inbox'
      && item.unread
  ).length;
}}

function folderCount(key){{
  if(key==='starred'){{
    return state.messages.filter(
      item=>item.starred
    ).length;
  }}

  return state.messages.filter(
    item=>item.folder===key
  ).length;
}}

function renderFolders(){{
  const root=document.querySelector('#folders');

  root.innerHTML=folders.map(
    ([key,label,icon])=>`
      <button
        class="nav-item ${{state.activeFolder===key?'active':''}}"
        data-folder="${{key}}"
      >
        <span>
          ${{icon}}
          <span class="nav-label">${{label}}</span>
        </span>
        <span class="nav-count">
          ${{key==='inbox'?unreadCount():folderCount(key)}}
        </span>
      </button>
    `
  ).join('');

  root.querySelectorAll(
    '[data-folder]'
  ).forEach(
    button=>button.addEventListener(
      'click',
      ()=>{{
        state.activeFolder=button.dataset.folder;
        state.selected=null;
        save();
        render();
      }}
    )
  );
}}

function renderList(){{
  const items=currentMessages();

  const names={{
    inbox:'Inbox',
    starred:'Starred',
    sent:'Sent',
    drafts:'Drafts',
    archive:'Archive',
    spam:'Spam',
    trash:'Trash'
  }};

  document.querySelector(
    '#folderTitle'
  ).textContent=
    names[state.activeFolder]||'Mail';

  document.querySelector(
    '#folderSummary'
  ).textContent=
    `${{items.length}} message${{items.length===1?'':'s'}}`;

  const root=document.querySelector(
    '#messageList'
  );

  if(!items.length){{
    root.innerHTML=`
      <div class="reader-empty">
        No messages here.
      </div>
    `;
    return;
  }}

  root.innerHTML=items.map(
    item=>`
      <article
        class="message
          ${{item.unread?'unread':''}}
          ${{state.selected===item.id?'active':''}}"
        data-message="${{item.id}}"
        tabindex="0"
      >
        <button
          class="star ${{item.starred?'on':''}}"
          data-star="${{item.id}}"
          aria-label="Toggle star"
        >
          ★
        </button>

        <div class="msg-main">
          <div class="msg-row">
            <span class="sender">
              ${{escapeHtml(item.sender)}}
            </span>
          </div>

          <div class="subject">
            ${{escapeHtml(item.subject)}}
          </div>

          <div class="snippet">
            ${{escapeHtml(item.body)}}
          </div>
        </div>

        <time class="time">
          ${{escapeHtml(item.time)}}
        </time>
      </article>
    `
  ).join('');

  root.querySelectorAll(
    '[data-message]'
  ).forEach(
    card=>{{
      const open=()=>{{
        state.selected=+card.dataset.message;

        const item=state.messages.find(
          row=>row.id===state.selected
        );

        if(item){{
          item.unread=false;
        }}

        save();
        render();
      }};

      card.addEventListener(
        'click',
        event=>{{
          if(
            event.target.closest(
              '[data-star]'
            )
          ){{
            return;
          }}

          open();
        }}
      );

      card.addEventListener(
        'keydown',
        event=>{{
          if(event.key==='Enter'){{
            open();
          }}
        }}
      );
    }}
  );

  root.querySelectorAll(
    '[data-star]'
  ).forEach(
    button=>button.addEventListener(
      'click',
      event=>{{
        event.stopPropagation();

        const item=state.messages.find(
          row=>row.id===+button.dataset.star
        );

        if(item){{
          item.starred=!item.starred;
          save();
          render();
        }}
      }}
    )
  );
}}

function renderReader(){{
  const root=document.querySelector(
    '#reader'
  );

  const listPane=document.querySelector(
    '#listPane'
  );

  const item=state.messages.find(
    row=>row.id===state.selected
  );

  if(!item){{
    root.classList.remove(
      'mobile-open'
    );

    listPane.classList.remove(
      'mobile-hidden'
    );

    root.innerHTML=`
      <div class="reader-empty">
        Select a message to read it.
      </div>
    `;
    return;
  }}

  root.classList.add(
    'mobile-open'
  );

  listPane.classList.add(
    'mobile-hidden'
  );

  root.innerHTML=`
    <article class="reader-card">

      <button
        class="tool-btn mobile-back"
        id="backToListButton"
      >
        ← Back to ${{escapeHtml(
          state.activeFolder==='inbox'
            ? 'Inbox'
            : state.activeFolder
        )}}
      </button>

      <h2>
        ${{escapeHtml(item.subject)}}
      </h2>

      <div class="mail-meta">
        <div class="avatar">
          ${{escapeHtml(item.sender.slice(0,1).toUpperCase())}}
        </div>

        <div>
          <strong>
            ${{escapeHtml(item.sender)}}
          </strong>

          <div class="snippet">
            ${{escapeHtml(item.email)}}
          </div>
        </div>
      </div>

      <div>
        ${{item.labels.map(
          label=>`
            <span class="tag">
              ${{escapeHtml(label)}}
            </span>
          `
        ).join('')}}
      </div>

      <p class="mail-body">
        ${{escapeHtml(item.body)}}
      </p>

      <div class="toolbar">
        <button
          class="tool-btn"
          id="replyButton"
        >
          Reply
        </button>

        <button
          class="tool-btn"
          id="forwardButton"
        >
          Forward
        </button>
      </div>
    </article>
  `;

  document.querySelector(
    '#backToListButton'
  ).onclick=()=>{{
    state.selected=null;
    save();
    render();
  }};

  document.querySelector(
    '#replyButton'
  ).onclick=()=>{{
    openCompose();

    document.querySelector(
      '#composeTo'
    ).value=item.email;

    document.querySelector(
      '#composeSubject'
    ).value=
      item.subject.startsWith('Re:')
        ? item.subject
        : 'Re: '+item.subject;
  }};

  document.querySelector(
    '#forwardButton'
  ).onclick=()=>{{
    openCompose();

    document.querySelector(
      '#composeSubject'
    ).value=
      item.subject.startsWith('Fwd:')
        ? item.subject
        : 'Fwd: '+item.subject;

    document.querySelector(
      '#composeBody'
    ).value=
      '\\n\\n---------- Forwarded message ----------\\n'
      +item.body;
  }};
}}

function escapeHtml(value){{
  return String(value)
    .replaceAll('&','&amp;')
    .replaceAll('<','&lt;')
    .replaceAll('>','&gt;')
    .replaceAll('"','&quot;')
    .replaceAll("'","&#039;");
}}

function selected(){{
  return state.messages.find(
    item=>item.id===state.selected
  );
}}

function moveSelected(folder,label){{
  const item=selected();

  if(!item){{
    toast('Select a message first');
    return;
  }}

  item.folder=folder;
  state.selected=null;
  save();
  render();
  toast(label);
}}

function openCompose(){{
  document.querySelector(
    '#composeModal'
  ).classList.add('open');
}}

function closeCompose(){{
  document.querySelector(
    '#composeModal'
  ).classList.remove('open');
}}

function clearCompose(){{
  for(const id of [
    '#composeTo',
    '#composeSubject',
    '#composeBody'
  ]){{
    document.querySelector(id).value='';
  }}
}}

function composePayload(folder){{
  const to=document.querySelector(
    '#composeTo'
  ).value.trim();

  const subject=document.querySelector(
    '#composeSubject'
  ).value.trim();

  const body=document.querySelector(
    '#composeBody'
  ).value.trim();

  return {{
    id:Date.now(),
    folder,
    sender:folder==='drafts'?'Draft':'Me',
    email:to||'unspecified recipient',
    subject:subject||'(no subject)',
    body,
    time:folder==='drafts'?'Draft':'Now',
    unread:false,
    starred:false,
    labels:[
      folder==='drafts'
        ? 'Draft'
        : 'Sent'
    ]
  }};
}}

function send(){{
  const message=composePayload('sent');

  state.messages.unshift(message);
  save();
  clearCompose();
  closeCompose();
  renderFolders();
  toast('Message added to Sent');
}}

function saveDraft(){{
  const message=composePayload('drafts');

  state.messages.unshift(message);
  save();
  clearCompose();
  closeCompose();
  renderFolders();
  toast('Draft saved');
}}

function render(){{
  document.body.classList.toggle(
    'dark',
    !!state.dark
  );

  renderFolders();
  renderList();
  renderReader();
}}

document.querySelector(
  '#composeButton'
).onclick=openCompose;

document.querySelector(
  '#closeCompose'
).onclick=closeCompose;

document.querySelector(
  '#composeModal'
).addEventListener(
  'click',
  event=>{{
    if(
      event.target.id==='composeModal'
    ){{
      closeCompose();
    }}
  }}
);

document.querySelector(
  '#sendButton'
).onclick=send;

document.querySelector(
  '#saveDraftButton'
).onclick=saveDraft;

document.querySelector(
  '#search'
).addEventListener(
  'input',
  event=>{{
    query=event.target.value.trim();
    renderList();
  }}
);

document.querySelector(
  '#themeButton'
).onclick=()=>{{
  state.dark=!state.dark;
  save();
  render();
}};

document.querySelector(
  '#settingsButton'
).onclick=()=>{{
  document.querySelector(
    '#settingsPanel'
  ).classList.add('open');
}};

document.querySelector(
  '#closeSettings'
).onclick=()=>{{
  document.querySelector(
    '#settingsPanel'
  ).classList.remove('open');
}};

document.querySelector(
  '#refreshButton'
).onclick=()=>{{
  render();
  toast('Mailbox refreshed');
}};

document.querySelector(
  '#markReadButton'
).onclick=()=>{{
  const item=selected();

  if(!item){{
    toast('Select a message first');
    return;
  }}

  item.unread=false;
  save();
  render();
  toast('Marked as read');
}};

document.querySelector(
  '#archiveButton'
).onclick=()=>moveSelected(
  'archive',
  'Archived'
);

document.querySelector(
  '#spamButton'
).onclick=()=>moveSelected(
  'spam',
  'Moved to spam'
);

document.querySelector(
  '#deleteButton'
).onclick=()=>moveSelected(
  'trash',
  'Moved to trash'
);

document.querySelector(
  '#densitySelect'
).value=
  document.documentElement.dataset.designDensity;

document.querySelector(
  '#densitySelect'
).addEventListener(
  'change',
  event=>{{
    document.documentElement.dataset.designDensity=
      event.target.value;

    toast(
      'Density set to '+event.target.value
    );
  }}
);

addEventListener(
  'keydown',
  event=>{{
    if(
      event.key==='Escape'
    ){{
      closeCompose();

      document.querySelector(
        '#settingsPanel'
      ).classList.remove('open');
    }}

    if(
      event.key.toLowerCase()==='c'
      && !event.ctrlKey
      && !event.metaKey
      && !event.target.matches(
        'input,textarea,select'
      )
    ){{
      openCompose();
    }}
  }}
);

render();
</script>

</body>
</html>"""


def validate_product_document(
    request: str,
    document: str,
) -> list[str]:
    """Fail closed on missing product behavior."""
    low = str(
        document
        or ""
    ).casefold()

    title_match = re.search(
        r"<title[^>]*>(.*?)</title>",
        document,
        flags=re.I | re.S,
    )

    title_text = (
        title_match.group(1).casefold()
        if title_match
        else ""
    )

    title_claim_safe = not any(
        phrase in title_text
        for phrase in (
            "gmail",
            "all features",
            "all services",
            "as good as",
            "fully featured",
            "full-featured",
            "smtp",
            "imap",
        )
    )

    checks = {
        "complete_html":
            (
                "<html" in low
                and "<body" in low
                and "</html>" in low
            ),

        "substantial":
            (
                len(
                    document.encode(
                        "utf-8"
                    )
                )
                >= 12_000
            ),

        "javascript":
            "<script" in low,

        "search":
            (
                'id="search"'
                in low
                and "currentmessages"
                in low
            ),

        "compose":
            (
                "composemodal"
                in low
                and "sendbutton"
                in low
                and "savedraftbutton"
                in low
            ),

        "folders":
            all(
                token in low
                for token in (
                    "inbox",
                    "starred",
                    "sent",
                    "drafts",
                    "archive",
                    "spam",
                    "trash",
                )
            ),

        "message_reading":
            "renderreader" in low,

        "reply":
            "replybutton" in low,

        "forward":
            "forwardbutton" in low,

        "star":
            "data-star" in low,

        "archive_action":
            "archivebutton" in low,

        "spam_action":
            "spambutton" in low,

        "delete_action":
            "deletebutton" in low,

        "persistence":
            "localstorage" in low,

        "responsive":
            "@media(max-width:650px)" in low,

        "reduced_motion":
            "prefers-reduced-motion" in low,

        "scope_truth":
            (
                "smtp/imap"
                in low
                or "smtp"
                in low
            ),

        "mobile_message_reader":
            all(
                token in low
                for token in (
                    "mobile-open",
                    "mobile-hidden",
                    "backtolistbutton",
                    'id="listpane"',
                )
            ),

        "compact_compose":
            (
                ".compose-btn span"
                in low
                and "display:none"
                in low
            ),

        "title_claim_safe":
            title_claim_safe,
    }

    if _email_request(
        request
    ):
        checks[
            "email_product_family"
        ] = (
            'data-product-family="email-workspace"'
            in low
        )

    return [
        name
        for name, passed in checks.items()
        if not passed
    ]


def _browser_validate(
    workspace: Path,
    progress: Progress,
) -> tuple[bool, str]:
    try:
        from sophyane.browser_runtime_v2 import (
            open_verified_browser,
        )

        opened, evidence = open_verified_browser(
            workspace,
            progress,
        )

        return (
            bool(opened),
            str(
                evidence
                or ""
            ),
        )

    except Exception as error:
        return (
            False,
            (
                f"{type(error).__name__}: "
                f"{error}"
            ),
        )


def compose_product_app(
    request: str,
    workspace: Path | str,
    *,
    progress: Progress | None = None,
    acquisition_report: str = "",
) -> str:
    progress = progress or (
        lambda _message: None
    )

    root = Path(
        workspace
    ).resolve()

    root.mkdir(
        parents=True,
        exist_ok=True,
    )

    if not is_product_app_request(
        request
    ):
        return (
            "Sophyane product-app synthesis\n"
            "Handled: False\n"
            "Success: False"
        )

    if not _email_request(
        request
    ):
        return (
            "Sophyane product-app synthesis\n"
            "Handled: False\n"
            "Reason: no bounded deterministic product family "
            "exists yet for this application request.\n"
            "Success: False"
        )

    progress(
        "SLI product recovery: strict reusable acquisition "
        "did not produce a valid artifact"
    )

    progress(
        "SLI product recovery: synthesizing bounded "
        "email-workspace product"
    )

    design = _local_design(
        request,
        progress,
    )

    document = _email_document(
        request,
        design,
    )

    failures = validate_product_document(
        request,
        document,
    )

    if failures:
        return (
            "Sophyane product-app synthesis\n"
            "Product family: email-workspace\n"
            "Structural validation: failed\n"
            "Failed checks: "
            + ", ".join(
                failures
            )
            + "\nSuccess: False"
        )

    output = root / "index.html"

    temporary = root / ".index.html.tmp"

    temporary.write_text(
        document,
        encoding="utf-8",
    )

    temporary.replace(
        output
    )

    progress(
        "SLI product recovery: deterministic product "
        "behavior validation PASS"
    )

    opened, evidence = _browser_validate(
        root,
        progress,
    )

    if not opened:
        output.unlink(
            missing_ok=True
        )

        return (
            "Sophyane product-app synthesis\n"
            "Product family: email-workspace\n"
            "Structural validation: passed\n"
            "Rendered validation: failed\n"
            f"Evidence: {evidence}\n"
            "Success: False"
        )

    rendered_ok = (
        "Rendered evidence: PASS"
        in evidence
    )

    hash_ok = (
        "HTTP verification: SHA-256 matched"
        in evidence
    )

    if not (
        rendered_ok
        and hash_ok
    ):
        output.unlink(
            missing_ok=True
        )

        return (
            "Sophyane product-app synthesis\n"
            "Product family: email-workspace\n"
            "Structural validation: passed\n"
            "Rendered validation: failed closed\n"
            f"Evidence: {evidence}\n"
            "Success: False"
        )

    source_status = (
        "strict acquisition rejected or unavailable"
        if acquisition_report
        else "no accepted reusable artifact"
    )

    return "\n".join(
        [
            "Sophyane product-app synthesis",
            f"Request: {request}",
            "Product family: email-workspace",
            (
                "Product scope: functional browser email "
                "workspace prototype"
            ),
            (
                "Production transport: SMTP/IMAP/backend "
                "services not falsely claimed"
            ),
            (
                "Recovery source: "
                + source_status
            ),
            (
                "Design generated: "
                + str(
                    design.generated
                )
            ),
            (
                "LLM used: "
                + (
                    "local-product-design"
                    if design.generated
                    else "False"
                )
            ),
            (
                "Design concept: "
                + design.concept
            ),
            "Deterministic behavior validation: passed",
            "Files: index.html",
            (
                "Bytes: "
                + str(
                    output.stat().st_size
                )
            ),
            evidence,
            "Success: True",
        ]
    )
