"""Rendered browser evidence using Termux Chromium headless_shell + CDP.

This backend deliberately does not use Selenium, Playwright, or ChromeDriver.

On Termux the Chromium child-process contract is important:
headless_shell must be supplied as an absolute --browser-subprocess-path.
The inherited Termux execution environment is preserved.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
import shutil
import socket
import subprocess
import tempfile
import time
from typing import Callable, Any
import urllib.parse
import urllib.request


Progress = Callable[[str], None]

_BACKEND = "termux-headless-shell-cdp"


@dataclass(frozen=True)
class RenderedEvidence:
    available: bool
    ok: bool
    backend: str
    url: str
    title: str = ""
    ready_state: str = ""
    html_length: int = 0
    body_text_length: int = 0
    viewport_width: int = 0
    viewport_height: int = 0
    document_width: int = 0
    document_height: int = 0
    horizontal_overflow: bool = False
    elements: int = 0
    images: int = 0
    broken_images: int = 0
    buttons: int = 0
    anchors: int = 0
    inputs: int = 0
    interactive: int = 0
    console_errors: int = 0
    log_errors: int = 0
    screenshot_bytes: int = 0
    error: str = ""

    def summary(self) -> str:
        if not self.available:
            detail = (
                f": {self.error}"
                if self.error
                else ""
            )
            return (
                "Rendered evidence: unavailable"
                f"{detail}"
            )

        if not self.ok:
            detail = (
                f": {self.error}"
                if self.error
                else ""
            )
            return (
                "Rendered evidence: FAIL"
                f"; backend={self.backend}"
                f"{detail}"
            )

        return (
            "Rendered evidence: PASS"
            f"; backend={self.backend}"
            f"; title={self.title}"
            f"; viewport="
            f"{self.viewport_width}x"
            f"{self.viewport_height}"
            f"; document="
            f"{self.document_width}x"
            f"{self.document_height}"
            f"; elements={self.elements}"
            f"; images={self.images}"
            f"; broken_images="
            f"{self.broken_images}"
            f"; interactive="
            f"{self.interactive}"
            f"; console_errors="
            f"{self.console_errors}"
            f"; log_errors="
            f"{self.log_errors}"
            f"; horizontal_overflow="
            f"{self.horizontal_overflow}"
            f"; screenshot_bytes="
            f"{self.screenshot_bytes}"
        )


def _free_port() -> int:
    with socket.socket(
        socket.AF_INET,
        socket.SOCK_STREAM,
    ) as sock:
        sock.bind(
            (
                "127.0.0.1",
                0,
            )
        )
        return int(
            sock.getsockname()[1]
        )


def _headless_binary() -> Path | None:
    prefix = str(
        os.environ.get(
            "PREFIX",
            "",
        )
    ).strip()

    if not prefix:
        return None

    candidate = (
        Path(prefix)
        / "lib"
        / "chromium"
        / "headless_shell"
    )

    if (
        candidate.is_file()
        and os.access(
            candidate,
            os.X_OK,
        )
    ):
        return candidate.resolve()

    return None


def _headless_command(
    headless: Path,
    *,
    port: int,
    profile: Path,
) -> list[str]:
    absolute = str(
        headless.resolve()
    )

    return [
        absolute,
        "--headless",
        "--no-sandbox",
        "--disable-dev-shm-usage",
        "--disable-gpu",
        (
            "--browser-subprocess-path="
            + absolute
        ),
        "--disable-background-networking",
        "--disable-component-update",
        "--disable-sync",
        "--no-first-run",
        (
            "--remote-debugging-address="
            "127.0.0.1"
        ),
        (
            "--remote-debugging-port="
            f"{port}"
        ),
        (
            "--user-data-dir="
            f"{profile}"
        ),
        "about:blank",
    ]


def _wait_for_cdp(
    port: int,
    *,
    timeout: float,
) -> dict[str, Any]:
    endpoint = (
        f"http://127.0.0.1:"
        f"{port}/json/version"
    )

    deadline = (
        time.monotonic()
        + timeout
    )

    last_error: Exception | None = None

    while (
        time.monotonic()
        < deadline
    ):
        try:
            with urllib.request.urlopen(
                endpoint,
                timeout=0.5,
            ) as response:
                return json.load(
                    response
                )
        except Exception as error:
            last_error = error
            time.sleep(
                0.1
            )

    raise RuntimeError(
        "CDP endpoint did not become "
        "ready"
        + (
            f": {last_error}"
            if last_error
            else ""
        )
    )


def _create_target(
    port: int,
    url: str,
) -> dict[str, Any]:
    endpoint = (
        f"http://127.0.0.1:"
        f"{port}/json/new?"
        + urllib.parse.quote(
            url,
            safe=":/?=&",
        )
    )

    request = urllib.request.Request(
        endpoint,
        method="PUT",
    )

    with urllib.request.urlopen(
        request,
        timeout=5,
    ) as response:
        return json.load(
            response
        )


_NODE_PROBE = r"""
const fs = require("fs");

const wsUrl = process.argv[1];
const evidencePath = process.argv[2];
const screenshotPath = process.argv[3];
const viewportWidth =
    Number(process.argv[4]);
const viewportHeight =
    Number(process.argv[5]);

const ws =
    new WebSocket(wsUrl);

let nextId = 1;

const pending =
    new Map();

const events = [];


function command(
    method,
    params = {}
) {
    const id =
        nextId++;

    return new Promise(
        (resolve, reject) => {
            pending.set(
                id,
                {
                    resolve,
                    reject
                }
            );

            ws.send(
                JSON.stringify({
                    id,
                    method,
                    params
                })
            );
        }
    );
}


function sleep(ms) {
    return new Promise(
        resolve =>
            setTimeout(
                resolve,
                ms
            )
    );
}


ws.onmessage = event => {
    const message =
        JSON.parse(
            event.data
        );

    if (
        message.id &&
        pending.has(
            message.id
        )
    ) {
        const item =
            pending.get(
                message.id
            );

        pending.delete(
            message.id
        );

        if (message.error) {
            item.reject(
                new Error(
                    JSON.stringify(
                        message.error
                    )
                )
            );
        } else {
            item.resolve(
                message.result
            );
        }

        return;
    }

    if (message.method) {
        events.push(
            message
        );
    }
};


ws.onerror = event => {
    console.error(
        "CDP websocket error",
        event
    );
};


ws.onopen = async () => {
    try {
        await command(
            "Page.enable"
        );

        await command(
            "Runtime.enable"
        );

        await command(
            "Log.enable"
        );

        await command(
            "Emulation.setDeviceMetricsOverride",
            {
                width:
                    viewportWidth,

                height:
                    viewportHeight,

                deviceScaleFactor:
                    1,

                mobile:
                    true
            }
        );

        await sleep(
            1500
        );

        const evaluated =
            await command(
                "Runtime.evaluate",
                {
                    expression: `
(() => {
    const root =
        document.documentElement;

    const body =
        document.body;

    const all =
        [
            ...document
                .querySelectorAll("*")
        ];

    const vw =
        innerWidth;

    const documentWidth =
        Math.max(
            root?.scrollWidth || 0,
            body?.scrollWidth || 0
        );

    const documentHeight =
        Math.max(
            root?.scrollHeight || 0,
            body?.scrollHeight || 0
        );

    const brokenImages =
        [
            ...document.images
        ].filter(
            img =>
                !img.complete ||
                img.naturalWidth === 0 ||
                img.naturalHeight === 0
        );

    const interactive =
        document.querySelectorAll(
            "button,a,input,select," +
            "textarea,[role=button]"
        );

    return {
        href:
            location.href,

        title:
            document.title,

        readyState:
            document.readyState,

        htmlLength:
            root?.outerHTML.length || 0,

        bodyTextLength:
            (
                body?.innerText ||
                ""
            ).trim().length,

        viewport: {
            width:
                innerWidth,

            height:
                innerHeight
        },

        document: {
            width:
                documentWidth,

            height:
                documentHeight
        },

        horizontalOverflow:
            documentWidth >
            vw + 1,

        counts: {
            elements:
                all.length,

            images:
                document.images.length,

            brokenImages:
                brokenImages.length,

            buttons:
                document.querySelectorAll(
                    "button"
                ).length,

            anchors:
                document.querySelectorAll(
                    "a"
                ).length,

            inputs:
                document.querySelectorAll(
                    "input,select,textarea"
                ).length,

            interactive:
                interactive.length
        }
    };
})()
`,
                    returnByValue:
                        true,

                    awaitPromise:
                        true
                }
            );

        const evidence =
            evaluated.result.value;

        const screenshot =
            await command(
                "Page.captureScreenshot",
                {
                    format:
                        "png",

                    captureBeyondViewport:
                        false,

                    fromSurface:
                        true
                }
            );

        fs.writeFileSync(
            screenshotPath,
            Buffer.from(
                screenshot.data,
                "base64"
            )
        );

        evidence.consoleErrors =
            events.filter(
                event =>
                    event.method ===
                    "Runtime.exceptionThrown"
            ).length;

        evidence.logErrors =
            events.filter(
                event =>
                    event.method ===
                    "Log.entryAdded" &&
                    event.params
                        ?.entry
                        ?.level ===
                        "error"
            ).length;

        evidence.screenshotBytes =
            fs.statSync(
                screenshotPath
            ).size;

        fs.writeFileSync(
            evidencePath,
            JSON.stringify(
                evidence,
                null,
                2
            )
        );

        ws.close();

    } catch (error) {
        console.error(
            error
        );

        ws.close();

        process.exitCode = 1;
    }
};
"""


def _result_from_payload(
    url: str,
    payload: dict[str, Any],
) -> RenderedEvidence:
    viewport = (
        payload.get(
            "viewport"
        )
        or {}
    )

    document = (
        payload.get(
            "document"
        )
        or {}
    )

    counts = (
        payload.get(
            "counts"
        )
        or {}
    )

    html_length = int(
        payload.get(
            "htmlLength"
        )
        or 0
    )

    screenshot_bytes = int(
        payload.get(
            "screenshotBytes"
        )
        or 0
    )

    title = str(
        payload.get(
            "title"
        )
        or ""
    )

    actual_url = str(
        payload.get(
            "href"
        )
        or ""
    )

    ok = bool(
        actual_url == url
        and title
        and html_length >= 100
        and int(
            counts.get(
                "elements"
            )
            or 0
        ) >= 3
        and screenshot_bytes >= 1000
    )

    return RenderedEvidence(
        available=True,
        ok=ok,
        backend=_BACKEND,
        url=url,
        title=title,
        ready_state=str(
            payload.get(
                "readyState"
            )
            or ""
        ),
        html_length=html_length,
        body_text_length=int(
            payload.get(
                "bodyTextLength"
            )
            or 0
        ),
        viewport_width=int(
            viewport.get(
                "width"
            )
            or 0
        ),
        viewport_height=int(
            viewport.get(
                "height"
            )
            or 0
        ),
        document_width=int(
            document.get(
                "width"
            )
            or 0
        ),
        document_height=int(
            document.get(
                "height"
            )
            or 0
        ),
        horizontal_overflow=bool(
            payload.get(
                "horizontalOverflow",
                False,
            )
        ),
        elements=int(
            counts.get(
                "elements"
            )
            or 0
        ),
        images=int(
            counts.get(
                "images"
            )
            or 0
        ),
        broken_images=int(
            counts.get(
                "brokenImages"
            )
            or 0
        ),
        buttons=int(
            counts.get(
                "buttons"
            )
            or 0
        ),
        anchors=int(
            counts.get(
                "anchors"
            )
            or 0
        ),
        inputs=int(
            counts.get(
                "inputs"
            )
            or 0
        ),
        interactive=int(
            counts.get(
                "interactive"
            )
            or 0
        ),
        console_errors=int(
            payload.get(
                "consoleErrors"
            )
            or 0
        ),
        log_errors=int(
            payload.get(
                "logErrors"
            )
            or 0
        ),
        screenshot_bytes=(
            screenshot_bytes
        ),
        error=(
            ""
            if ok
            else (
                "rendered page did not "
                "satisfy evidence contract"
            )
        ),
    )


def capture_rendered_evidence(
    url: str,
    workspace: Path,
    progress: Progress,
    *,
    viewport_width: int = 390,
    viewport_height: int = 844,
    timeout: float = 15.0,
) -> RenderedEvidence:
    """Capture real rendered DOM and screenshot evidence.

    Missing Termux headless support is non-fatal.  Callers may
    continue with their ordinary browser-delivery path.
    """
    headless = _headless_binary()

    if headless is None:
        return RenderedEvidence(
            available=False,
            ok=False,
            backend=_BACKEND,
            url=url,
            error=(
                "Termux Chromium "
                "headless_shell unavailable"
            ),
        )

    node = shutil.which(
        "node"
    )

    if not node:
        return RenderedEvidence(
            available=False,
            ok=False,
            backend=_BACKEND,
            url=url,
            error=(
                "Node.js unavailable "
                "for CDP websocket client"
            ),
        )

    root = Path(
        workspace
    ).expanduser().resolve()

    port = _free_port()

    process: subprocess.Popen[bytes] | None = (
        None
    )

    try:
        with tempfile.TemporaryDirectory(
            prefix="sophyane-render-",
        ) as temporary:
            temp = Path(
                temporary
            )

            profile = (
                temp
                / "profile"
            )

            evidence_path = (
                temp
                / "evidence.json"
            )

            screenshot_path = (
                temp
                / "screenshot.png"
            )

            headless_log = (
                temp
                / "headless.log"
            )

            command = _headless_command(
                headless,
                port=port,
                profile=profile,
            )

            progress(
                "Rendered evidence: "
                "starting Termux "
                "headless_shell CDP backend"
            )

            with headless_log.open(
                "wb"
            ) as log_handle:
                process = subprocess.Popen(
                    command,
                    cwd=root,
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                    stderr=log_handle,
                )

                _wait_for_cdp(
                    port,
                    timeout=min(
                        timeout,
                        8.0,
                    ),
                )

                target = _create_target(
                    port,
                    url,
                )

                ws_url = str(
                    target.get(
                        "webSocketDebuggerUrl"
                    )
                    or ""
                )

                if not ws_url:
                    raise RuntimeError(
                        "CDP target has no "
                        "webSocketDebuggerUrl"
                    )

                completed = subprocess.run(
                    [
                        node,
                        "-e",
                        _NODE_PROBE,
                        ws_url,
                        str(
                            evidence_path
                        ),
                        str(
                            screenshot_path
                        ),
                        str(
                            viewport_width
                        ),
                        str(
                            viewport_height
                        ),
                    ],
                    cwd=root,
                    text=True,
                    capture_output=True,
                    timeout=timeout,
                    check=False,
                )

            if (
                completed.returncode != 0
            ):
                detail = (
                    completed.stderr.strip()
                    or completed.stdout.strip()
                    or (
                        "Node CDP probe "
                        "returned non-zero"
                    )
                )

                raise RuntimeError(
                    detail[-1200:]
                )

            if not evidence_path.is_file():
                raise RuntimeError(
                    "CDP probe produced no "
                    "evidence JSON"
                )

            payload = json.loads(
                evidence_path.read_text(
                    encoding="utf-8",
                )
            )

            result = (
                _result_from_payload(
                    url,
                    payload,
                )
            )

            log = (
                headless_log.read_text(
                    encoding="utf-8",
                    errors="replace",
                )
                if headless_log.is_file()
                else ""
            )

            fatal_markers = (
                "CANNOT LINK EXECUTABLE "
                '"/proc/self/exe"',
                "Network service crashed",
                "expected absolute path",
                "GPU process isn't usable",
            )

            fatal = [
                marker
                for marker
                in fatal_markers
                if marker in log
            ]

            if fatal:
                return RenderedEvidence(
                    available=True,
                    ok=False,
                    backend=_BACKEND,
                    url=url,
                    error=(
                        "Chromium runtime "
                        "health failure: "
                        + ", ".join(
                            fatal
                        )
                    ),
                )

            progress(
                result.summary()
            )

            return result

    except Exception as error:
        result = RenderedEvidence(
            available=True,
            ok=False,
            backend=_BACKEND,
            url=url,
            error=(
                f"{type(error).__name__}: "
                f"{error}"
            ),
        )

        progress(
            result.summary()
        )

        return result

    finally:
        if process is not None:
            try:
                process.terminate()
                process.wait(
                    timeout=2,
                )
            except Exception:
                try:
                    process.kill()
                except Exception:
                    pass
