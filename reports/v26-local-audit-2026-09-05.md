# Sophyane 26.0.0 local audit — 2026-09-05

Scope: current dirty working tree in `/data/data/com.termux/files/home/sophyane`, based on commit `8c284e2`. Both project metadata and runtime version identify 26.0.0. Existing changes were reviewed as part of this version; no application code was edited.

Verdict: not ready to describe as flawless. The following defects were reproduced locally without live model calls.

## Confirmed defects

1. **High: graph deadline is applied separately to each future.** `src/sophyane/readonly_task_graph.py:95-98` computes remaining time once, then reuses it for each worker. Four blocked workers with a 0.05-second graph deadline returned after 0.199 seconds. Recompute remaining time against an absolute deadline before every wait; stop waiting when it expires.
2. **High: timed-out graph workers remain active.** `src/sophyane/readonly_task_graph.py:105` calls `shutdown(wait=False, cancel_futures=True)`, which cannot stop already-running workers. In the same reproduction, all four workers were still active when the graph returned, and completed after a controlled release. Local graph callers share their provider with these workers (`agent.py:102`), so outstanding calls can overlap subsequent work. Use cooperative cancellation and provider deadlines, or process isolation where hard termination is necessary. Merely cancelling futures is insufficient.
3. **High: logout during a failed chat request leaves chat stuck.** `src/sophyane/browser/home/app.js:319-322` clears `auth`; the pending submit handler dereferences `auth.email` at line 987 in its error handler. Executing the actual submit handler with stubbed UI and a request rejection after logout produced `Cannot read properties of null (reading 'email')`, `busy=true`, and `sendDisabled=true`. Capture the request identity and restore busy/UI state in `finally`.
4. **Medium: selecting an unavailable cloud API raises an exception.** `src/sophyane/startup_policy.py:757-760` raises when External LLM → Cloud API is chosen without configured clouds. Reproduced with mocked Codex availability and input `4`, `1`. The submenu displays Cloud API without an availability warning and offers no recovery loop. Mark unavailable choices and reprompt.
5. **Medium: browser requests lack application timeouts/cancellation.** `src/sophyane/browser/home/app.js:466-478,523-539` uses fetch without an abort signal; the submit handler waits for completion before clearing its global busy state. A stalled request has no bounded recovery or user cancellation. This is a source-confirmed omission; an actual stalled browser/network session was not run.

## Verification

- All 454 Python files under `src/sophyane` passed AST parsing.
- Browser `app.js` passed `node --check`.
- Focused pytest selection covering graphs, harnesses, agents, loops, terminal UI, startup, mode 4, and visualization: **393 passed, 7 failed, 2698 deselected**, 62.67 seconds.
- Separate continuous RSI/service supervisors, browser no-progress, and duplicate-command completion tests: **22 passed**, 0.86 seconds. Counts overlap with the broader suite and must not be added to it.
- Startup environment-isolation file alone: **6 passed**. Its failure in the combined selection indicates test-order/environment contamination, not a standalone demonstrated startup failure.
- Several failed startup tests still expect mode 4 to be directly named/selected as Cloud LLM. The implementation now has an external-provider submenu. Update those expectations and explicitly mock host executable discovery before interpreting every failure as a product regression.

## Limits

Browser automation could not run: `agent-browser` is not installed, and Chromium was not found on PATH. The agent-browser skill was consulted and availability checked. No screenshot-based desktop/mobile layout validation was completed. CSS review found a fixed, vertically centered auth gate without its own overflow scrolling; short-viewport/keyboard behavior needs visual testing before reporting this as a confirmed layout defect.

Graph rendering tests are automated checks, not visual certification. No live paid provider, OTP/email, browser-provider, production learning, or prolonged real-model soak test was intentionally initiated. Passing mocks and unit checks does not establish flawless end-to-end operation.
