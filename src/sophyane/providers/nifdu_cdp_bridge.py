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

    return matches[-1]


class CDP:
    def __init__(self, page):
        self.socket = websocket.create_connection(
            page["webSocketDebuggerUrl"],
            timeout=30,
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

        self.socket.send(
            json.dumps(
                {
                    "id": ident,
                    "method": method,
                    "params": params or {},
                }
            )
        )

        while True:
            message = json.loads(
                self.socket.recv()
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

  const composer =
    promptTextarea
    || textarea
    || editable;

  const challenged =
    challengeTitle
    || challengeBody
    || cloudflareFrame;

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
    composer,
    interactive:
      composer
      && !challenged
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
    e.innerHTML = '';

    const selection =
      window.getSelection();

    const range =
      document.createRange();

    range.selectNodeContents(e);

    selection.removeAllRanges();
    selection.addRange(range);

    document.execCommand(
      'insertText',
      false,
      value
    );

    e.dispatchEvent(
      new InputEvent(
        'input',
        {{
          bubbles: true,
          inputType: 'insertText',
          data: value
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

    try:
        cdp.call("Runtime.enable")

        wait_prompt(cdp)

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
