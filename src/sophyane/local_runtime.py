"""Hardware-aware open-model bootstrap when frontier API credits fail.

Sophyane automatically:
1. Profiles CPU/RAM/disk
2. Chooses a small open model that fits the machine
3. Tries Ollama install/serve/pull
4. If Ollama fails → downloads a hardware-fit GGUF from Hugging Face
   (or GitHub release mirrors) and llama.cpp binaries from GitHub
5. Starts llama-server and switches config to local_gguf / ollama
"""

from __future__ import annotations

import json
import logging
import os
import platform
import shutil
import subprocess
import time
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable

from sophyane.config import (
    CONFIG_DIR,
    load_config,
    save_config,
    save_json,
)

LOGGER = logging.getLogger("sophyane")
STATE_DIR = Path.home() / ".local" / "state" / "sophyane"
LOCAL_STATE_FILE = STATE_DIR / "local_runtime.json"
GGUF_STATE_FILE = STATE_DIR / "gguf_runtime.json"
OLLAMA_HOST = os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434").rstrip("/")
# 8766 avoids clash with sophyane-web which often binds 8765.
LLAMA_SERVER_HOST = os.environ.get("SOPHYANE_LLAMA_SERVER", "http://127.0.0.1:8766").rstrip("/")
BIN_DIR = Path.home() / ".local" / "bin"
MODELS_DIR = Path.home() / ".local" / "share" / "sophyane" / "models"
GGUF_DIR = MODELS_DIR / "gguf"
LLAMA_DIR = MODELS_DIR / "llama.cpp"
LLAMA_RUNTIME_DIR = LLAMA_DIR / "runtime"
USER_AGENT = "SophyaneLocalRuntime/16.1 (+https://github.com/badrpk/sophyane)"

ProgressFn = Callable[[str], None]


@dataclass(frozen=True)
class HardwareProfile:
    arch: str
    cpus: int
    ram_mb: int
    disk_free_mb: int
    os_name: str
    virtualization: str

    @property
    def tier(self) -> str:
        """Hardware tier used to pick open GGUF size (larger machine → stronger model)."""
        if self.ram_mb < 2500 or self.disk_free_mb < 900:
            return "nano"
        if self.ram_mb < 5500 or self.disk_free_mb < 2500:
            return "micro"
        if self.ram_mb < 12000:
            return "small"
        if self.ram_mb < 20000 or self.disk_free_mb < 8000:
            return "standard"
        # High-RAM / desktop / workstation: allow 7–8B class local models
        return "pro"


# (model_tag, approx_download_mb, min_ram_mb, notes)
MODEL_CATALOG: dict[str, list[tuple[str, int, int, str]]] = {
    "nano": [
        ("tinyllama", 650, 1500, "TinyLlama 1.1B — fits Crostini / 2–3GB RAM"),
        ("qwen2.5:0.5b", 400, 1200, "Qwen2.5 0.5B — ultra-light"),
        ("smollm2:135m", 100, 800, "SmolLM2 135M — last-resort tiny model"),
    ],
    "micro": [
        # Prefer sub-1B models first on 2.5–5GB machines (Crostini / thin VMs).
        ("qwen2.5:0.5b", 400, 1200, "Qwen2.5 0.5B"),
        ("tinyllama", 650, 1500, "TinyLlama 1.1B"),
        ("llama3.2:1b", 1300, 2800, "Llama 3.2 1B"),
    ],
    "small": [
        ("llama3.2:3b", 2000, 4500, "Llama 3.2 3B"),
        ("llama3.2:1b", 1300, 2500, "Llama 3.2 1B"),
        ("qwen2.5:1.5b", 1000, 2500, "Qwen2.5 1.5B"),
    ],
    "standard": [
        ("llama3.2:3b", 2000, 4500, "Llama 3.2 3B"),
        ("qwen2.5:3b", 2000, 4500, "Qwen2.5 3B"),
        ("llama3.1:8b", 4700, 9000, "Llama 3.1 8B"),
    ],
    "pro": [
        ("llama3.1:8b", 4700, 10000, "Llama 3.1 8B — strong local agent"),
        ("qwen2.5:7b", 4500, 10000, "Qwen2.5 7B"),
        ("llama3.2:3b", 2000, 4500, "Llama 3.2 3B (lighter)"),
    ],
}


@dataclass(frozen=True)
class HfGgufSpec:
    """Hardware-fit GGUF available from Hugging Face (primary) or GitHub mirrors."""

    key: str
    repo: str
    filename: str
    size_mb: int
    min_ram_mb: int
    notes: str
    # Optional GitHub release mirrors: (repo, tag, asset_name)
    github_mirrors: tuple[tuple[str, str, str], ...] = ()

    def hf_urls(self) -> list[str]:
        base = f"https://huggingface.co/{self.repo}/resolve/main/{self.filename}"
        return [
            base,
            f"{base}?download=true",
            f"https://huggingface.co/{self.repo}/resolve/main/{self.filename}?download=true",
        ]

    def github_urls(self) -> list[str]:
        urls: list[str] = []
        for repo, tag, asset in self.github_mirrors:
            urls.append(
                f"https://github.com/{repo}/releases/download/{tag}/{asset}"
            )
        return urls


# Ordered per tier — first entry that fits free disk + RAM wins.
HF_GGUF_CATALOG: dict[str, list[HfGgufSpec]] = {
    "nano": [
        HfGgufSpec(
            "smollm2-135m",
            "HuggingFaceTB/SmolLM2-135M-Instruct-GGUF",
            "smollm2-135m-instruct-q8_0.gguf",
            140,
            800,
            "SmolLM2 135M Instruct Q8 — last-resort tiny CPU model",
        ),
        HfGgufSpec(
            "qwen2.5-0.5b",
            "Qwen/Qwen2.5-0.5B-Instruct-GGUF",
            "qwen2.5-0.5b-instruct-q4_k_m.gguf",
            400,
            1200,
            "Qwen2.5 0.5B Instruct Q4_K_M",
        ),
        HfGgufSpec(
            "tinyllama",
            "TheBloke/TinyLlama-1.1B-Chat-v1.0-GGUF",
            "tinyllama-1.1b-chat-v1.0.Q4_K_M.gguf",
            640,
            1500,
            "TinyLlama 1.1B Chat Q4_K_M",
        ),
    ],
    "micro": [
        HfGgufSpec(
            "qwen2.5-0.5b",
            "Qwen/Qwen2.5-0.5B-Instruct-GGUF",
            "qwen2.5-0.5b-instruct-q4_k_m.gguf",
            400,
            1200,
            "Qwen2.5 0.5B Instruct Q4_K_M",
        ),
        HfGgufSpec(
            "tinyllama",
            "TheBloke/TinyLlama-1.1B-Chat-v1.0-GGUF",
            "tinyllama-1.1b-chat-v1.0.Q4_K_M.gguf",
            640,
            1500,
            "TinyLlama 1.1B Chat Q4_K_M",
        ),
        HfGgufSpec(
            "smollm2-360m",
            "HuggingFaceTB/SmolLM2-360M-Instruct-GGUF",
            "smollm2-360m-instruct-q8_0.gguf",
            380,
            1400,
            "SmolLM2 360M Instruct Q8",
        ),
    ],
    "small": [
        HfGgufSpec(
            "qwen2.5-1.5b",
            "Qwen/Qwen2.5-1.5B-Instruct-GGUF",
            "qwen2.5-1.5b-instruct-q4_k_m.gguf",
            1000,
            2500,
            "Qwen2.5 1.5B Instruct Q4_K_M",
        ),
        HfGgufSpec(
            "llama3.2-1b",
            "bartowski/Llama-3.2-1B-Instruct-GGUF",
            "Llama-3.2-1B-Instruct-Q4_K_M.gguf",
            800,
            2500,
            "Llama 3.2 1B Instruct Q4_K_M",
        ),
        HfGgufSpec(
            "qwen2.5-0.5b",
            "Qwen/Qwen2.5-0.5B-Instruct-GGUF",
            "qwen2.5-0.5b-instruct-q4_k_m.gguf",
            400,
            1200,
            "Qwen2.5 0.5B Instruct Q4_K_M",
        ),
    ],
    "standard": [
        HfGgufSpec(
            "llama3.2-3b",
            "bartowski/Llama-3.2-3B-Instruct-GGUF",
            "Llama-3.2-3B-Instruct-Q4_K_M.gguf",
            2000,
            4500,
            "Llama 3.2 3B Instruct Q4_K_M",
        ),
        HfGgufSpec(
            "qwen2.5-3b",
            "Qwen/Qwen2.5-3B-Instruct-GGUF",
            "qwen2.5-3b-instruct-q4_k_m.gguf",
            2000,
            4500,
            "Qwen2.5 3B Instruct Q4_K_M",
        ),
        HfGgufSpec(
            "qwen2.5-1.5b",
            "Qwen/Qwen2.5-1.5B-Instruct-GGUF",
            "qwen2.5-1.5b-instruct-q4_k_m.gguf",
            1000,
            2500,
            "Qwen2.5 1.5B Instruct Q4_K_M",
        ),
    ],
    "pro": [
        HfGgufSpec(
            "qwen2.5-7b",
            "Qwen/Qwen2.5-7B-Instruct-GGUF",
            "qwen2.5-7b-instruct-q4_k_m.gguf",
            4500,
            10000,
            "Qwen2.5 7B Instruct Q4_K_M — strong local agent on 10GB+ RAM",
        ),
        HfGgufSpec(
            "llama3.1-8b",
            "bartowski/Meta-Llama-3.1-8B-Instruct-GGUF",
            "Meta-Llama-3.1-8B-Instruct-Q4_K_M.gguf",
            4700,
            10000,
            "Llama 3.1 8B Instruct Q4_K_M",
        ),
        HfGgufSpec(
            "llama3.2-3b",
            "bartowski/Llama-3.2-3B-Instruct-GGUF",
            "Llama-3.2-3B-Instruct-Q4_K_M.gguf",
            2000,
            4500,
            "Llama 3.2 3B Instruct Q4_K_M (lighter)",
        ),
    ],
}


@dataclass
class LocalBootstrapResult:
    ok: bool
    provider: str
    model: str
    hardware_tier: str
    message: str
    actions: list[str]
    ollama_url: str = OLLAMA_HOST

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _progress(progress: ProgressFn | None, message: str) -> None:
    if progress:
        progress(message)
    LOGGER.info(message)


def profile_hardware() -> HardwareProfile:
    ram_mb = 0
    try:
        meminfo = Path("/proc/meminfo").read_text(encoding="utf-8")
        for line in meminfo.splitlines():
            if line.startswith("MemTotal:"):
                ram_mb = int(line.split()[1]) // 1024
                break
    except OSError:
        ram_mb = 2048

    disk_free_mb = 0
    try:
        usage = shutil.disk_usage(Path.home())
        disk_free_mb = usage.free // (1024 * 1024)
    except OSError:
        disk_free_mb = 0

    virt = "unknown"
    try:
        out = subprocess.run(
            ["systemd-detect-virt"],
            capture_output=True,
            text=True,
            timeout=3,
            check=False,
        )
        if out.returncode == 0 and out.stdout.strip():
            virt = out.stdout.strip()
    except (OSError, subprocess.SubprocessError):
        if Path("/dev/lxd/sock").exists() or "crosvm" in platform.platform().lower():
            virt = "crosvm"

    return HardwareProfile(
        arch=platform.machine() or "unknown",
        cpus=os.cpu_count() or 1,
        ram_mb=ram_mb,
        disk_free_mb=disk_free_mb,
        os_name=platform.system().lower(),
        virtualization=virt,
    )


def recommend_models(profile: HardwareProfile | None = None) -> list[tuple[str, int, int, str]]:
    profile = profile or profile_hardware()
    return list(MODEL_CATALOG.get(profile.tier, MODEL_CATALOG["nano"]))


def _http_json(url: str, payload: dict[str, Any] | None = None, timeout: float = 30.0) -> dict[str, Any]:
    data = None
    headers = {"Content-Type": "application/json"}
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(url, data=data, headers=headers, method="POST" if data else "GET")
    with urllib.request.urlopen(request, timeout=timeout) as response:
        body = response.read().decode("utf-8")
    return json.loads(body) if body else {}


def ollama_reachable(timeout: float = 2.0) -> bool:
    try:
        with urllib.request.urlopen(f"{OLLAMA_HOST}/api/tags", timeout=timeout) as response:
            return 200 <= response.status < 300
    except (urllib.error.URLError, TimeoutError, OSError):
        return False


def list_local_models() -> list[str]:
    if not ollama_reachable():
        return []
    try:
        payload = _http_json(f"{OLLAMA_HOST}/api/tags", timeout=10)
    except Exception:  # noqa: BLE001
        return []
    models = payload.get("models") or []
    names: list[str] = []
    for item in models:
        if isinstance(item, dict) and item.get("name"):
            names.append(str(item["name"]))
    return names


def find_ollama_binary() -> str | None:
    path = shutil.which("ollama")
    if path:
        return path
    candidate = BIN_DIR / "ollama"
    if candidate.exists() and os.access(candidate, os.X_OK):
        return str(candidate)
    return None


def _run(cmd: list[str], *, timeout: float | None = None, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    merged = os.environ.copy()
    if env:
        merged.update(env)
    return subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
        env=merged,
    )


def _arch_slug(arch: str) -> str:
    arch = (arch or "").lower()
    if arch in {"x86_64", "amd64"}:
        return "amd64"
    if arch in {"aarch64", "arm64"}:
        return "arm64"
    return arch or "amd64"


def _ensure_zstd(progress: ProgressFn | None = None) -> str | None:
    """Return path to zstd binary if available (optional for .tar.zst)."""
    path = shutil.which("zstd")
    if path:
        return path
    candidate = BIN_DIR / "zstd"
    if candidate.exists() and os.access(candidate, os.X_OK):
        return str(candidate)
    # Best-effort: download Debian zstd .deb and extract user-locally (no root).
    try:
        _progress(progress, "Installing user-local zstd (no root) …")
        tmp = MODELS_DIR / "zstd-debs"
        tmp.mkdir(parents=True, exist_ok=True)
        result = _run(
            ["bash", "-lc", f"cd {tmp} && apt-get download zstd libzstd1"],
            timeout=120,
        )
        if result.returncode != 0:
            return None
        extract = MODELS_DIR / "zstd-root"
        if extract.exists():
            shutil.rmtree(extract, ignore_errors=True)
        extract.mkdir(parents=True, exist_ok=True)
        for deb in tmp.glob("*.deb"):
            _run(["dpkg-deb", "-x", str(deb), str(extract)], timeout=60)
        bin_path = extract / "usr" / "bin" / "zstd"
        if not bin_path.exists():
            return None
        BIN_DIR.mkdir(parents=True, exist_ok=True)
        target = BIN_DIR / "zstd"
        shutil.copy2(bin_path, target)
        target.chmod(0o755)
        lib_dir = extract / "usr" / "lib"
        # Prefer multiarch lib path when present.
        for so in extract.rglob("libzstd.so*"):
            dest_lib = Path.home() / ".local" / "lib"
            dest_lib.mkdir(parents=True, exist_ok=True)
            shutil.copy2(so, dest_lib / so.name)
        ld = str(Path.home() / ".local" / "lib")
        os.environ["LD_LIBRARY_PATH"] = ld + ":" + os.environ.get("LD_LIBRARY_PATH", "")
        return str(target)
    except Exception as error:  # noqa: BLE001
        LOGGER.warning("Could not bootstrap zstd: %s", error)
        return None


def install_ollama(progress: ProgressFn | None = None) -> str:
    """Install Ollama into ~/.local/bin when missing. Raises RuntimeError on failure."""
    existing = find_ollama_binary()
    if existing:
        return existing

    profile = profile_hardware()
    # Full package is large; require headroom.
    if profile.disk_free_mb < 1200:
        raise RuntimeError(
            f"Not enough free disk to install Ollama "
            f"({profile.disk_free_mb}MB free; need ~1200MB free). "
            "Free space or install Ollama manually: https://ollama.com/download"
        )

    if profile.os_name != "linux":
        raise RuntimeError(
            f"Automatic Ollama install is supported on Linux only "
            f"(detected {profile.os_name}). Install from https://ollama.com/download"
        )

    BIN_DIR.mkdir(parents=True, exist_ok=True)
    MODELS_DIR.mkdir(parents=True, exist_ok=True)
    arch = _arch_slug(profile.arch)
    filename = f"ollama-linux-{arch}"

    # Prefer official CDN, then GitHub release assets (.tar.zst primary).
    candidates = [
        f"https://ollama.com/download/{filename}.tar.zst",
        f"https://github.com/ollama/ollama/releases/latest/download/{filename}.tar.zst",
        f"https://ollama.com/download/{filename}.tgz",
        f"https://github.com/ollama/ollama/releases/latest/download/{filename}.tgz",
    ]

    archive: Path | None = None
    used_url = ""
    last_error: Exception | None = None
    for url in candidates:
        suffix = ".tar.zst" if url.endswith(".tar.zst") else ".tgz"
        dest = MODELS_DIR / f"{filename}{suffix}"
        _progress(progress, f"Downloading Ollama from {url} …")
        try:
            urllib.request.urlretrieve(url, dest)
            archive = dest
            used_url = url
            break
        except Exception as error:  # noqa: BLE001
            last_error = error
            LOGGER.warning("Download failed for %s: %s", url, error)
            continue
    if archive is None:
        raise RuntimeError(f"Failed to download Ollama: {last_error}")

    _progress(progress, f"Extracting Ollama ({used_url}) …")
    extract_dir = MODELS_DIR / "ollama-extract"
    if extract_dir.exists():
        shutil.rmtree(extract_dir, ignore_errors=True)
    extract_dir.mkdir(parents=True, exist_ok=True)

    if str(archive).endswith(".tar.zst"):
        zstd = _ensure_zstd(progress)
        if not zstd:
            raise RuntimeError(
                "Ollama package is .tar.zst but zstd is not available. "
                "Install zstd (apt install zstd) and re-run /local."
            )
        # zstd -d -c archive | tar -xf - -C extract_dir
        try:
            decompress = subprocess.Popen(
                [zstd, "-d", "-c", str(archive)],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            extract = subprocess.run(
                ["tar", "-xf", "-", "-C", str(extract_dir)],
                stdin=decompress.stdout,
                capture_output=True,
                text=True,
                timeout=600,
                check=False,
            )
            if decompress.stdout:
                decompress.stdout.close()
            decompress.wait(timeout=30)
        except Exception as error:  # noqa: BLE001
            raise RuntimeError(f"Failed to extract Ollama zst archive: {error}") from error
        if extract.returncode != 0:
            raise RuntimeError(
                f"Failed to extract Ollama: {extract.stderr or extract.stdout}"
            )
    else:
        result = _run(["tar", "-xzf", str(archive), "-C", str(extract_dir)], timeout=600)
        if result.returncode != 0:
            raise RuntimeError(f"Failed to extract Ollama: {result.stderr or result.stdout}")

    binary = None
    for path in extract_dir.rglob("ollama"):
        if path.is_file() and os.access(path, os.X_OK):
            binary = path
            break
        if path.is_file() and path.name == "ollama":
            binary = path
            break
    if binary is None:
        # Some archives nest bin/ollama
        for path in extract_dir.rglob("*"):
            if path.is_file() and path.name == "ollama":
                binary = path
                break
    if binary is None:
        raise RuntimeError("Ollama binary not found inside downloaded archive")

    target = BIN_DIR / "ollama"
    shutil.copy2(binary, target)
    target.chmod(0o755)
    try:
        archive.unlink(missing_ok=True)
        shutil.rmtree(extract_dir, ignore_errors=True)
    except OSError:
        pass

    # Ensure ~/.local/bin is on PATH for this process.
    path = os.environ.get("PATH", "")
    if str(BIN_DIR) not in path.split(":"):
        os.environ["PATH"] = f"{BIN_DIR}:{path}"

    _progress(progress, f"Ollama installed at {target}")
    return str(target)


def start_ollama_server(progress: ProgressFn | None = None) -> None:
    if ollama_reachable():
        _progress(progress, "Ollama server already running")
        return

    binary = find_ollama_binary() or install_ollama(progress)
    log_path = STATE_DIR / "ollama.log"
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    _progress(progress, "Starting Ollama server …")
    host_env = OLLAMA_HOST
    for prefix in ("https://", "http://"):
        if host_env.startswith(prefix):
            host_env = host_env[len(prefix) :]
            break
    with log_path.open("a", encoding="utf-8") as log:
        subprocess.Popen(
            [binary, "serve"],
            stdout=log,
            stderr=log,
            start_new_session=True,
            env={**os.environ, "OLLAMA_HOST": host_env or "127.0.0.1:11434"},
        )

    deadline = time.time() + 60
    while time.time() < deadline:
        if ollama_reachable():
            _progress(progress, "Ollama server is ready")
            return
        time.sleep(0.5)
    raise RuntimeError(
        f"Ollama did not become ready at {OLLAMA_HOST}. See {log_path}"
    )


def pull_model(model: str, progress: ProgressFn | None = None, timeout: float = 1800.0) -> None:
    binary = find_ollama_binary()
    if not binary:
        raise RuntimeError("Ollama binary missing; cannot pull model")
    _progress(progress, f"Pulling open model `{model}` (this may take several minutes) …")
    # Stream progress via ollama CLI.
    process = subprocess.Popen(
        [binary, "pull", model],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    started = time.time()
    assert process.stdout is not None
    last_emit = 0.0
    for line in process.stdout:
        now = time.time()
        if now - last_emit > 5:
            snippet = line.strip()[:160]
            if snippet:
                _progress(progress, f"pull: {snippet}")
            last_emit = now
        if now - started > timeout:
            process.kill()
            raise RuntimeError(f"Timed out pulling model {model}")
    code = process.wait(timeout=30)
    if code != 0:
        raise RuntimeError(f"ollama pull {model} failed with exit {code}")
    _progress(progress, f"Model ready: {model}")


def choose_installable_model(profile: HardwareProfile | None = None) -> str:
    profile = profile or profile_hardware()
    existing = list_local_models()
    for name, size_mb, min_ram, _note in recommend_models(profile):
        # Prefer already-local models first.
        for local in existing:
            if local == name or local.startswith(name + ":") or name.startswith(local.split(":")[0]):
                return local
        if profile.ram_mb >= min_ram and profile.disk_free_mb >= size_mb + 200:
            return name
    # Last resort: smallest catalog entry even if tight on disk (user may have model cached).
    return recommend_models(profile)[0][0]


def persist_local_provider(model: str, *, provider: str = "ollama") -> None:
    config = load_config()
    config["provider"] = provider
    config["model"] = model
    config["timeout"] = max(int(config.get("timeout", 180)), 300)
    save_config(config)

    llm_path = CONFIG_DIR / "llm.json"
    llm: dict[str, Any] = {}
    if llm_path.exists():
        try:
            llm = json.loads(llm_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            llm = {}
    if not isinstance(llm, dict):
        llm = {}
    llm["active_provider"] = provider
    order = llm.get("fallback_order") or []
    if not isinstance(order, list):
        order = []
    # Local first when auto-promoted after cloud credit failure.
    new_order = [provider] + [x for x in order if x != provider]
    if provider != "ollama":
        new_order = [provider] + [x for x in new_order if x != "ollama"]
        if "ollama" not in new_order:
            new_order.append("ollama")
    llm["fallback_order"] = new_order
    providers = llm.setdefault("providers", {})
    if not isinstance(providers, dict):
        providers = {}
        llm["providers"] = providers
    if provider == "ollama":
        providers["ollama"] = {
            "enabled": True,
            "api_key_env": [],
            "model": model,
            "base_url": OLLAMA_HOST,
        }
    else:
        providers["local_gguf"] = {
            "enabled": True,
            "api_key_env": [],
            "model": model,
            "base_url": LLAMA_SERVER_HOST,
        }
    save_json(llm_path, llm, private=False)

    STATE_DIR.mkdir(parents=True, exist_ok=True)
    LOCAL_STATE_FILE.write_text(
        json.dumps(
            {
                "provider": provider,
                "model": model,
                "updated": time.time(),
                "hardware": asdict(profile_hardware()),
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


def _urlopen(url: str, timeout: float = 60.0):
    request = urllib.request.Request(
        url,
        headers={"User-Agent": USER_AGENT},
        method="GET",
    )
    return urllib.request.urlopen(request, timeout=timeout)


def download_file(
    urls: list[str],
    dest: Path,
    *,
    progress: ProgressFn | None = None,
    min_bytes: int = 1024,
) -> Path:
    """Download first working URL to dest (atomic replace). Supports HF + GitHub."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    partial = dest.with_suffix(dest.suffix + ".partial")
    last_error: Exception | None = None

    for url in urls:
        _progress(progress, f"Downloading {dest.name} …")
        try:
            with _urlopen(url, timeout=120) as response:
                total = response.headers.get("Content-Length")
                total_i = int(total) if total and total.isdigit() else 0
                downloaded = 0
                last_report = 0
                with partial.open("wb") as handle:
                    while True:
                        chunk = response.read(1024 * 256)
                        if not chunk:
                            break
                        handle.write(chunk)
                        downloaded += len(chunk)
                        if total_i and downloaded - last_report > 5 * 1024 * 1024:
                            pct = 100.0 * downloaded / total_i
                            _progress(
                                progress,
                                f"  {dest.name}: {downloaded // (1024 * 1024)}MB "
                                f"/ {total_i // (1024 * 1024)}MB ({pct:.0f}%)",
                            )
                            last_report = downloaded
            size = partial.stat().st_size
            if size < min_bytes:
                raise RuntimeError(f"Download too small ({size} bytes) from {url}")
            partial.replace(dest)
            _progress(progress, f"Saved {dest} ({size // (1024 * 1024)}MB)")
            return dest
        except Exception as error:  # noqa: BLE001
            last_error = error
            LOGGER.warning("Download failed for %s: %s", url, error)
            try:
                partial.unlink(missing_ok=True)
            except OSError:
                pass
            continue
    raise RuntimeError(f"All download sources failed for {dest.name}: {last_error}")


def choose_hf_gguf(profile: HardwareProfile | None = None) -> HfGgufSpec:
    profile = profile or profile_hardware()
    specs = list(HF_GGUF_CATALOG.get(profile.tier, HF_GGUF_CATALOG["nano"]))
    # Always allow falling back to smaller tiers.
    tier_order = ("pro", "standard", "small", "micro", "nano")
    try:
        start = tier_order.index(profile.tier)
    except ValueError:
        start = tier_order.index("nano")
    for tier in tier_order[start + 1 :]:
        for spec in HF_GGUF_CATALOG.get(tier, []):
            if all(spec.key != s.key for s in specs):
                specs.append(spec)

    for spec in specs:
        if profile.ram_mb >= spec.min_ram_mb and profile.disk_free_mb >= spec.size_mb + 150:
            # Prefer already-downloaded file.
            existing = GGUF_DIR / spec.filename
            if existing.exists() and existing.stat().st_size > 1024 * 1024:
                return spec
    for spec in specs:
        if profile.ram_mb >= spec.min_ram_mb and profile.disk_free_mb >= spec.size_mb + 150:
            return spec
    return specs[0]


def list_hf_gguf_for_hardware(profile: HardwareProfile | None = None) -> list[dict[str, Any]]:
    """All GGUF options that fit (or almost fit) this machine, with install status."""
    profile = profile or profile_hardware()
    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    # Present this tier first, then stronger/weaker for user choice with approval
    for tier in (profile.tier, "pro", "standard", "small", "micro", "nano"):
        for spec in HF_GGUF_CATALOG.get(tier, []):
            if spec.key in seen:
                continue
            seen.add(spec.key)
            path = GGUF_DIR / spec.filename
            installed = path.exists() and path.stat().st_size > 1024 * 1024
            fits_ram = profile.ram_mb >= spec.min_ram_mb
            fits_disk = profile.disk_free_mb >= spec.size_mb + 150
            out.append(
                {
                    "key": spec.key,
                    "filename": spec.filename,
                    "repo": spec.repo,
                    "size_mb": spec.size_mb,
                    "min_ram_mb": spec.min_ram_mb,
                    "notes": spec.notes,
                    "tier_catalog": tier,
                    "installed": installed,
                    "path": str(path) if installed else "",
                    "fits_ram": fits_ram,
                    "fits_disk": fits_disk,
                    "recommended": fits_ram and fits_disk and tier == profile.tier,
                    "requires_approval": not installed,
                }
            )
    return out


def download_hf_gguf(
    spec: HfGgufSpec | None = None,
    *,
    progress: ProgressFn | None = None,
) -> Path:
    profile = profile_hardware()
    spec = spec or choose_hf_gguf(profile)
    GGUF_DIR.mkdir(parents=True, exist_ok=True)
    dest = GGUF_DIR / spec.filename
    if dest.exists() and dest.stat().st_size > 1024 * 1024:
        _progress(progress, f"GGUF already present: {dest}")
        return dest

    # Free incomplete Ollama archives if we need space for a small HF model.
    if profile.disk_free_mb < spec.size_mb + 200:
        for junk in MODELS_DIR.glob("ollama-linux-*.tar.zst"):
            try:
                _progress(progress, f"Freeing incomplete Ollama archive {junk.name} for HF model")
                junk.unlink()
            except OSError:
                pass
        for junk in MODELS_DIR.glob("ollama-linux-*.tgz"):
            try:
                junk.unlink()
            except OSError:
                pass

    urls = spec.hf_urls() + spec.github_urls()
    _progress(
        progress,
        f"Pulling open GGUF `{spec.key}` from Hugging Face/GitHub "
        f"(~{spec.size_mb}MB, min RAM {spec.min_ram_mb}MB) — {spec.notes}",
    )
    return download_file(urls, dest, progress=progress, min_bytes=1024 * 1024)


def _latest_llama_cpp_tag() -> str:
    try:
        with _urlopen(
            "https://api.github.com/repos/ggml-org/llama.cpp/releases/latest",
            timeout=30,
        ) as response:
            data = json.loads(response.read().decode("utf-8"))
        tag = str(data.get("tag_name") or "").strip()
        if tag:
            return tag
    except Exception as error:  # noqa: BLE001
        LOGGER.warning("Could not resolve latest llama.cpp release: %s", error)
    return "b10017"


def _llama_libs_ok(runtime_dir: Path) -> bool:
    """True when runtime has shared libs llama-server needs."""
    if not runtime_dir.exists():
        return False
    sos = list(runtime_dir.rglob("libllama*.so*")) + list(
        runtime_dir.rglob("libggml*.so*")
    )
    server = runtime_dir / "llama-server"
    if not server.exists():
        # nested bin layout
        matches = list(runtime_dir.rglob("llama-server"))
        if not matches:
            return False
        server = matches[0]
    if not sos:
        # Some builds are static; check ldd for missing deps.
        probe = _run(
            ["bash", "-lc", f"ldd {server} 2>&1 | grep -c 'not found' || true"],
            timeout=10,
        )
        return "not found" not in (probe.stdout or "") or probe.stdout.strip() in {
            "0",
            "",
        }
    # Dynamic build: ensure at least one impl lib exists.
    impl = list(runtime_dir.rglob("libllama-server-impl.so*")) or list(
        runtime_dir.rglob("*impl*.so*")
    )
    return bool(impl or sos)


def _write_llama_wrapper(name: str, real_binary: Path, lib_dirs: list[Path]) -> Path:
    """Install a PATH wrapper that sets LD_LIBRARY_PATH for llama.cpp shared libs."""
    BIN_DIR.mkdir(parents=True, exist_ok=True)
    wrapper = BIN_DIR / name
    lib_path = ":".join(str(p) for p in lib_dirs if p.exists())
    content = f"""#!/usr/bin/env bash
set -euo pipefail
export LD_LIBRARY_PATH="{lib_path}${{LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}}"
exec "{real_binary}" "$@"
"""
    wrapper.write_text(content, encoding="utf-8")
    wrapper.chmod(0o755)
    return wrapper


def install_llama_cpp(
    progress: ProgressFn | None = None,
    *,
    force: bool = False,
) -> dict[str, str]:
    """Download full llama.cpp runtime (binaries + .so) from GitHub releases."""
    LLAMA_DIR.mkdir(parents=True, exist_ok=True)
    BIN_DIR.mkdir(parents=True, exist_ok=True)

    if not force and _llama_libs_ok(LLAMA_RUNTIME_DIR):
        server_real = next(LLAMA_RUNTIME_DIR.rglob("llama-server"), None)
        cli_real = next(
            (
                p
                for p in LLAMA_RUNTIME_DIR.rglob("*")
                if p.is_file() and p.name in {"llama-cli", "llama-completion", "main"}
            ),
            None,
        )
        lib_dirs = sorted({p.parent for p in LLAMA_RUNTIME_DIR.rglob("*.so*")})
        if not lib_dirs:
            lib_dirs = [LLAMA_RUNTIME_DIR]
        server_wrap = (
            _write_llama_wrapper("llama-server", server_real, lib_dirs)
            if server_real
            else BIN_DIR / "llama-server"
        )
        cli_wrap = (
            _write_llama_wrapper("llama-cli", cli_real, lib_dirs)
            if cli_real
            else BIN_DIR / "llama-cli"
        )
        return {
            "server": str(server_wrap) if server_wrap.exists() else "",
            "cli": str(cli_wrap) if cli_wrap.exists() else "",
            "runtime": str(LLAMA_RUNTIME_DIR),
        }

    profile = profile_hardware()
    tag = _latest_llama_cpp_tag()
    if profile.arch in {"aarch64", "arm64"}:
        asset = f"llama-{tag}-bin-ubuntu-arm64.tar.gz"
    else:
        asset = f"llama-{tag}-bin-ubuntu-x64.tar.gz"

    urls = [
        f"https://github.com/ggml-org/llama.cpp/releases/download/{tag}/{asset}",
        f"https://github.com/ggerganov/llama.cpp/releases/download/{tag}/{asset}",
    ]
    archive = MODELS_DIR / asset
    if not archive.exists() or archive.stat().st_size < 1024 * 100:
        download_file(urls, archive, progress=progress, min_bytes=1024 * 100)
    else:
        _progress(progress, f"Using cached {archive.name}")

    if LLAMA_RUNTIME_DIR.exists():
        shutil.rmtree(LLAMA_RUNTIME_DIR, ignore_errors=True)
    LLAMA_RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    result = _run(
        ["tar", "-xzf", str(archive), "-C", str(LLAMA_RUNTIME_DIR)],
        timeout=300,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"Failed to extract llama.cpp: {result.stderr or result.stdout}"
        )

    # Flatten single top-level directory if present.
    children = [p for p in LLAMA_RUNTIME_DIR.iterdir()]
    if len(children) == 1 and children[0].is_dir():
        nested = children[0]
        for item in nested.iterdir():
            target = LLAMA_RUNTIME_DIR / item.name
            if target.exists():
                if target.is_dir():
                    shutil.rmtree(target)
                else:
                    target.unlink()
            shutil.move(str(item), str(target))
        nested.rmdir()

    found_server = next(LLAMA_RUNTIME_DIR.rglob("llama-server"), None)
    found_cli = None
    for path in LLAMA_RUNTIME_DIR.rglob("*"):
        if path.is_file() and path.name in {"llama-cli", "llama-completion", "main"}:
            found_cli = path
            break
    if found_server is None and found_cli is None:
        raise RuntimeError(
            "llama.cpp archive did not contain llama-server or llama-cli"
        )

    for path in LLAMA_RUNTIME_DIR.rglob("*"):
        if path.is_file() and (
            path.name.startswith("llama")
            or path.name.startswith("lib")
            or path.suffix in {".so"}
            or ".so." in path.name
        ):
            try:
                path.chmod(path.stat().st_mode | 0o111)
            except OSError:
                pass

    lib_dirs = sorted({p.parent for p in LLAMA_RUNTIME_DIR.rglob("*.so*")})
    if not lib_dirs:
        lib_dirs = [LLAMA_RUNTIME_DIR]
    # Also include runtime root for rpath-less builds.
    if LLAMA_RUNTIME_DIR not in lib_dirs:
        lib_dirs.insert(0, LLAMA_RUNTIME_DIR)

    server_wrap = (
        _write_llama_wrapper("llama-server", found_server, lib_dirs)
        if found_server
        else None
    )
    cli_wrap = (
        _write_llama_wrapper("llama-cli", found_cli, lib_dirs) if found_cli else None
    )

    try:
        archive.unlink(missing_ok=True)
    except OSError:
        pass

    path = os.environ.get("PATH", "")
    if str(BIN_DIR) not in path.split(":"):
        os.environ["PATH"] = f"{BIN_DIR}:{path}"
    os.environ["LD_LIBRARY_PATH"] = (
        ":".join(str(p) for p in lib_dirs)
        + ":"
        + os.environ.get("LD_LIBRARY_PATH", "")
    )

    _progress(
        progress,
        f"llama.cpp runtime installed at {LLAMA_RUNTIME_DIR} "
        f"(libs={len(list(LLAMA_RUNTIME_DIR.rglob('*.so*')))})",
    )
    return {
        "server": str(server_wrap) if server_wrap else "",
        "cli": str(cli_wrap) if cli_wrap else "",
        "runtime": str(LLAMA_RUNTIME_DIR),
    }


def llama_server_reachable(timeout: float = 2.0) -> bool:
    """True only for a real llama-server OpenAI models endpoint (not sophyane-web)."""
    try:
        request = urllib.request.Request(
            f"{LLAMA_SERVER_HOST}/v1/models",
            headers={"User-Agent": USER_AGENT},
        )
        with urllib.request.urlopen(request, timeout=timeout) as response:
            if response.status != 200:
                return False
            body = response.read().decode("utf-8", errors="replace")
            data = json.loads(body) if body else {}
            # OpenAI-compatible: {"object":"list","data":[...]}
            if isinstance(data, dict) and (
                data.get("object") == "list" or isinstance(data.get("data"), list)
            ):
                return True
            return False
    except Exception:  # noqa: BLE001
        return False


def start_llama_server(
    gguf_path: Path,
    *,
    progress: ProgressFn | None = None,
    binaries: dict[str, str] | None = None,
) -> None:
    if llama_server_reachable():
        _progress(progress, "llama-server already running")
        return

    binaries = binaries or install_llama_cpp(progress, force=False)
    # Reinstall if previous broken thin wrappers exist.
    if not _llama_libs_ok(LLAMA_RUNTIME_DIR):
        binaries = install_llama_cpp(progress, force=True)

    server = binaries.get("server") or str(BIN_DIR / "llama-server")
    if not Path(server).exists():
        raise RuntimeError("llama-server binary missing")

    host = "127.0.0.1"
    port = 8766
    for prefix in ("https://", "http://"):
        if LLAMA_SERVER_HOST.startswith(prefix):
            rest = LLAMA_SERVER_HOST[len(prefix) :]
            if ":" in rest:
                host, port_s = rest.rsplit(":", 1)
                try:
                    port = int(port_s)
                except ValueError:
                    port = 8766
            else:
                host = rest
            break

    log_path = STATE_DIR / "llama-server.log"
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    _progress(progress, f"Starting llama-server on {host}:{port} with {gguf_path.name} …")
    threads = max(1, min(4, os.cpu_count() or 1))
    # Context budget: small models still need headroom for chat system prompts.
    # Keep conservative on very low RAM; coding planner should not run here.
    ram = profile_hardware().ram_mb
    if ram < 2000:
        ctx = 2048
    elif ram < 3500:
        ctx = 4096
    else:
        ctx = 8192
    cmd = [
        server,
        "-m",
        str(gguf_path),
        "--host",
        host,
        "--port",
        str(port),
        "-c",
        str(ctx),
        "-t",
        str(threads),
        "--parallel",
        "1",
    ]
    env = os.environ.copy()
    runtime = binaries.get("runtime") or str(LLAMA_RUNTIME_DIR)
    lib_dirs = sorted({str(p.parent) for p in Path(runtime).rglob("*.so*")})
    if runtime not in lib_dirs:
        lib_dirs.insert(0, runtime)
    env["LD_LIBRARY_PATH"] = ":".join(lib_dirs) + ":" + env.get("LD_LIBRARY_PATH", "")
    with log_path.open("a", encoding="utf-8") as log:
        subprocess.Popen(
            cmd,
            stdout=log,
            stderr=log,
            start_new_session=True,
            env=env,
        )

    deadline = time.time() + 90
    while time.time() < deadline:
        if llama_server_reachable():
            _progress(progress, "llama-server is ready")
            return
        time.sleep(0.5)
    raise RuntimeError(f"llama-server did not become ready. See {log_path}")


def persist_gguf_state(
    *,
    model_key: str,
    gguf_path: Path,
    server: str,
    cli: str,
) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    payload = {
        "provider": "local_gguf",
        "model": model_key,
        "gguf_path": str(gguf_path),
        "server": server,
        "cli": cli,
        "endpoint": LLAMA_SERVER_HOST,
        "updated": time.time(),
        "hardware": asdict(profile_hardware()),
    }
    GGUF_STATE_FILE.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    os.environ["SOPHYANE_GGUF_PATH"] = str(gguf_path)
    if cli:
        os.environ["SOPHYANE_LLAMA_CLI"] = cli
    os.environ["SOPHYANE_LLAMA_SERVER"] = LLAMA_SERVER_HOST


def ensure_hf_gguf_runtime(
    *,
    progress: ProgressFn | None = None,
    force_pull: bool = False,
) -> LocalBootstrapResult:
    """Install hardware-fit GGUF from Hugging Face + llama.cpp from GitHub."""
    actions: list[str] = []
    profile = profile_hardware()
    actions.append(f"profiled:{profile.tier}")
    try:
        spec = choose_hf_gguf(profile)
        actions.append(f"selected_gguf:{spec.key}")
        if force_pull:
            target = GGUF_DIR / spec.filename
            if target.exists():
                try:
                    target.unlink()
                except OSError:
                    pass
        gguf_path = download_hf_gguf(spec, progress=progress)
        actions.append(f"downloaded:{gguf_path.name}")

        binaries = install_llama_cpp(progress)
        actions.append("llama_cpp_installed")

        try:
            start_llama_server(gguf_path, progress=progress, binaries=binaries)
            actions.append("llama_server_ready")
            server_mode = True
        except Exception as error:  # noqa: BLE001
            _progress(
                progress,
                f"llama-server start failed ({error}); will use llama-cli one-shot mode",
            )
            actions.append(f"server_failed:{error}")
            server_mode = False
            if not binaries.get("cli"):
                raise

        persist_gguf_state(
            model_key=spec.key,
            gguf_path=gguf_path,
            server=binaries.get("server", ""),
            cli=binaries.get("cli", ""),
        )
        persist_local_provider(spec.key, provider="local_gguf")
        actions.append("config_switched_to_local_gguf")

        # Warm-up
        if server_mode:
            try:
                _http_json(
                    f"{LLAMA_SERVER_HOST}/v1/chat/completions",
                    {
                        "model": spec.key,
                        "messages": [{"role": "user", "content": "Reply with OK"}],
                        "max_tokens": 8,
                        "temperature": 0.1,
                    },
                    timeout=180,
                )
                actions.append("warmup_ok")
            except Exception as error:  # noqa: BLE001
                actions.append(f"warmup_warn:{error}")

        return LocalBootstrapResult(
            ok=True,
            provider="local_gguf",
            model=spec.key,
            hardware_tier=profile.tier,
            message=(
                f"Local open model ready via Hugging Face GGUF: {spec.key} "
                f"({gguf_path.name}), tier={profile.tier}, "
                f"backend={'llama-server' if server_mode else 'llama-cli'}. "
                "Ollama was unavailable; Sophyane will serve from this model."
            ),
            actions=actions,
            ollama_url=LLAMA_SERVER_HOST,
        )
    except Exception as error:  # noqa: BLE001
        LOGGER.exception("Hugging Face / GitHub GGUF bootstrap failed")
        return LocalBootstrapResult(
            ok=False,
            provider="local_gguf",
            model="",
            hardware_tier=profile.tier,
            message=str(error),
            actions=actions + [f"error:{error}"],
            ollama_url=LLAMA_SERVER_HOST,
        )


def ensure_ollama_runtime(
    *,
    progress: ProgressFn | None = None,
    force_pull: bool = False,
) -> LocalBootstrapResult:
    """Ollama-only bootstrap path."""
    actions: list[str] = []
    profile = profile_hardware()
    actions.append(f"profiled:{profile.tier}")

    if not find_ollama_binary():
        install_ollama(progress)
        actions.append("installed_ollama")
    else:
        actions.append("ollama_present")

    start_ollama_server(progress)
    actions.append("server_ready")

    model = choose_installable_model(profile)
    local = list_local_models()
    model_present = any(
        item == model or item.startswith(model.split(":")[0])
        for item in local
    )
    if force_pull or not model_present:
        pull_model(model, progress=progress)
        actions.append(f"pulled:{model}")
    else:
        for item in local:
            if item == model or item.startswith(model.split(":")[0]):
                model = item
                break
        actions.append(f"model_cached:{model}")

    _progress(progress, f"Warming up `{model}` …")
    try:
        _http_json(
            f"{OLLAMA_HOST}/api/generate",
            {
                "model": model,
                "prompt": "Reply with OK",
                "stream": False,
                "options": {"num_predict": 8},
            },
            timeout=180,
        )
        actions.append("warmup_ok")
    except Exception as error:  # noqa: BLE001
        _progress(progress, f"Warm-up failed ({error}); trying smaller model …")
        alts = [m for m, *_ in recommend_models(profile) if m != model]
        if not alts:
            raise
        model = alts[-1] if profile.tier == "nano" else alts[0]
        pull_model(model, progress=progress)
        _http_json(
            f"{OLLAMA_HOST}/api/generate",
            {
                "model": model,
                "prompt": "Reply with OK",
                "stream": False,
                "options": {"num_predict": 8},
            },
            timeout=180,
        )
        actions.append(f"warmup_fallback:{model}")

    persist_local_provider(model, provider="ollama")
    actions.append("config_switched_to_ollama")
    return LocalBootstrapResult(
        ok=True,
        provider="ollama",
        model=model,
        hardware_tier=profile.tier,
        message=(
            f"Local open model ready: ollama/{model} "
            f"(hardware tier {profile.tier}). Cloud credits were unavailable; "
            "Sophyane will serve from this local model."
        ),
        actions=actions,
    )


def ensure_local_open_model(
    *,
    progress: ProgressFn | None = None,
    force_pull: bool = False,
) -> LocalBootstrapResult:
    """Ensure a local open model is installed, running, and selected.

    Order:
    1. Ollama (if already installed or installable)
    2. Hugging Face GGUF + GitHub llama.cpp (always tried when Ollama fails)
    """
    actions: list[str] = []
    profile = profile_hardware()
    _progress(
        progress,
        (
            f"Hardware profile: {profile.cpus} CPUs, {profile.ram_mb}MB RAM, "
            f"{profile.disk_free_mb}MB free disk, tier={profile.tier}, "
            f"arch={profile.arch}, virt={profile.virtualization}"
        ),
    )
    actions.append(f"profiled:{profile.tier}")

    ollama_error: str | None = None
    # Prefer Ollama only when binary already exists OR there is comfortable free disk.
    try_ollama = bool(find_ollama_binary()) or profile.disk_free_mb >= 2500
    if try_ollama:
        try:
            _progress(progress, "Trying Ollama path …")
            result = ensure_ollama_runtime(progress=progress, force_pull=force_pull)
            result.actions = actions + result.actions
            STATE_DIR.mkdir(parents=True, exist_ok=True)
            LOCAL_STATE_FILE.write_text(
                json.dumps(result.to_dict(), indent=2) + "\n",
                encoding="utf-8",
            )
            return result
        except Exception as error:  # noqa: BLE001
            ollama_error = str(error)
            LOGGER.warning("Ollama path failed: %s", error)
            _progress(
                progress,
                f"Ollama unavailable ({error}). "
                "Falling back to Hugging Face GGUF + GitHub llama.cpp …",
            )
            actions.append(f"ollama_failed:{error}")
    else:
        _progress(
            progress,
            "Skipping Ollama install (tight disk / not installed); "
            "using Hugging Face GGUF + GitHub llama.cpp …",
        )
        actions.append("ollama_skipped_low_disk")

    result = ensure_hf_gguf_runtime(progress=progress, force_pull=force_pull)
    result.actions = actions + result.actions
    if not result.ok and ollama_error:
        result.message = (
            f"{result.message}\n(Ollama earlier error: {ollama_error})"
        )

    STATE_DIR.mkdir(parents=True, exist_ok=True)
    try:
        LOCAL_STATE_FILE.write_text(
            json.dumps(result.to_dict(), indent=2) + "\n",
            encoding="utf-8",
        )
    except OSError:
        pass
    return result


def is_credit_or_auth_failure(message: str) -> bool:
    text = message.lower()
    tokens = (
        "insufficient_quota",
        "quota",
        "credit",
        "billing",
        "prepayment",
        "resource_exhausted",
        "permission-denied",
        "unauthorized",
        "invalid api key",
        "incorrect api key",
        "401",
        "402",
        "403",
        "429",
        "all llm providers failed",
        "connection refused",
        "failed to establish",
    )
    return any(token in text for token in tokens)
