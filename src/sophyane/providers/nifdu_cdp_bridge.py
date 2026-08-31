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


def wait_prompt(cdp):
    deadline = time.monotonic() + 90

    while time.monotonic() < deadline:
        ready = cdp.evaluate(
            r"""
(() => Boolean(
  document.querySelector('#prompt-textarea') ||
  document.querySelector('textarea') ||
  document.querySelector('[contenteditable="true"]')
))()
"""
        )

        if ready:
            return

        time.sleep(1)

    raise RuntimeError(
        "ChatGPT prompt box was not detected."
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
                if text != previous:
                    previous = text
                    stable_since = (
                        time.monotonic()
                    )

                elif (
                    not state.get(
                        "streaming"
                    )
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
