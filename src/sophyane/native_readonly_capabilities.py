"""Fast, deterministic, read-only native capabilities.

These capabilities answer local-state questions without invoking an LLM.
No file mutation, package installation, process termination, or network
modification is performed here.
"""

from __future__ import annotations

import getpass
import json
import os
import platform
import re
import shutil
import socket
import subprocess
from urllib.parse import quote
from datetime import datetime
from pathlib import Path
from typing import Any


def _normalize(text: str) -> str:
    # SOPHYANE_SYSTEM_STORAGE_PHRASE_FIX
    normalized = " ".join(
        str(text or "").casefold().strip().split()
    )

    common_typos = {
        "sytem": "system",
        "storge": "storage",
        "configration": "configuration",
        "configuraton": "configuration",
    }

    words = normalized.split()
    corrected = []

    for word in words:
        clean_word = word.strip("?!.,:;")

        # Ignore standalone punctuation such as "?".
        if not clean_word:
            continue

        corrected.append(
            common_typos.get(clean_word, clean_word)
        )

    return " ".join(corrected).strip()


def _run(
    command: list[str],
    *,
    cwd: Path | None = None,
    timeout: float = 4.0,
) -> str:
    """Run a bounded read-only command and return stdout/stderr text."""
    try:
        completed = subprocess.run(
            command,
            cwd=str(cwd) if cwd else None,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return ""

    stdout = str(completed.stdout or "").strip()
    stderr = str(completed.stderr or "").strip()

    if completed.returncode == 0:
        return stdout

    return stdout or stderr


def _first_command(*names: str) -> str | None:
    for name in names:
        path = shutil.which(name)
        if path:
            return path
    return None


def _format_bytes(value: int | float) -> str:
    amount = float(value)
    units = ("B", "KB", "MB", "GB", "TB")

    for unit in units:
        if abs(amount) < 1024.0 or unit == units[-1]:
            if unit == "B":
                return f"{int(amount)} {unit}"
            return f"{amount:.2f} {unit}"
        amount /= 1024.0

    return f"{amount:.2f} TB"


def _read_text(path: str | Path, limit: int = 20000) -> str:
    try:
        return Path(path).read_text(
            encoding="utf-8",
            errors="replace",
        )[:limit]
    except OSError:
        return ""


def _read_meminfo() -> dict[str, int]:
    values: dict[str, int] = {}

    for line in _read_text("/proc/meminfo").splitlines():
        if ":" not in line:
            continue

        key, raw = line.split(":", 1)
        match = re.search(r"\d+", raw)

        if match:
            # Linux /proc/meminfo values are normally expressed in KiB.
            values[key.strip()] = int(match.group()) * 1024

    return values


def _cpu_model() -> str:
    cpuinfo = _read_text("/proc/cpuinfo")

    for label in (
        "Hardware",
        "model name",
        "Processor",
        "chip name",
    ):
        match = re.search(
            rf"^{re.escape(label)}\s*:\s*(.+)$",
            cpuinfo,
            flags=re.I | re.M,
        )
        if match:
            return match.group(1).strip()

    return platform.processor() or platform.machine() or "Unknown"


def _android_property(name: str) -> str:
    getprop = _first_command("getprop")
    if not getprop:
        return ""

    return _run([getprop, name], timeout=2.0).strip()


def _battery_data() -> dict[str, Any] | None:
    command = _first_command("termux-battery-status")

    if command:
        raw = _run([command], timeout=5.0)
        try:
            value = json.loads(raw)
            if isinstance(value, dict):
                return value
        except (TypeError, ValueError, json.JSONDecodeError):
            pass

    capacity = _read_text(
        "/sys/class/power_supply/battery/capacity",
        limit=100,
    ).strip()
    status = _read_text(
        "/sys/class/power_supply/battery/status",
        limit=100,
    ).strip()

    if not capacity and not status:
        return None

    data: dict[str, Any] = {}

    if capacity:
        try:
            data["percentage"] = int(capacity)
        except ValueError:
            data["percentage"] = capacity

    if status:
        data["status"] = status

    return data


# SOPHYANE_ANDROID_ALARM_STATUS_READBACK
def _read_android_alarm_status() -> dict[str, Any] | None:
    """Read Companion alarm status exported to shared Downloads."""
    candidates = (
        Path.home()
        / "storage"
        / "downloads"
        / "SophyaneAlarmStatus.json",

        Path("/storage/emulated/0/Download/SophyaneAlarmStatus.json"),
    )

    status_file = next(
        (
            candidate
            for candidate in candidates
            if candidate.is_file()
        ),
        None,
    )

    if status_file is None:
        return None

    try:
        data = json.loads(
            status_file.read_text(
                encoding="utf-8",
                errors="replace",
            )
        )
    except (OSError, TypeError, ValueError, json.JSONDecodeError):
        return None

    if not isinstance(data, dict):
        return None

    try:
        trigger_millis = int(
            data.get("trigger_millis", 0) or 0
        )
    except (TypeError, ValueError):
        trigger_millis = 0

    scheduled = bool(data.get("scheduled"))

    if trigger_millis <= int(
        datetime.now().timestamp() * 1000
    ):
        scheduled = False
        trigger_millis = 0

    return {
        "scheduled": scheduled,
        "trigger_millis": trigger_millis,
        "label": str(data.get("label") or ""),
        "source": str(data.get("source") or ""),
        "updated_millis": data.get("updated_millis", 0),
        "path": str(status_file),
        "raw": data,
    }


def _alarm_status_reply() -> str:
    status = _read_android_alarm_status()

    if status is None:
        return (
            "I cannot read Sophyane Companion's alarm status yet. "
            "Install or update Companion to version 0.4.0, open it once, "
            "and then ask again."
        )

    if (
        not status.get("scheduled")
        or int(status.get("trigger_millis") or 0) <= 0
    ):
        return (
            "No future alarm is currently saved in "
            "Sophyane Companion."
        )

    trigger_millis = int(status["trigger_millis"])
    trigger = datetime.fromtimestamp(
        trigger_millis / 1000.0
    ).astimezone()

    label = str(status.get("label") or "Wake up").strip()
    clock = trigger.strftime("%I:%M %p").lstrip("0")
    date = trigger.strftime("%A, %d %B %Y")

    return (
        f"Your next alarm is {clock} on {date}. "
        f"Label: {label}."
    )


# SOPHYANE_ANDROID_ALARM_BRIDGE
def _parse_alarm_time(text: str) -> tuple[int, int] | None:
    """Parse common alarm time forms such as 0700am, 7 am and 19:30."""
    normalized = _normalize(text)

    # 0700am, 0730 pm, 7am, 7:30pm
    compact = re.search(
        r"\b(\d{1,2})(?::?(\d{2}))?\s*(am|pm)\b",
        normalized,
        flags=re.I,
    )

    if compact:
        hour = int(compact.group(1))
        minute = int(compact.group(2) or 0)
        meridiem = compact.group(3).lower()

        if not 1 <= hour <= 12 or not 0 <= minute <= 59:
            return None

        if meridiem == "am":
            hour = 0 if hour == 12 else hour
        else:
            hour = 12 if hour == 12 else hour + 12

        return hour, minute

    # Four-digit 24-hour time: 0700, 1930
    four_digit = re.search(
        r"(?<!\d)([01]\d|2[0-3])([0-5]\d)(?!\d)",
        normalized,
    )

    if four_digit:
        return int(four_digit.group(1)), int(four_digit.group(2))

    # Colon-based 24-hour time: 7:00, 19:30
    colon = re.search(
        r"(?<!\d)([01]?\d|2[0-3]):([0-5]\d)(?!\d)",
        normalized,
    )

    if colon:
        return int(colon.group(1)), int(colon.group(2))

    return None


def _android_alarm_reply(message: str) -> str:
    parsed = _parse_alarm_time(message)

    if parsed is None:
        return (
            "I understood that you want an alarm, but I could not determine "
            "the time. Use a form such as `7:00 am`, `0700`, or `19:30`."
        )

    hour, minute = parsed
    label = "Wake up"

    label_match = re.search(
        r"\b(?:label|called|named)\s+(.+)$",
        str(message or "").strip(),
        flags=re.I,
    )

    if label_match:
        candidate = label_match.group(1).strip(" .")
        if candidate:
            label = candidate[:80]

    uri = (
        "sophyane://alarm/create"
        f"?hour={hour}"
        f"&minute={minute}"
        f"&label={quote(label)}"
    )

    am = _first_command("am")

    if not am:
        return (
            "The Android activity manager is unavailable, so Sophyane could "
            "not open the Companion alarm service."
        )

    result = _run(
        [
            am,
            "start",
            "-a",
            "android.intent.action.VIEW",
            "-d",
            uri,
        ],
        timeout=8.0,
    )

    lowered = result.casefold()

    if (
        "error" in lowered
        or "unable to resolve" in lowered
        or "activity not started" in lowered
    ):
        return (
            "Sophyane Companion could not be opened. Confirm that the app is "
            "installed, then open it once and grant Alarms & reminders access.\n"
            f"Android result: {result}"
        )

    display = f"{hour:02d}:{minute:02d}"

    return (
        f"Opened Sophyane Companion and requested the next alarm for "
        f"{display} with label “{label}”. "
        "The Companion app schedules the alarm natively through Android."
    )


def _time_reply() -> str:
    now = datetime.now().astimezone()
    zone = now.tzname() or "local time"

    return (
        f"The current time is {now.strftime('%I:%M:%S %p')} "
        f"({zone})."
    )


def _date_reply() -> str:
    now = datetime.now().astimezone()

    return (
        f"Today is {now.strftime('%A, %d %B %Y')}."
    )


def _timezone_reply() -> str:
    now = datetime.now().astimezone()
    zone = now.tzname() or "Unknown"
    offset = now.strftime("%z")

    if len(offset) == 5:
        offset = f"{offset[:3]}:{offset[3:]}"

    return f"Local time zone: {zone} (UTC{offset})."


def _identity_reply() -> str:
    return (
        f"User: {getpass.getuser()}\n"
        f"Hostname: {socket.gethostname()}\n"
        f"Current directory: {Path.cwd()}"
    )


def _os_reply() -> str:
    android_release = _android_property("ro.build.version.release")
    android_sdk = _android_property("ro.build.version.sdk")
    manufacturer = _android_property("ro.product.manufacturer")
    model = _android_property("ro.product.model")

    lines = [
        f"System: {platform.system() or 'Unknown'}",
        f"Kernel: {platform.release() or 'Unknown'}",
        f"Architecture: {platform.machine() or 'Unknown'}",
    ]

    if android_release:
        lines.append(f"Android: {android_release}")

    if android_sdk:
        lines.append(f"Android SDK: {android_sdk}")

    if manufacturer or model:
        lines.append(
            "Device: "
            + " ".join(
                value for value in (manufacturer, model) if value
            )
        )

    return "\n".join(lines)


def _cpu_reply() -> str:
    logical = os.cpu_count() or 0

    return (
        f"CPU: {_cpu_model()}\n"
        f"Architecture: {platform.machine() or 'Unknown'}\n"
        f"Logical CPUs: {logical}"
    )


def _memory_reply() -> str:
    values = _read_meminfo()

    if not values:
        return "RAM information is unavailable."

    total = values.get("MemTotal", 0)
    available = values.get("MemAvailable", 0)
    used = max(0, total - available)

    return (
        f"RAM total: {_format_bytes(total)}\n"
        f"RAM used: {_format_bytes(used)}\n"
        f"RAM available: {_format_bytes(available)}"
    )


def _storage_reply() -> str:
    root = Path.home()

    try:
        usage = shutil.disk_usage(root)
    except OSError as error:
        return f"Storage information is unavailable: {error}"

    return (
        f"Storage path: {root}\n"
        f"Total: {_format_bytes(usage.total)}\n"
        f"Used: {_format_bytes(usage.used)}\n"
        f"Free: {_format_bytes(usage.free)}"
    )


def _battery_reply() -> str:
    data = _battery_data()

    if not data:
        return (
            "Battery information is unavailable. In Termux, install and "
            "authorize Termux:API to expose detailed battery data."
        )

    lines = ["Battery information:"]

    preferred = (
        ("percentage", "Charge"),
        ("status", "Status"),
        ("plugged", "Power source"),
        ("health", "Health"),
        ("temperature", "Temperature"),
        ("current", "Current"),
    )

    for key, label in preferred:
        if key not in data:
            continue

        value = data[key]

        if key == "percentage":
            value = f"{value}%"
        elif key == "temperature":
            value = f"{value} °C"

        lines.append(f"{label}: {value}")

    return "\n".join(lines)


def _phone_reply() -> str:
    manufacturer = _android_property("ro.product.manufacturer")
    brand = _android_property("ro.product.brand")
    model = _android_property("ro.product.model")
    device = _android_property("ro.product.device")
    android = _android_property("ro.build.version.release")
    sdk = _android_property("ro.build.version.sdk")
    build = _android_property("ro.build.display.id")
    security = _android_property("ro.build.version.security_patch")
    soc = (
        _android_property("ro.soc.model")
        or _android_property("ro.board.platform")
        or _cpu_model()
    )

    mem = _read_meminfo()
    total_ram = mem.get("MemTotal", 0)

    try:
        storage = shutil.disk_usage(Path.home())
    except OSError:
        storage = None

    lines = ["Phone configuration:"]

    fields = (
        ("Manufacturer", manufacturer),
        ("Brand", brand),
        ("Model", model),
        ("Device", device),
        ("Android version", android),
        ("Android SDK", sdk),
        ("Security patch", security),
        ("Build", build),
        ("Processor / SoC", soc),
        ("Architecture", platform.machine()),
    )

    for label, value in fields:
        if value:
            lines.append(f"{label}: {value}")

    if total_ram:
        lines.append(f"RAM: {_format_bytes(total_ram)}")

    if storage:
        lines.append(f"Storage total: {_format_bytes(storage.total)}")
        lines.append(f"Storage free: {_format_bytes(storage.free)}")

    battery = _battery_data()
    if battery and "percentage" in battery:
        lines.append(f"Battery: {battery['percentage']}%")

    if len(lines) == 1:
        return (
            "Android device properties are unavailable in this environment."
        )

    return "\n".join(lines)


def _uptime_reply() -> str:
    raw = _read_text("/proc/uptime", limit=100).strip()

    try:
        seconds = int(float(raw.split()[0]))
    except (IndexError, TypeError, ValueError):
        # Android may restrict /proc/uptime. Fall back to the system
        # uptime command, which normally returns text such as:
        # "up 2 days, 4 hours, 12 minutes".
        command = _first_command("uptime")
        if command:
            output = _run([command, "-p"], timeout=3.0)
            if not output:
                output = _run([command], timeout=3.0)

            if output:
                return "System uptime: " + output.strip().rstrip(".") + "."

        return "System uptime is unavailable."

    days, remainder = divmod(seconds, 86400)
    hours, remainder = divmod(remainder, 3600)
    minutes, seconds = divmod(remainder, 60)

    parts: list[str] = []

    if days:
        parts.append(f"{days} day{'s' if days != 1 else ''}")
    if hours:
        parts.append(f"{hours} hour{'s' if hours != 1 else ''}")
    if minutes:
        parts.append(f"{minutes} minute{'s' if minutes != 1 else ''}")
    if not parts:
        parts.append(f"{seconds} seconds")

    return "System uptime: " + ", ".join(parts) + "."


def _process_reply() -> str:
    ps = _first_command("ps")

    if not ps:
        return "The process-list command is unavailable."

    for args in (
        [ps, "-eo", "pid,ppid,stat,%cpu,%mem,comm", "--sort=-%cpu"],
        [ps, "-A", "-o", "PID,PPID,STAT,NAME"],
        [ps, "-A"],
    ):
        raw = _run(args, timeout=4.0)
        if raw:
            lines = raw.splitlines()
            return "Running processes:\n" + "\n".join(lines[:31])

    return "No process information was returned."


def _ports_reply() -> str:
    ss = _first_command("ss")

    if ss:
        raw = _run([ss, "-lntup"], timeout=4.0)
        if raw:
            return "Listening ports:\n" + "\n".join(
                raw.splitlines()[:41]
            )

    netstat = _first_command("netstat")

    if netstat:
        raw = _run([netstat, "-lnt"], timeout=4.0)
        if raw:
            return "Listening ports:\n" + "\n".join(
                raw.splitlines()[:41]
            )

    return "No supported listening-port command was found."


def _network_reply() -> str:
    ip = _first_command("ip")

    if ip:
        raw = _run([ip, "-brief", "address"], timeout=4.0)
        if raw:
            return "Network interfaces:\n" + raw

    ifconfig = _first_command("ifconfig")

    if ifconfig:
        raw = _run([ifconfig], timeout=4.0)
        if raw:
            return "Network interfaces:\n" + "\n".join(
                raw.splitlines()[:60]
            )

    try:
        addresses = socket.getaddrinfo(
            socket.gethostname(),
            None,
        )
        values = sorted(
            {
                item[4][0]
                for item in addresses
                if item and item[4]
            }
        )
    except OSError:
        values = []

    if values:
        return "Local addresses:\n" + "\n".join(values)

    return "Network-interface information is unavailable."


def _git_root(cwd: Path) -> Path | None:
    git = _first_command("git")

    if not git:
        return None

    raw = _run(
        [git, "rev-parse", "--show-toplevel"],
        cwd=cwd,
        timeout=3.0,
    )

    if not raw:
        return None

    return Path(raw.splitlines()[0]).expanduser().resolve()


def _git_status_reply(cwd: Path) -> str:
    git = _first_command("git")

    if not git:
        return "Git is not installed."

    root = _git_root(cwd)

    if root is None:
        return f"{cwd} is not inside a Git repository."

    branch = _run(
        [git, "branch", "--show-current"],
        cwd=root,
        timeout=3.0,
    ) or "(detached HEAD)"

    status = _run(
        [git, "status", "--short", "--branch"],
        cwd=root,
        timeout=4.0,
    )

    return (
        f"Repository: {root}\n"
        f"Branch: {branch}\n"
        f"{status or 'Working tree is clean.'}"
    )


def _git_log_reply(cwd: Path) -> str:
    git = _first_command("git")

    if not git:
        return "Git is not installed."

    root = _git_root(cwd)

    if root is None:
        return f"{cwd} is not inside a Git repository."

    raw = _run(
        [
            git,
            "log",
            "-10",
            "--date=short",
            "--pretty=format:%h  %ad  %s",
        ],
        cwd=root,
        timeout=5.0,
    )

    return (
        f"Recent commits in {root}:\n"
        + (raw or "No commits were found.")
    )


def _project_reply(cwd: Path) -> str:
    root = _git_root(cwd) or cwd.resolve()

    indicators = {
        "Python": (
            "pyproject.toml",
            "setup.py",
            "requirements.txt",
            "Pipfile",
        ),
        "Node.js / JavaScript": (
            "package.json",
            "pnpm-lock.yaml",
            "yarn.lock",
        ),
        "Rust": ("Cargo.toml",),
        "CMake / C++": ("CMakeLists.txt",),
        "Go": ("go.mod",),
        "Java / Gradle": (
            "pom.xml",
            "build.gradle",
            "build.gradle.kts",
        ),
        "Docker": (
            "Dockerfile",
            "docker-compose.yml",
            "compose.yml",
        ),
    }

    detected: list[str] = []
    evidence: list[str] = []

    for technology, filenames in indicators.items():
        present = [
            filename
            for filename in filenames
            if (root / filename).exists()
        ]

        if present:
            detected.append(technology)
            evidence.extend(present)

    test_locations = [
        name
        for name in ("tests", "test", "spec")
        if (root / name).is_dir()
    ]

    readmes = [
        path.name
        for path in root.iterdir()
        if path.is_file()
        and path.name.casefold().startswith("readme")
    ]

    lines = [
        f"Project root: {root}",
        (
            "Detected technologies: "
            + (", ".join(detected) if detected else "Unknown")
        ),
    ]

    if evidence:
        lines.append("Build/dependency files: " + ", ".join(evidence))

    if test_locations:
        lines.append("Test directories: " + ", ".join(test_locations))
    else:
        lines.append("Test directories: none detected")

    if readmes:
        lines.append("README files: " + ", ".join(readmes))
    else:
        lines.append("README files: none detected")

    return "\n".join(lines)


# SOPHYANE_AGENT_INTROSPECTION
# SOPHYANE_TOKEN_USAGE_INTROSPECTION
def _token_usage_reply() -> str:
    """Give a truthful answer unless timestamped attribution exists."""
    return (
        "Per-agent token usage for the last 24 hours is not currently "
        "available. Sophyane does not yet persist model-token usage with "
        "both an agent or worker identifier and a timestamp. Native workers, "
        "the execution kernel and worker-pool threads consume no LLM tokens "
        "directly; tokens are consumed only when a worker calls an LLM "
        "provider. A reliable report requires timestamped usage events with "
        "provider, model, worker role, input tokens and output tokens."
    )


# SOPHYANE_SAAS_AGENT_ADVICE
def _saas_agent_reply() -> str:
    return (
        "Recommended Sophyane architecture for SaaS services:\n"
        "1. SophyaneAgent — customer-facing API/chat agent.\n"
        "2. Multi-agent supervisor — routes complex requests and controls "
        "worker limits, retries and task graphs.\n"
        "3. Specialist workers — handle domain-specific jobs such as coding, "
        "analysis, support, document processing or automation.\n"
        "4. Executor worker — performs validated tools and deterministic "
        "operations.\n"
        "5. Reviewer worker — checks and merges worker outputs before the "
        "customer receives them.\n"
        "6. Native workers — provide fast, low-cost local capabilities.\n"
        "7. LLM provider worker — uses Gemini, OpenAI or another configured "
        "provider only when generative reasoning is required.\n\n"
        "Recommended flow:\n"
        "Customer/API → SophyaneAgent → Supervisor → "
        "Specialist/Executor → Reviewer → Response\n\n"
        "For most SaaS products, expose SophyaneAgent as the public service "
        "and keep the supervisor, specialists, executor and reviewer internal."
    )


def _agent_architecture_reply() -> str:
    """Describe Sophyane's grounded agent and worker architecture."""
    max_workers = 6

    try:
        from sophyane.multiagent import MultiAgentRuntime

        # Read the constructor default without starting a runtime.
        import inspect

        parameter = inspect.signature(
            MultiAgentRuntime.__init__
        ).parameters.get("max_workers")

        if (
            parameter is not None
            and isinstance(parameter.default, int)
        ):
            max_workers = parameter.default
    except Exception:
        pass

    native_pool_workers = 4

    try:
        native_pool_workers = max(
            2,
            int(
                os.environ.get(
                    "SOPHYANE_NATIVE_POOL_WORKERS",
                    "4",
                )
            ),
        )
    except (TypeError, ValueError):
        native_pool_workers = 4

    return (
        "Sophyane agent architecture:\n"
        "Main user-facing agent: 1 SophyaneAgent\n"
        "Multi-agent supervisor: available\n"
        f"Maximum concurrent specialist workers: {max_workers}\n"
        "Built-in worker roles include specialist, executor and reviewer.\n"
        "Optional collaborative workers: NIFDU, Neuron and an LLM provider.\n"
        f"Native execution pool: {native_pool_workers} worker threads "
        "(threads are execution workers, not separate assistant agents)."
    )


def _agent_count_reply() -> str:
    """Answer agent-count questions without pretending all workers are active."""
    max_workers = 6

    try:
        from sophyane.multiagent import MultiAgentRuntime
        import inspect

        parameter = inspect.signature(
            MultiAgentRuntime.__init__
        ).parameters.get("max_workers")

        if (
            parameter is not None
            and isinstance(parameter.default, int)
        ):
            max_workers = parameter.default
    except Exception:
        pass

    return (
        "Sophyane has 1 main user-facing agent. "
        "For complex tasks, its multi-agent supervisor can launch "
        f"up to {max_workers} concurrent specialist workers. "
        "It can also coordinate optional NIFDU, Neuron and LLM workers."
    )


def _tool_versions_reply() -> str:
    tools: tuple[
        tuple[str, tuple[str, ...], tuple[str, ...]],
        ...
    ] = (
        ("Python", ("python", "python3"), ("--version",)),
        ("Git", ("git",), ("--version",)),
        ("Node.js", ("node",), ("--version",)),
        ("npm", ("npm",), ("--version",)),
        ("Rust", ("rustc",), ("--version",)),
        ("Cargo", ("cargo",), ("--version",)),
        ("Clang", ("clang",), ("--version",)),
        ("CMake", ("cmake",), ("--version",)),
        ("Ninja", ("ninja",), ("--version",)),
    )

    lines = ["Installed development tools:"]

    for label, names, arguments in tools:
        command = _first_command(*names)

        if not command:
            continue

        raw = _run(
            [command, *arguments],
            timeout=3.0,
        )

        if raw:
            lines.append(f"{label}: {raw.splitlines()[0]}")

    if len(lines) == 1:
        return "No recognized development tools were found."

    return "\n".join(lines)


def try_native_readonly_reply(
    message: str,
    *,
    cwd: str | Path | None = None,
) -> str | None:
    """Return a grounded native response, or None for normal LLM routing."""
    text = _normalize(message)
    working_directory = (
        Path(cwd).expanduser()
        if cwd is not None
        else Path.cwd()
    )

    if not text:
        return None

    # SOPHYANE_EXACT_NATIVE_TIME_ROUTING
    # Current local time is deterministic device state and must never be
    # answered by Gemini or a local language model.
    exact_time_queries = {
        "time",
        "time now",
        "current time",
        "local time",
        "show time",
        "show current time",
        "tell me the time",
        "tell me current time",
        "what time is it",
        "what time is it now",
        "what is time",
        "what is time now",
        "what is the time",
        "what is the time now",
        "current time now",
    }

    if text in exact_time_queries:
        return _time_reply()

    # Grounded model-token accounting
    token_usage_patterns = (
        "token usage",
        "tokens used",
        "tokens consumed",
        "token consumed",
        "how many tokens",
        "agent tokens",
        "worker tokens",
    )

    if any(pattern in text for pattern in token_usage_patterns):
        return _token_usage_reply()

    # SaaS deployment architecture
    saas_agent_patterns = (
        "agent for saas",
        "agents for saas",
        "saas agent",
        "saas services",
        "give saas services",
        "provide saas services",
        "use for saas",
        "saas architecture",
        "saas deployment",
    )

    if any(pattern in text for pattern in saas_agent_patterns):
        return _saas_agent_reply()

    # Agent and worker architecture
    agent_count_patterns = (
        "how many agents",
        "number of agents",
        "agent count",
        "how many workers",
        "number of workers",
    )

    if any(pattern in text for pattern in agent_count_patterns):
        return _agent_count_reply()

    agent_architecture_patterns = (
        "what does this agent do",
        "what do your agents do",
        "what agents do you have",
        "which agents do you have",
        "show agents",
        "list agents",
        "agent architecture",
        "multi agent architecture",
        "multi-agent architecture",
        "worker architecture",
    )

    if any(
        pattern in text
        for pattern in agent_architecture_patterns
    ):
        return _agent_architecture_reply()

    # Read the real alarm from Sophyane Companion.
    alarm_status_phrases = (
        "what is morning alarm time",
        "what is my alarm time",
        "what time is my alarm",
        "when is my alarm",
        "show my alarm",
        "show alarm time",
        "next alarm",
        "alarm status",
        "check alarm",
        "current alarm",
        "saved alarm",
    )

    if any(
        phrase in text
        for phrase in alarm_status_phrases
    ):
        return _alarm_status_reply()

    # Native Android wake-up alarm
    alarm_words = (
        "set alarm",
        "create alarm",
        "wake me",
        "wake me up",
        "alarm for",
        "alarm at",
    )

    if any(phrase in text for phrase in alarm_words):
        return _android_alarm_reply(message)

    # Time and calendar
    if re.fullmatch(
        r"(?:what(?:'s| is)?|tell me|show me)?\s*"
        r"(?:the\s+)?(?:current\s+)?time(?:\s+now)?\??",
        text,
    ):
        return _time_reply()

    if text in {
        "time now",
        "current time",
        "what time is it",
        "what is time now",
        "what is the time now",
    }:
        return _time_reply()

    if re.fullmatch(
        r"(?:what(?:'s| is)?|tell me|show me)?\s*"
        r"(?:today'?s\s+|current\s+)?date\??",
        text,
    ) or text in {
        "what day is today",
        "what is today",
        "today",
        "date today",
        "current date",
    }:
        return _date_reply()

    if "time zone" in text or "timezone" in text:
        return _timezone_reply()

    # Identity and operating system
    if text in {
        "who am i",
        "current user",
        "show current user",
        "hostname",
        "what is my hostname",
        "current directory",
        "working directory",
        "where am i",
        "pwd",
    }:
        return _identity_reply()

    if any(
        phrase in text
        for phrase in (
            "operating system",
            "os version",
            "kernel version",
            "system information",
            "system info",
            "system configuration",
            "system configuration information",
            "show system configuration",
            "my system configuration",
            "device system information",
            "what os",
        )
    ):
        return _os_reply()

    # Android / phone
    if any(
        phrase in text
        for phrase in (
            "configuration of my phone",
            "configuration of this phone",
            "phone configuration",
            "phone specifications",
            "phone specification",
            "phone specs",
            "device configuration",
            "device specifications",
            "android configuration",
        )
    ):
        return _phone_reply()

    # Hardware and resources
    if any(
        phrase in text
        for phrase in (
            "cpu information",
            "cpu info",
            "processor information",
            "processor info",
            "what cpu",
            "what processor",
            "cpu model",
        )
    ):
        return _cpu_reply()

    if any(
        phrase in text
        for phrase in (
            "ram information",
            "ram info",
            "memory information",
            "memory usage",
            "how much ram",
            "available ram",
        )
    ):
        return _memory_reply()

    if any(
        phrase in text
        for phrase in (
            "storage information",
            "storage info",
            "storage capacity",
            "my storage capacity",
            "what is storage capacity",
            "what storage capacity",
            "total storage",
            "disk capacity",
            "disk usage",
            "free storage",
            "available storage",
            "how much storage",
        )
    ):
        return _storage_reply()

    if "battery" in text and any(
        word in text
        for word in (
            "status",
            "information",
            "info",
            "percentage",
            "level",
            "health",
            "charge",
        )
    ):
        return _battery_reply()

    if text in {
        "uptime",
        "system uptime",
        "how long has the system been running",
    }:
        return _uptime_reply()

    # Processes and network
    if any(
        phrase in text
        for phrase in (
            "list processes",
            "running processes",
            "show processes",
            "process list",
        )
    ):
        return _process_reply()

    if any(
        phrase in text
        for phrase in (
            "list ports",
            "listening ports",
            "show ports",
            "open ports",
        )
    ):
        return _ports_reply()

    if any(
        phrase in text
        for phrase in (
            "network interfaces",
            "network information",
            "network info",
            "ip address",
            "local ip",
            "show ip",
        )
    ):
        return _network_reply()

    # Git and project inspection
    if text in {
        "git status",
        "show git status",
        "repository status",
        "repo status",
        "current branch",
        "git branch",
    }:
        return _git_status_reply(working_directory)

    if any(
        phrase in text
        for phrase in (
            "git log",
            "recent commits",
            "commit history",
            "git history",
        )
    ):
        return _git_log_reply(working_directory)

    if any(
        phrase in text
        for phrase in (
            "inspect project",
            "project information",
            "project info",
            "detect project",
            "project configuration",
            "what type of project",
            "detect language",
            "detect build system",
        )
    ):
        return _project_reply(working_directory)

    if any(
        phrase in text
        for phrase in (
            "development tools",
            "developer tools",
            "tool versions",
            "installed compilers",
            "compiler versions",
        )
    ):
        return _tool_versions_reply()

    return None
