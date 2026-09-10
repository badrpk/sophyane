#!/usr/bin/env python3
from __future__ import annotations

import json
import os
from pathlib import Path
import sys
import time
import urllib.request

import websocket


HOST = os.environ.get(
    "SOPHYANE_CDP_HOST",
    "127.0.0.1",
)

PORT = int(
    os.environ.get(
        "SOPHYANE_CDP_PORT",
        "9222",
    )
)

TIMEOUT = int(
    os.environ.get(
        "SOPHYANE_CHATGPT_TIMEOUT",
        "300",
    )
)

# SOPHYANE_CDP_ABSOLUTE_CALL_DEADLINE_V1
#
# Generation latency and DevTools transport latency are different
# authorities. A single CDP command must never inherit the full model
# generation allowance, and unrelated DevTools events must never reset
# its operation deadline.
CDP_CONNECT_TIMEOUT = float(
    os.environ.get(
        "SOPHYANE_CDP_CONNECT_TIMEOUT",
        "5",
    )
)

CDP_CALL_TIMEOUT = float(
    os.environ.get(
        "SOPHYANE_CDP_CALL_TIMEOUT",
        "10",
    )
)

CDP_READINESS_TIMEOUT = float(
    os.environ.get(
        "SOPHYANE_CDP_READINESS_TIMEOUT",
        "5",
    )
)


def bounded_cdp_timeout(
    configured,
):
    configured = max(
        0.1,
        float(configured),
    )

    bridge_timeout = max(
        0.1,
        float(TIMEOUT),
    )

    return min(
        configured,
        bridge_timeout,
    )


def endpoint(path: str) -> str:
    return f"http://{HOST}:{PORT}{path}"


def load_json(path: str):
    with urllib.request.urlopen(
        endpoint(path),
        timeout=5,
    ) as response:
        return json.loads(
            response.read().decode(
                "utf-8"
            )
        )


def pages():
    return [
        item
        for item in load_json("/json")
        if item.get("type") == "page"
    ]


def chat_page():
    # SOPHYANE_CDP_READINESS_AWARE_CHAT_PAGE_SELECTION_V1
    #
    # Prefer an existing ChatGPT target that is currently capable of
    # generation. A newer Work/project tab may be quota exhausted while
    # another ordinary ChatGPT tab remains usable.
    #
    # If no target can be proven interactive, preserve historical
    # matches[-1] fallback behavior so wait_prompt() remains responsible
    # for the final quota/challenge/signed-out diagnostic.
    matches = [
        page
        for page in pages()
        if "chatgpt.com"
        in str(
            page.get("url", "")
        ).lower()
    ]

    if not matches:
        raise RuntimeError(
            "No ChatGPT Chromium tab found on "
            f"CDP {HOST}:{PORT}. "
            "Open ChatGPT in the NIFDU Chromium "
            "instance exposing this DevTools port."
        )

    # SOPHYANE_CDP_BOUNDED_READINESS_SELECTION_V1
    # SOPHYANE_CDP_FAIL_CLOSED_TARGET_SELECTION_V1
    #
    # Target discovery is only a readiness probe. It must not consume one
    # complete socket timeout per stale ChatGPT tab.
    #
    # A responsive-but-semantically-unusable page is still a valid fallback
    # because wait_prompt() can report quota, challenge, or signed-out state.
    # A target whose CDP transport/protocol probe fails must never be returned
    # as though readiness selection had succeeded.
    selection_deadline = (
        time.monotonic()
        + bounded_cdp_timeout(
            CDP_READINESS_TIMEOUT
        )
    )

    semantic_fallback = None
    transport_failures = []

    # SOPHYANE_CDP_FAIR_TARGET_PROBE_BUDGET_V1
    #
    # A single stale renderer must not consume the complete global
    # readiness-selection window and prevent later candidates from
    # being probed. Divide the remaining readiness time across the
    # remaining candidates and apply that share to each candidate's
    # CDP command deadline.
    candidates = list(
        reversed(matches)
    )

    for index, page in enumerate(
        candidates
    ):
        now = time.monotonic()

        if now >= selection_deadline:
            break

        remaining_selection = (
            selection_deadline
            - now
        )

        candidates_left = (
            len(candidates)
            - index
        )

        candidate_budget = max(
            0.1,
            remaining_selection
            / candidates_left,
        )

        cdp = None

        try:
            cdp = CDP(page)

            if hasattr(
                cdp,
                "call_timeout",
            ):
                cdp.call_timeout = min(
                    float(
                        cdp.call_timeout
                    ),
                    candidate_budget,
                )

            readiness = chatgpt_readiness(
                cdp
            )

            # Reaching this point proves that this target answered the
            # readiness CDP operation. Preserve the first responsive target
            # encountered in reversed(matches), which keeps historical
            # matches[-1] preference when that target is healthy.
            if semantic_fallback is None:
                semantic_fallback = page

            if readiness.get(
                "interactive"
            ):
                return page

        except Exception as exc:
            # A stale/closing/unresponsive DevTools target must not prevent
            # another ChatGPT target from being considered, but it must also
            # never become the semantic fallback.
            transport_failures.append(
                (
                    str(
                        page.get(
                            "id",
                            "",
                        )
                    ),
                    exc,
                )
            )
            continue

        finally:
            if cdp is not None:
                cdp.close()

    if semantic_fallback is not None:
        return semantic_fallback

    if transport_failures:
        target_id, last_error = (
            transport_failures[-1]
        )

        raise RuntimeError(
            "No responsive ChatGPT CDP target "
            "was found during readiness selection. "
            f"Last target={target_id!r}; "
            "last transport error="
            f"{type(last_error).__name__}: "
            f"{last_error}"
        ) from last_error

    raise RuntimeError(
        "No responsive ChatGPT CDP target "
        "was found before the bounded "
        "readiness-selection deadline."
    )


class CDP:
    def __init__(self, page):
        self.call_timeout = (
            CDP_CALL_TIMEOUT
        )

        self.socket = websocket.create_connection(
            page["webSocketDebuggerUrl"],
            timeout=bounded_cdp_timeout(
                CDP_CONNECT_TIMEOUT
            ),
            origin=f"http://{HOST}:{PORT}",
        )

        self.ident = 0

    def close(self):
        try:
            self.socket.close()
        except Exception:
            pass

    def call(
        self,
        method,
        params=None,
    ):
        self.ident += 1
        ident = self.ident

        operation_timeout = (
            bounded_cdp_timeout(
                self.call_timeout
            )
        )

        deadline = (
            time.monotonic()
            + operation_timeout
        )

        payload = json.dumps(
            {
                "id": ident,
                "method": method,
                "params": params or {},
            }
        )

        try:
            self.socket.settimeout(
                operation_timeout
            )

            self.socket.send(
                payload
            )

        except websocket.WebSocketTimeoutException as exc:
            raise TimeoutError(
                f"CDP {method} timed out "
                "while sending the command."
            ) from exc

        while True:
            remaining = (
                deadline
                - time.monotonic()
            )

            if remaining <= 0:
                raise TimeoutError(
                    f"CDP {method} timed out "
                    f"after {operation_timeout:.3f}s."
                )

            try:
                self.socket.settimeout(
                    max(
                        0.05,
                        remaining,
                    )
                )

                raw_message = (
                    self.socket.recv()
                )

            except websocket.WebSocketTimeoutException as exc:
                raise TimeoutError(
                    f"CDP {method} timed out "
                    f"after {operation_timeout:.3f}s."
                ) from exc

            message = json.loads(
                raw_message
            )

            if message.get("id") != ident:
                continue

            if "error" in message:
                raise RuntimeError(
                    message["error"]
                )

            return message.get(
                "result",
                {},
            )

    def evaluate(self, expression):
        result = self.call(
            "Runtime.evaluate",
            {
                "expression": expression,
                "returnByValue": True,
                "awaitPromise": True,
            },
        )

        return (
            result.get("result", {})
            .get("value")
        )


def assistant_state(cdp):
    # SOPHYANE_CDP_CURRENT_CHATGPT_MESSAGE_DOM_V1
    #
    # Preserve the historical data-message-author-role contract, while
    # supporting the current ChatGPT mobile/web shell where conversation
    # turns are rendered as:
    #
    #   ol[aria-label="Conversation"]
    #   li._wdUoQG_messageTurn
    #   ._wdUoQG_userMessageGroup
    #   ._wdUoQG_assistantMessage
    #
    # Do not depend on the generated class prefix alone. Prefer semantic
    # containment plus role-specific descendants, with historical selectors
    # remaining authoritative when present.
    return (
        cdp.evaluate(
            r"""
(() => {
  const legacyAssistants = [
    ...document.querySelectorAll(
      '[data-message-author-role="assistant"]'
    )
  ];

  const legacyUsers = [
    ...document.querySelectorAll(
      '[data-message-author-role="user"]'
    )
  ];

  const conversation =
    document.querySelector(
      'ol[aria-label="Conversation"]'
    )
    || document.querySelector(
      '[role="region"][aria-label="Conversation"]'
    );

  const turns = conversation
    ? [
        ...conversation.querySelectorAll('li')
      ]
    : [];

  const currentAssistants = turns
    .map(
      turn =>
        turn.querySelector(
          'div[class*="assistantMessage"]'
        )
    )
    .filter(Boolean);

  const currentUsers = turns
    .map(
      turn =>
        turn.querySelector(
          'div[class*="userMessageGroup"]'
        )
        || turn.querySelector(
          'button[class*="userMessage"]'
        )
    )
    .filter(Boolean);

  const assistants =
    legacyAssistants.length
      ? legacyAssistants
      : currentAssistants;

  const users =
    legacyUsers.length
      ? legacyUsers
      : currentUsers;

  const last =
    assistants.length
      ? assistants[assistants.length - 1]
      : null;

  const stop =
    document.querySelector(
      '[data-testid="stop-button"]'
    )
    || [
      ...document.querySelectorAll('button')
    ].find(button => {
      const label = (
        button.getAttribute('aria-label')
        || button.innerText
        || ''
      ).trim();

      return /^stop\b/i.test(label);
    });

  return {
    count: assistants.length,
    user_count: users.length,
    text: last
      ? (
          last.innerText
          || last.textContent
          || ''
        )
      : '',
    streaming: Boolean(stop),
  };
})()
"""
        )
        or {
            "count": 0,
            "user_count": 0,
            "text": "",
            "streaming": False,
        }
    )



# SOPHYANE_CDP_FRESH_USAGE_LIMIT_RESPONSE_V1
def chatgpt_usage_limit_response(text):
    """Return True for an explicit ChatGPT generation quota response.

    This classifier is intentionally applied only to a response proven fresh
    relative to the pre-send assistant state. Historical conversation text
    mentioning limits must not make an otherwise usable page unavailable.
    """
    value = " ".join(
        str(
            text
            or ""
        ).lower().split()
    )

    if not value:
        return False

    explicit = (
        "you've hit your usage limit",
        "you have hit your usage limit",
        "usage limit reached",
        "you've reached your usage limit",
        "you have reached your usage limit",
    )

    return any(
        phrase in value
        for phrase in explicit
    )


# SOPHYANE_CDP_CHATGPT_INTERACTIVE_READINESS_V1
def chatgpt_readiness(cdp):
    """Return semantic ChatGPT readiness without mutating the page.

    Chromium/CDP transport readiness is intentionally separate.
    NIFDU is usable only when the ChatGPT page exposes an interactive
    prompt surface and is not displaying a browser-verification challenge.
    """

    value = (
        cdp.evaluate(
            r"""
(() => {
  const bodyText =
    document.body?.innerText || '';

  const title =
    document.title || '';

  const promptTextarea =
    !!document.querySelector(
      '#prompt-textarea'
    );

  const textarea =
    !!document.querySelector(
      'textarea'
    );

  const editable =
    !!document.querySelector(
      '[contenteditable="true"]'
    );

  // SOPHYANE_CDP_CHATGPT_USAGE_LIMIT_STATE_V1
  // SOPHYANE_CDP_CHATGPT_ACTIVE_USAGE_LIMIT_V2
  //
  // IMPORTANT:
  // Do not infer CURRENT quota state from document.body.innerText.
  // Conversation history may legitimately contain an old assistant/user
  // message such as "you've hit your usage limit; try again at 6:39 PM".
  //
  // Only a visible active ChatGPT UI notice OUTSIDE conversation-history
  // message containers is allowed to block generation.
  const usageLimitPattern =
    /you.?ve hit your usage limit|usage limit|upgrade your plan|add credits|try again at/i;

  const historySelectors = [
    'article',
    '[data-message-author-role]',
    '[data-testid^="conversation-turn"]',
    '[data-testid*="conversation-turn"]'
  ].join(',');

  const isVisible = (el) => {
    if (!el) {
      return false;
    }

    const style = getComputedStyle(el);
    const rect = el.getBoundingClientRect();

    return (
      style.display !== 'none'
      && style.visibility !== 'hidden'
      && Number.parseFloat(
        style.opacity || '1'
      ) > 0
      && rect.width > 0
      && rect.height > 0
    );
  };

  // SOPHYANE_CDP_CHATGPT_ACTIVE_WORK_USAGE_LIMIT_V1
  //
  // Current ChatGPT Work exhaustion is rendered as a composer-adjacent
  // shell such as:
  //
  //   "You’re out of Work usage for now"
  //
  // It is not necessarily an alert/status/aria-live node and therefore
  // can evade the generic quota-candidate classifier below. Detect that
  // exact active shell independently, while still excluding historical
  // conversation turns.
  const workUsageLimitPattern =
    /you(?:'|’)?re out of work usage for now|out of work usage for now/i;

  const activeWorkUsageNodes =
    Array.from(
      document.querySelectorAll('body *')
    ).filter((el) => {
      const text =
        (el.innerText || '').trim();

      if (
        !text
        || text.length > 1000
        || !workUsageLimitPattern.test(text)
        || !isVisible(el)
      ) {
        return false;
      }

      if (
        typeof el.closest === 'function'
        && el.closest(historySelectors)
      ) {
        return false;
      }

      return true;
    });

  const activeWorkUsageNotice =
    activeWorkUsageNodes.length > 0;

  const activeWorkUsageText =
    activeWorkUsageNotice
      ? (
          activeWorkUsageNodes
            .map(
              el => (el.innerText || '').trim()
            )
            .sort(
              (a, b) => a.length - b.length
            )[0]
          || ''
        )
      : '';

  const quotaCandidates = [];

  for (
    const el
    of Array.from(
      document.querySelectorAll('body *')
    )
  ) {
    const text =
      (el.innerText || '').trim();

    if (
      !text
      || text.length > 1000
      || !usageLimitPattern.test(text)
    ) {
      continue;
    }

    if (!isVisible(el)) {
      continue;
    }

    //
    // Historical chat content is evidence about a PREVIOUS response,
    // never evidence of the CURRENT account/composer state.
    //
    if (
      typeof el.closest === 'function'
      && el.closest(historySelectors)
    ) {
      continue;
    }

    //
    // Prefer the smallest matching node rather than a parent container
    // whose innerText merely includes text from a matching descendant.
    //
    const matchingChild =
      Array.from(
        el.children || []
      ).some((child) => {
        const childText =
          (child.innerText || '').trim();

        return (
          childText
          && childText.length <= 1000
          && usageLimitPattern.test(
            childText
          )
        );
      });

    if (matchingChild) {
      continue;
    }

    const host =
      (
        typeof el.closest === 'function'
        && el.closest(
          [
            '[role="alert"]',
            '[role="status"]',
            '[role="dialog"]',
            '[aria-live="assertive"]',
            '[aria-live="polite"]'
          ].join(',')
        )
      )
      || el;

    if (!isVisible(host)) {
      continue;
    }

    const hostStyle =
      getComputedStyle(host);

    const role =
      (
        host.getAttribute('role')
        || ''
      ).toLowerCase();

    const ariaLive =
      (
        host.getAttribute('aria-live')
        || ''
      ).toLowerCase();

    const activeSemantics =
      role === 'alert'
      || role === 'status'
      || role === 'dialog'
      || ariaLive === 'assertive'
      || ariaLive === 'polite'
      || hostStyle.position === 'fixed'
      || hostStyle.position === 'sticky';

    //
    // A plain visible node outside conversation history may still be an
    // active quota shell. Keep it only when it is associated with the
    // composer region rather than arbitrary page copy.
    //
    const promptEl =
      document.querySelector(
        '#prompt-textarea, textarea, [contenteditable="true"]'
      );

    let composerAssociated = false;

    if (
      promptEl
      && isVisible(promptEl)
    ) {
      const promptRect =
        promptEl.getBoundingClientRect();

      const hostRect =
        host.getBoundingClientRect();

      composerAssociated =
        (
          hostRect.bottom
          >= promptRect.top - 420
          && hostRect.top
          <= promptRect.bottom + 220
        );
    }

    if (
      !activeSemantics
      && !composerAssociated
    ) {
      continue;
    }

    quotaCandidates.push({
      text,
      role,
      ariaLive
    });
  }

  const activeUsageLimit =
    (
      quotaCandidates.length > 0
      || activeWorkUsageNotice
    );

  const activeUsageLimitText =
    quotaCandidates.length > 0
      ? quotaCandidates[0].text
      : activeWorkUsageText;

  const tryAgainMatch =
    activeUsageLimitText.match(
      /try again at [^.\n]+/i
    );

  const workResetMatch =
    activeWorkUsageNotice
      ? bodyText.match(
          /(?:wait for your usage to reset at|usage to reset at)\s+[^.\n]+/i
        )
      : null;

  const tryAgainText =
    tryAgainMatch
      ? tryAgainMatch[0]
      : (
          workResetMatch
            ? workResetMatch[0]
            : ''
        );

  const usageLimited =
    activeUsageLimit;

  const challengeTitle =
    /just a moment/i.test(
      title
    );

  const challengeBody =
    /checking your browser|verify you are human|just a moment/i.test(
      bodyText
    );

  const cloudflareFrame =
    [
      ...document.querySelectorAll(
        'iframe'
      )
    ].some(frame => {
      const src =
        frame.getAttribute('src') || '';

      return /challenges\.cloudflare\.com/i.test(
        src
      );
    });

  // SOPHYANE_CDP_CHATGPT_SIGNED_OUT_STATE_V1
  //
  // Detect an explicit ChatGPT authentication surface only when there is
  // no usable composer. This is observational only: NIFDU never automates
  // login, copies cookies, or attempts to bypass browser verification.
  const authControls =
    [
      ...document.querySelectorAll(
        'a, button'
      )
    ];

  const loginControl =
    authControls.some(node => {
      const text = (
        node.innerText
        || node.textContent
        || node.getAttribute('aria-label')
        || ''
      ).trim();

      const href = (
        node.getAttribute('href')
        || ''
      );

      return (
        /^(log\s*in|sign\s*in)$/i.test(text)
        || /\/auth\/login(?:[/?#]|$)/i.test(href)
      );
    });

  const composer =
    promptTextarea
    || textarea
    || editable;

  const challenged =
    challengeTitle
    || challengeBody
    || cloudflareFrame;

  const signedOut =
    !composer
    && !challenged
    && loginControl;

  return {
    href: location.href,
    title,
    readyState: document.readyState,
    bodyChars: bodyText.length,
    promptTextarea,
    textarea,
    editable,
    challengeTitle,
    challengeBody,
    cloudflareFrame,
    challenged,
    loginControl,
    signedOut,
    usageLimited,
    activeUsageLimit,
    activeUsageLimitText,
    activeWorkUsageNotice,
    activeWorkUsageText,
    quotaCandidateCount:
      quotaCandidates.length,
    tryAgainText,
    composer,
    interactive:
      composer
      && !challenged
      && !signedOut
      && !usageLimited
  };
})()
"""
        )
        or {}
    )

    if not isinstance(
        value,
        dict,
    ):
        return {
            "interactive": False,
            "challenged": False,
            "composer": False,
            "reason": (
                "invalid_readiness_payload"
            ),
        }

    result = dict(value)

    if result.get(
        "challenged"
    ):
        reason = (
            "browser_verification_challenge"
        )

    elif result.get(
        "signedOut"
    ):
        reason = (
            "chatgpt_signed_out"
        )

    elif result.get(
        "usageLimited"
    ):
        reason = (
            "chatgpt_usage_limit"
        )

    elif not result.get(
        "composer"
    ):
        reason = (
            "prompt_composer_not_detected"
        )

    elif not result.get(
        "interactive"
    ):
        reason = (
            "chatgpt_not_interactive"
        )

    else:
        reason = "ready"

    result[
        "reason"
    ] = reason

    return result


def wait_prompt(cdp):
    # SOPHYANE_CDP_CHATGPT_INTERACTIVE_WAIT_V1
    #
    # CDP connectivity alone does not prove that ChatGPT is usable.
    # A Cloudflare/browser-verification page may expose a healthy DevTools
    # endpoint while providing no prompt surface.
    #
    # Keep this bounded and observational. Do not attempt to solve or bypass
    # verification challenges.
    deadline = (
        time.monotonic()
        + 90
    )

    last = {}

    while time.monotonic() < deadline:
        last = chatgpt_readiness(
            cdp
        )

        if last.get(
            "interactive"
        ):
            return

        if last.get(
            "challenged"
        ):
            raise RuntimeError(
                "ChatGPT is blocked by a browser verification challenge; "
                "NIFDU CDP transport is ready but ChatGPT is not interactive."
            )

        if last.get(
            "signedOut"
        ):
            raise RuntimeError(
                "ChatGPT is signed out in the persistent NIFDU Chromium "
                "profile; sign in manually in that browser profile and "
                "retry. NIFDU CDP transport is ready."
            )

        # SOPHYANE_CDP_CHATGPT_USAGE_LIMIT_FAIL_FAST_V1
        #
        # Do not populate a prompt, poll the assistant DOM, or burn the
        # full bridge timeout when ChatGPT has explicitly disabled new
        # generation for the current account/session.
        if last.get(
            "usageLimited"
        ):
            retry = str(
                last.get(
                    "tryAgainText",
                    "",
                )
                or ""
            ).strip()

            detail = (
                "; "
                + retry
                if retry
                else ""
            )

            raise RuntimeError(
                "ChatGPT usage limit reached; NIFDU CDP transport is "
                "ready but the selected ChatGPT session cannot generate "
                "a new response"
                + detail
                + "."
            )

        time.sleep(
            1
        )

    reason = str(
        last.get(
            "reason",
            "prompt_composer_not_detected",
        )
    )

    raise RuntimeError(
        "ChatGPT prompt box was not detected before timeout; "
        "semantic readiness reason="
        + reason
    )

def attach_file(cdp, filename):
    path = Path(filename).expanduser().resolve()

    if not path.is_file():
        return False

    cdp.call(
        "DOM.enable"
    )

    document = cdp.call(
        "DOM.getDocument",
        {
            "depth": 2,
            "pierce": True,
        },
    )

    root_id = (
        document["root"]["nodeId"]
    )

    found = cdp.call(
        "DOM.querySelector",
        {
            "nodeId": root_id,
            "selector": 'input[type="file"]',
        },
    )

    node_id = int(
        found.get(
            "nodeId",
            0,
        )
        or 0
    )

    if not node_id:
        return False

    cdp.call(
        "DOM.setFileInputFiles",
        {
            "nodeId": node_id,
            "files": [str(path)],
        },
    )

    time.sleep(1)

    return True


def populate_prompt(cdp, text):
    payload = json.dumps(text)

    result = cdp.evaluate(
        f"""
(() => {{
  const value = {payload};

  const e =
    document.querySelector('#prompt-textarea') ||
    document.querySelector('textarea') ||
    document.querySelector('[contenteditable="true"]');

  if (!e) {{
    return false;
  }}

  e.focus();

  if (
    e.tagName === 'TEXTAREA' ||
    e.tagName === 'INPUT'
  ) {{
    const proto =
      e.tagName === 'TEXTAREA'
        ? HTMLTextAreaElement.prototype
        : HTMLInputElement.prototype;

    const setter =
      Object.getOwnPropertyDescriptor(
        proto,
        'value'
      ).set;

    setter.call(e, value);

    e.dispatchEvent(
      new Event(
        'input',
        {{bubbles: true}}
      )
    );
  }}
  else {{
      // SOPHYANE_CDP_LIGHTWEIGHT_CONTENTEDITABLE_PROMPT_V1
      //
      // Insert the complete value directly into the editable DOM instead
      // of routing the whole prompt through synchronous execCommand.
      e.replaceChildren(
        document.createTextNode(value)
      );

      const selection =
        window.getSelection();

      if (selection) {{
        const range =
          document.createRange();

        range.selectNodeContents(e);
        range.collapse(false);

        selection.removeAllRanges();
        selection.addRange(range);
      }}

e.dispatchEvent(
      new InputEvent(
        'input',
        {{
          bubbles: true,
          inputType: 'insertText',
          data: null
        }}
      )
    );
  }}

  return true;
}})()
"""
    )

    if not result:
        raise RuntimeError(
            "Unable to populate ChatGPT prompt."
        )



def prepare_for_new_generation(
    cdp,
    *,
    timeout=20.0,
    interval=0.25,
):
    """Settle a stale ChatGPT generation before submitting a new prompt.

    A bridge response timeout does not imply that the browser-side ChatGPT
    generation stopped. The next same-provider protocol-repair request may
    therefore inherit an active Stop control and no usable Send control.

    Recovery is intentionally bounded:

    1. observe whether a generation is still active;
    2. if active, click ChatGPT's ordinary Stop control once;
    3. wait until the generation control disappears;
    4. only then allow the caller to establish its new response baseline.

    This never bypasses authentication or browser verification and never
    switches providers.
    """

    deadline = (
        time.monotonic()
        + max(
            1.0,
            float(timeout),
        )
    )

    stop_requested = False

    state_expression = r"""
(() => {
  const direct =
    document.querySelector(
      '[data-testid="stop-button"]'
    );

  const fallback =
    [...document.querySelectorAll('button')]
    .find(button => {
      const label =
        (
          button.getAttribute('aria-label')
          || ''
        ).trim();

      return (
        /^stop generating$/i.test(label)
        || /^stop response$/i.test(label)
        || /^stop$/i.test(label)
      );
    });

  const button =
    direct || fallback || null;

  const visible =
    !!button
    && (() => {
      const rect =
        button.getBoundingClientRect();

      const style =
        getComputedStyle(button);

      return (
        rect.width > 0
        && rect.height > 0
        && style.display !== 'none'
        && style.visibility !== 'hidden'
      );
    })();

  return {
    generating: !!visible,
    stopPresent: !!button
  };
})()
"""

    stop_expression = r"""
(() => {
  const direct =
    document.querySelector(
      '[data-testid="stop-button"]'
    );

  const fallback =
    [...document.querySelectorAll('button')]
    .find(button => {
      const label =
        (
          button.getAttribute('aria-label')
          || ''
        ).trim();

      return (
        /^stop generating$/i.test(label)
        || /^stop response$/i.test(label)
        || /^stop$/i.test(label)
      );
    });

  const button =
    direct || fallback || null;

  if (!button)
    return false;

  button.click();
  return true;
})()
"""

    while time.monotonic() < deadline:
        state = (
            cdp.evaluate(
                state_expression
            )
            or {}
        )

        generating = bool(
            state.get(
                "generating"
            )
        )

        if not generating:
            return

        if not stop_requested:
            stopped = bool(
                cdp.evaluate(
                    stop_expression
                )
            )

            if stopped:
                stop_requested = True

        time.sleep(
            max(
                0.05,
                float(interval),
            )
        )

    raise RuntimeError(
        "ChatGPT prior generation did not settle "
        "before the next NIFDU prompt."
    )


def cleanup_failed_generation(
    cdp,
    *,
    generation_submitted,
    timeout=20.0,
):
    """Best-effort cleanup after a submitted NIFDU request fails.

    Once ChatGPT has accepted a prompt, a Python-side timeout or transport
    exception does not guarantee that browser-side generation stopped.

    Clean that generation before returning control to the caller so an
    immediate same-provider retry does not inherit a stale Stop state.

    Cleanup is deliberately best-effort. The original provider exception
    remains authoritative; any cleanup exception is returned to the caller
    for diagnostic annotation rather than replacing the primary failure.
    """

    if not generation_submitted:
        return None

    try:
        prepare_for_new_generation(
            cdp,
            timeout=timeout,
        )
    except Exception as exc:
        return exc

    return None


def click_send(cdp):
    deadline = time.monotonic() + 15

    while time.monotonic() < deadline:
        result = cdp.evaluate(
            r"""
(() => {
  const direct =
    document.querySelector(
      '[data-testid="send-button"]'
    );

  const fallback =
    [...document.querySelectorAll('button')]
    .find(button => {
      const label =
        button.getAttribute('aria-label') || '';

      return /^send/i.test(label);
    });

  const button = direct || fallback;

  if (!button || button.disabled)
    return false;

  button.click();
  return true;
})()
"""
        )

        if result:
            return

        time.sleep(0.25)

    raise RuntimeError(
        "ChatGPT send button was not usable."
    )



# SOPHYANE_CDP_STRUCTURED_RESPONSE_COMPLETENESS_V1
def structured_response_semantically_complete(text):
    """Reject obviously unfinished structured NIFDU responses.

    Generic DOM stability is insufficient when ChatGPT has rendered a
    required section header but has not yet populated its body.
    """
    value = str(
        text
        or ""
    ).replace(
        "\r\n",
        "\n",
    ).strip()

    if not value:
        return False

    lines = value.splitlines()

    if not lines:
        return False

    structured_status = lines[0].strip().startswith(
        "STATUS:"
    )

    if not structured_status:
        return True

    terminal_headers = {
        "REASON:",
        "EVIDENCE:",
        "NEXT_MODE3_INSTRUCTION:",
    }

    last_nonempty_index = None

    for index in range(
        len(lines) - 1,
        -1,
        -1,
    ):
        if lines[index].strip():
            last_nonempty_index = index
            break

    if last_nonempty_index is None:
        return False

    if (
        lines[
            last_nonempty_index
        ].strip()
        in terminal_headers
    ):
        return False

    return True


# SOPHYANE_CDP_POST_STREAM_DOM_SETTLEMENT_V2
def settle_completed_assistant_text(
    cdp,
    initial_text,
    *,
    timeout=3.0,
    interval=0.25,
    stable_for=1.0,
):
    """Return assistant text only after bounded non-streaming stability.

    ChatGPT may remove the stop/streaming indicator before its final DOM
    mutation lands. A single identical snapshot is therefore insufficient.

    Require the assistant text to remain byte-for-byte unchanged while
    non-streaming for ``stable_for`` seconds. Any text change or resumed
    streaming resets the stability clock.

    The entire settlement phase remains bounded by ``timeout``.
    """

    previous = str(
        initial_text
        or ""
    ).strip()

    started = time.monotonic()

    deadline = (
        started
        + max(
            0.5,
            float(timeout),
        )
    )

    stable_since = (
        started
        if previous
        else None
    )

    while time.monotonic() < deadline:
        time.sleep(
            max(
                0.05,
                float(interval),
            )
        )

        state = assistant_state(
            cdp
        )

        current = str(
            state.get(
                "text",
                "",
            )
            or ""
        ).strip()

        streaming = bool(
            state.get(
                "streaming"
            )
        )

        now = time.monotonic()

        if streaming:
            previous = current
            stable_since = None
            continue

        if not current:
            stable_since = None
            continue

        if current != previous:
            previous = current
            stable_since = now
            continue

        if stable_since is None:
            stable_since = now
            continue

        if (
            now
            - stable_since
        ) >= max(
            0.25,
            float(stable_for),
        ):
            # SOPHYANE_CDP_STRUCTURED_SETTLEMENT_GATE_V1
            #
            # Byte stability alone is not semantic completion when a
            # structured NIFDU response currently ends at an empty required
            # field such as REASON:. Keep observing within the existing
            # bounded settlement window.
            if structured_response_semantically_complete(
                current
            ):
                return current

    # SOPHYANE_CDP_STRUCTURED_TIMEOUT_FAIL_CLOSED_V1
    #
    # Never return an obviously incomplete structured response merely
    # because the bounded DOM-settlement window expired. In particular,
    # STATUS contracts ending at empty REASON:, EVIDENCE:, or
    # NEXT_MODE3_INSTRUCTION: must remain incomplete.
    if (
        previous
        and not structured_response_semantically_complete(
            previous
        )
    ):
        raise TimeoutError(
            "Structured ChatGPT response did not finish "
            "within the post-stream settlement window."
        )

    return previous



def ask(prompt, image=None):
    page = chat_page()

    cdp = CDP(page)

    # SOPHYANE_NIFDU_FAILED_GENERATION_CLEANUP_V1
    #
    # Cleanup is valid only after ChatGPT has actually accepted a new
    # generation request. Pre-send failures must remain read-only with
    # respect to generation state.
    generation_submitted = False

    try:
        cdp.call("Runtime.enable")

        wait_prompt(cdp)

        # SOPHYANE_NIFDU_POST_TIMEOUT_GENERATION_RECOVERY_V1
        #
        # A transport timeout only terminates this Python-side wait. ChatGPT
        # may still be generating in the browser, leaving a Stop control in
        # place and making the next same-provider protocol repair unable to
        # send. Settle/cancel that stale generation before taking the new
        # assistant/user baseline.
        prepare_for_new_generation(
            cdp,
        )

        before = assistant_state(cdp)

        before_count = int(
            before.get(
                "count",
                0,
            )
            or 0
        )

        before_text = str(
            before.get(
                "text",
                "",
            )
            or ""
        ).strip()

        before_user_count = int(
            before.get(
                "user_count",
                0,
            )
            or 0
        )

        attached = False

        if image:
            try:
                attached = attach_file(
                    cdp,
                    image,
                )
            except Exception:
                attached = False

        if image and not attached:
            prompt += (
                "\n\n[SCREENSHOT FALLBACK NOTE]\n"
                "A Termux screenshot was captured locally, "
                "but this ChatGPT page did not expose a "
                "file-input element through CDP. "
                "Use the textual execution evidence above."
            )

        populate_prompt(
            cdp,
            prompt,
        )

        # SOPHYANE_NIFDU_AMBIGUOUS_SEND_COMMIT_V1
        #
        # CDP Runtime.evaluate is side-effecting here: browser JavaScript may
        # execute button.click() even if the WebSocket response carrying the
        # evaluation result is subsequently lost. Mark the request as
        # potentially submitted before entering click_send(), so any exception
        # from that boundary performs state-based cleanup rather than assuming
        # that no browser generation could have started.
        generation_submitted = True

        click_send(cdp)

        deadline = (
            time.monotonic()
            + TIMEOUT
        )

        previous = ""
        stable_since = None

        # SOPHYANE_CDP_IDENTICAL_RESPONSE_FRESHNESS_V1
        #
        # ChatGPT may reuse an assistant DOM node and may legitimately
        # produce text identical to the previous turn. Track the new user
        # turn plus observed streaming so completion does not depend only
        # on assistant count/text changing.
        new_user_turn_seen = False
        streaming_seen = False

        while time.monotonic() < deadline:
            state = assistant_state(cdp)

            count = int(
                state.get("count", 0)
                or 0
            )

            text = str(
                state.get("text", "")
                or ""
            ).strip()

            user_count = int(
                state.get(
                    "user_count",
                    0,
                )
                or 0
            )

            streaming = bool(
                state.get(
                    "streaming"
                )
            )

            if user_count > before_user_count:
                new_user_turn_seen = True

            if (
                new_user_turn_seen
                and streaming
            ):
                streaming_seen = True

            # SOPHYANE_CDP_FRESH_USAGE_LIMIT_TERMINAL_V1
            #
            # ChatGPT may represent an exhausted generation quota as an
            # assistant message rather than as a composer-level banner.
            # Such a response is terminal for this provider call. Treating it
            # as an unfinished ordinary answer burns the entire bridge timeout
            # and incorrectly surfaces "Timed out waiting for ChatGPT."
            #
            # Require freshness relative to the pre-send state so historical
            # quota messages in an older conversation remain harmless.
            response_changed = bool(
                text
                and (
                    count > before_count
                    or text != before_text
                )
            )

            if (
                response_changed
                and not streaming
                and chatgpt_usage_limit_response(
                    text
                )
            ):
                raise RuntimeError(
                    "ChatGPT usage limit reached; "
                    "NIFDU CDP transport is ready but "
                    "the selected ChatGPT session cannot "
                    "generate a new response: "
                    + text
                )

            # ChatGPT's current UI may reuse/update an existing
            # assistant DOM node instead of appending a new node.
            #
            # Therefore response freshness is established by either:
            #
            #   1. assistant node count increased, or
            #   2. last assistant text differs from the pre-send text.
            #
            # Requiring only count > before_count caused valid completed
            # replies to remain invisible to this bridge until timeout.
            fresh = bool(
                text
                and (
                    count > before_count
                    or text != before_text
                    or (
                        new_user_turn_seen
                        and streaming_seen
                        and not streaming
                    )
                )
            )

            if fresh:
                # SOPHYANE_CDP_COMPLETED_FRESH_RESPONSE_RETURN_V1
                #
                # If ChatGPT has appended a genuinely new assistant turn and
                # there is no active stop/streaming control, the completed DOM
                # response is already authoritative. Do not require two more
                # seconds of byte-for-byte innerText stability: current
                # ChatGPT shells can mutate incidental rendered text while the
                # semantic response itself is complete, which previously left
                # the bridge sleeping until its full timeout.
                #
                # For same-node reuse, retain the stronger observed-streaming
                # completion proof. Text-difference-only freshness still uses
                # the historical stability fallback below.
                # SOPHYANE_NIFDU_RESPONSE_COMPLETION_AUTHORITY_V11
                #
                # A newly-created assistant DOM node is not, by itself,
                # proof that ChatGPT finished generating its contents.
                #
                # Current ChatGPT shells can append the assistant node before
                # the streaming indicator becomes observable. Returning merely
                # because:
                #
                #     count > before_count and not streaming
                #
                # can therefore capture a partially populated response.
                #
                # Immediate completion is safe only after this bridge has
                # actually observed the new user turn streaming and then
                # observed that streaming stop.
                #
                # New-node/text-difference freshness without observed stream
                # completion falls through to the existing text-stability
                # proof below.
                observed_stream_completion = bool(
                    not streaming
                    and new_user_turn_seen
                    and streaming_seen
                )

                # SOPHYANE_CDP_COMPLETED_FRESH_TURN_ALIAS_V1
                #
                # Keep the lower-level observed-stream proof explicit for
                # completion-safety tests, while retaining the canonical
                # higher-level completed-fresh-turn contract used by the
                # tracked bridge authority tests.
                completed_fresh_turn = bool(
                    observed_stream_completion
                )

                if observed_stream_completion:
                    # SOPHYANE_CDP_POST_STREAM_SETTLEMENT_GATE_V1
                    #
                    # The stop/streaming control may disappear one DOM tick
                    # before the final assistant text is committed. Settle the
                    # completed response boundedly before returning it.
                    return settle_completed_assistant_text(
                        cdp,
                        text,
                    )

                if completed_fresh_turn:
                    return settle_completed_assistant_text(
                        cdp,
                        text,
                    )

                if text != previous:
                    previous = text
                    stable_since = (
                        time.monotonic()
                    )

                elif (
                    not streaming
                    and stable_since
                    and (
                        time.monotonic()
                        - stable_since
                    ) >= 2.0
                ):
                    return text

            time.sleep(0.75)

        raise TimeoutError(
            "Timed out waiting for ChatGPT."
        )

    except Exception as exc:
        # SOPHYANE_NIFDU_FAILED_GENERATION_CLEANUP_V1
        #
        # Do not hand an active browser-side generation back to the strict
        # runtime. Its automatic protocol repair may invoke this provider
        # immediately, so leaving a Stop state here poisons the next request.
        #
        # Preserve the original exception as the root cause. Cleanup failure
        # is secondary diagnostic evidence only.
        cleanup_error = cleanup_failed_generation(
            cdp,
            generation_submitted=generation_submitted,
        )

        if cleanup_error is not None:
            try:
                exc.add_note(
                    "NIFDU browser-generation cleanup also failed: "
                    f"{type(cleanup_error).__name__}: "
                    f"{cleanup_error}"
                )
            except Exception:
                pass

        raise

    finally:
        cdp.close()


def main():
    if len(sys.argv) < 2:
        print(
            "usage: chatgpt_cdp.py open|ask ...",
            file=sys.stderr,
        )
        return 2

    if sys.argv[1] == "open":
        page = chat_page()

        print(
            "ChatGPT tab:",
            page.get("url", ""),
        )

        print(
            "title:",
            page.get("title", ""),
        )

        return 0

    if sys.argv[1] == "ask":
        if len(sys.argv) < 3:
            raise SystemExit(
                "ask requires prompt file"
            )

        prompt = Path(
            sys.argv[2]
        ).read_text(
            encoding="utf-8"
        )

        image = (
            sys.argv[3]
            if len(sys.argv) >= 4
            else None
        )

        response = ask(
            prompt,
            image=image,
        )

        print(response)

        return 0

    raise SystemExit(
        f"unknown action: {sys.argv[1]}"
    )


if __name__ == "__main__":
    raise SystemExit(main())
