# External RSI Watchdog Design

## Goal

Keep the continuous RSI daemon available across provider failures and abrupt
daemon termination by running an independent, restart-capable supervisor.

## Scope

The watchdog is a small Python process launched with `python -m
sophyane.rsi.supervisor`. It owns the configured PID file, daemon socket path,
and watchdog state. It starts the existing `sophyane.rsi_terminal --daemon`
process, checks its PID and heartbeat, and restarts it after abnormal exit or a
stale heartbeat. It does not replace provider fallback or alter RSI task policy.

## Interface

Supported options:

- `--daemonize`: detach the watchdog into a new session.
- `--heartbeat-interval SECONDS`: polling interval, default 5 seconds.
- `--pid-file PATH`: watchdog PID file.
- `--socket-path PATH`: RSI daemon Unix socket path.
- `--state-dir PATH`: RSI state directory; defaults to the existing continuous
  RSI state directory.
- `--watchdog-mode external`: required explicit mode for this supervisor.
- `--wakelock`: acquire/release `termux-wake-lock` when available.
- `--once`: run one health/restart decision and exit, useful for tests and
  external schedulers.

The command returns nonzero for invalid configuration or an unrecoverable
startup error. Runtime daemon failures are recorded and retried with bounded
exponential backoff.

## Lifecycle and safety

The watchdog uses an exclusive lock adjacent to its PID file so only one
watchdog owns a target at a time. It treats a PID file as stale when the PID is
not alive or its command line is not the expected RSI daemon. Stale PID and
socket artifacts are removed only after that ownership check. A live unrelated
PID blocks startup rather than being killed.

The child daemon is launched with the existing `sophyane.rsi_terminal` entry
point and inherits the configured environment. A heartbeat is healthy only if
the JSON heartbeat is readable, the timestamp is within the configured stale
threshold, and the recorded PID matches the child. The supervisor never kills
an unrelated process; it terminates only its own child during controlled
shutdown.

Restart attempts use bounded exponential delays to avoid a crash loop. The
watchdog writes a small JSON status record containing PID, child PID, last
check, restart count, and last error. `--wakelock` is best-effort: missing
Termux API commands are recorded as unavailable, not treated as a daemon
failure.

## Testing

Unit tests cover argument parsing, stale artifact recovery, unrelated PID
protection, heartbeat/PID health decisions, child restart/backoff behavior,
and best-effort wakelock invocation. Tests use temporary directories and a
short-lived Python child; they never control the production RSI process.
