"""Hardware-aware llama.cpp and GGUF runtime bootstrap.

Sophyane automatically:
1. Profiles CPU, RAM, disk and platform.
2. Selects a hardware-fit GGUF model.
3. Downloads or locates llama.cpp.
4. Starts llama-server on the local OpenAI-compatible endpoint.
5. Persists local_gguf as the selected local provider.
"""

from __future__ import annotations

import json
import logging
import os
import platform
import re
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
STATE_DIR = Path(
    os.environ.get(
        "SOPHYANE_STATE_DIR",
        Path.home() / ".local" / "state" / "sophyane",
    )
).expanduser()
LOCAL_STATE_FILE = STATE_DIR / "local_runtime.json"
GGUF_STATE_FILE = STATE_DIR / "gguf_runtime.json"
# 8766 avoids clash with sophyane-web which often binds 8765.
LLAMA_SERVER_HOST = os.environ.get(
    "SOPHYANE_LLAMA_SERVER",
    "http://127.0.0.1:8766",
).rstrip("/")
BIN_DIR = Path(
    os.environ.get(
        "SOPHYANE_NATIVE_BIN",
        Path.home() / ".local" / "bin",
    )
).expanduser()
MODELS_DIR = Path(
    os.environ.get(
        "SOPHYANE_MODELS_DIR",
        Path.home() / ".local" / "share" / "sophyane" / "models",
    )
).expanduser()
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
            "bartowski/SmolLM2-135M-Instruct-GGUF",
            "SmolLM2-135M-Instruct-Q8_0.gguf",
            145,
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
    runtime_url: str = LLAMA_SERVER_HOST

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


def persist_local_provider(model: str) -> None:
    """Persist llama.cpp/GGUF as Sophyane's only local inference provider."""
    provider = "local_gguf"

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

    llm["fallback_order"] = [
        provider,
        *[
            item
            for item in order
            if str(item).casefold() != provider
        ],
    ]

    providers = llm.setdefault("providers", {})
    if not isinstance(providers, dict):
        providers = {}
        llm["providers"] = providers

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
                "runtime_url": LLAMA_SERVER_HOST,
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

    urls = [
        *spec.hf_urls(),
        *spec.github_urls(),
    ]
    min_bytes = max(
        1024 * 1024,
        int(spec.size_mb * 1024 * 1024 * 0.50),
    )

    return download_file(
        urls,
        dest,
        progress=progress,
        min_bytes=min_bytes,
    )


LLAMA_CPP_FALLBACK_BUILD = "b10809"
LLAMA_CPP_RELEASES_API = (
    "https://api.github.com/repos/ggml-org/llama.cpp/releases"
)


def _llama_cpp_asset_name(
    profile: HardwareProfile,
    tag: str,
) -> str:
    """Return the upstream binary asset matching this platform."""

    arch = profile.arch.lower()
    os_name = profile.os_name.lower()

    if arch in {"aarch64", "arm64"}:
        platform_name = (
            "android-arm64"
            if os_name == "android"
            else "ubuntu-arm64"
        )
    elif arch in {
        "x86_64",
        "amd64",
        "x64",
    }:
        platform_name = "ubuntu-x64"
    else:
        raise RuntimeError(
            "Unsupported llama.cpp binary platform: "
            f"os={profile.os_name}, arch={profile.arch}"
        )

    return (
        f"llama-{tag}-bin-"
        f"{platform_name}.tar.gz"
    )


def _llama_cpp_release_json(
    url: str,
) -> dict[str, Any]:
    with _urlopen(
        url,
        timeout=30,
    ) as response:
        raw = response.read().decode(
            "utf-8"
        )

    data = json.loads(raw)

    if not isinstance(data, dict):
        raise RuntimeError(
            "Invalid llama.cpp release metadata"
        )

    return data


def _llama_cpp_asset_url(
    release: dict[str, Any],
    asset_name: str,
) -> str | None:
    for item in release.get(
        "assets",
        [],
    ):
        if not isinstance(item, dict):
            continue

        if str(
            item.get(
                "name",
                "",
            )
        ) != asset_name:
            continue

        url = str(
            item.get(
                "browser_download_url",
                "",
            )
        ).strip()

        return url or None

    return None


def _llama_cpp_advertised_build(
    release: dict[str, Any],
) -> str | None:
    """Resolve an upstream bNNNN binary build from stable metadata."""

    # Current stable releases publish a tiny nightly-tag.txt asset.
    for item in release.get(
        "assets",
        [],
    ):
        if not isinstance(item, dict):
            continue

        if str(
            item.get(
                "name",
                "",
            )
        ) != "nightly-tag.txt":
            continue

        url = str(
            item.get(
                "browser_download_url",
                "",
            )
        ).strip()

        if not url:
            continue

        try:
            with _urlopen(
                url,
                timeout=30,
            ) as response:
                tag = (
                    response.read()
                    .decode(
                        "utf-8"
                    )
                    .strip()
                )

            if re.fullmatch(
                r"b\d+",
                tag,
            ):
                return tag
        except Exception as error:  # noqa: BLE001
            LOGGER.warning(
                "Could not read llama.cpp nightly tag asset: %s",
                error,
            )

    # Also accept the build link advertised in the release body.
    body = str(
        release.get(
            "body",
            "",
        )
    )

    match = re.search(
        r"/releases/tag/(b\d+)",
        body,
    )

    if match:
        return match.group(1)

    return None


def _resolve_llama_cpp_binary_release(
    profile: HardwareProfile,
) -> tuple[str, str, str]:
    """Resolve a release that actually owns the required binary asset."""

    try:
        latest = _llama_cpp_release_json(
            f"{LLAMA_CPP_RELEASES_API}/latest"
        )

        latest_tag = str(
            latest.get(
                "tag_name",
                "",
            )
        ).strip()

        # Some upstream releases may directly own platform binaries.
        if latest_tag:
            latest_asset = (
                _llama_cpp_asset_name(
                    profile,
                    latest_tag,
                )
            )

            latest_url = (
                _llama_cpp_asset_url(
                    latest,
                    latest_asset,
                )
            )

            if latest_url:
                return (
                    latest_tag,
                    latest_asset,
                    latest_url,
                )

        build_tag = (
            _llama_cpp_advertised_build(
                latest
            )
        )

        if not build_tag:
            raise RuntimeError(
                "latest llama.cpp release does not advertise "
                "a binary build tag"
            )

        build = _llama_cpp_release_json(
            f"{LLAMA_CPP_RELEASES_API}"
            f"/tags/{build_tag}"
        )

        asset = _llama_cpp_asset_name(
            profile,
            build_tag,
        )

        url = _llama_cpp_asset_url(
            build,
            asset,
        )

        if not url:
            raise RuntimeError(
                f"llama.cpp build {build_tag} "
                f"does not contain required asset {asset}"
            )

        return (
            build_tag,
            asset,
            url,
        )

    except Exception as error:  # noqa: BLE001
        LOGGER.warning(
            "Could not resolve current llama.cpp binary release: %s; "
            "using pinned fallback %s",
            error,
            LLAMA_CPP_FALLBACK_BUILD,
        )

        tag = LLAMA_CPP_FALLBACK_BUILD
        asset = _llama_cpp_asset_name(
            profile,
            tag,
        )

        return (
            tag,
            asset,
            (
                "https://github.com/ggml-org/llama.cpp/"
                f"releases/download/{tag}/{asset}"
            ),
        )


def _latest_llama_cpp_tag() -> str:
    """Backward-compatible binary-build tag resolver."""

    tag, _, _ = (
        _resolve_llama_cpp_binary_release(
            profile_hardware()
        )
    )

    return tag

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


def _discover_native_llama_cpp() -> dict[str, str] | None:
    """Return a verified existing llama.cpp runtime without downloading.

    Discovery is deliberately portable. A candidate is trusted only when it
    is executable and ``--version`` succeeds. Broken PATH wrappers therefore
    cannot shadow a working Android/Termux build.
    """
    home = Path.home()

    roots = (
        LLAMA_RUNTIME_DIR,
        home
        / "llama.cpp-termux"
        / "build-termux"
        / "bin",
        home
        / "llama.cpp"
        / "build"
        / "bin",
    )

    server_candidates: list[Path] = []

    for root in roots:
        server_candidates.append(
            root / "llama-server"
        )

    path_server = shutil.which(
        "llama-server"
    )

    if path_server:
        server_candidates.append(
            Path(path_server)
        )

    seen: set[str] = set()

    for server in server_candidates:
        try:
            key = str(
                server.expanduser().resolve()
            )
        except OSError:
            key = str(
                server.expanduser()
            )

        if key in seen:
            continue

        seen.add(
            key
        )

        if not (
            server.is_file()
            and os.access(
                server,
                os.X_OK,
            )
        ):
            continue

        probe = _run(
            [
                str(server),
                "--version",
            ],
            timeout=10,
        )

        if probe.returncode != 0:
            continue

        root = server.parent

        cli = None

        cli_candidates = [
            root / "llama-cli",
            root / "llama-completion",
            root / "main",
        ]

        path_cli = shutil.which(
            "llama-cli"
        )

        if path_cli:
            cli_candidates.append(
                Path(path_cli)
            )

        cli_seen: set[str] = set()

        for candidate in cli_candidates:
            try:
                cli_key = str(
                    candidate.expanduser().resolve()
                )
            except OSError:
                cli_key = str(
                    candidate.expanduser()
                )

            if cli_key in cli_seen:
                continue

            cli_seen.add(
                cli_key
            )

            if not (
                candidate.is_file()
                and os.access(
                    candidate,
                    os.X_OK,
                )
            ):
                continue

            candidate_probe = _run(
                [
                    str(candidate),
                    "--version",
                ],
                timeout=10,
            )

            if candidate_probe.returncode == 0:
                cli = candidate
                break

        return {
            "server": str(server),
            "cli": (
                str(cli)
                if cli is not None
                else ""
            ),
            "runtime": str(root),
        }

    return None


def _verify_llama_runtime_paths(
    binaries: dict[str, str],
) -> None:
    """Require every returned llama.cpp executable to pass --version."""

    found = False

    for key in (
        "server",
        "cli",
    ):
        raw = str(
            binaries.get(
                key,
                "",
            )
        ).strip()

        if not raw:
            continue

        found = True
        path = Path(
            raw
        ).expanduser()

        if not (
            path.is_file()
            and os.access(
                path,
                os.X_OK,
            )
        ):
            raise RuntimeError(
                f"llama.cpp {key} is not executable: {path}"
            )

        probe = _run(
            [
                str(path),
                "--version",
            ],
            timeout=10,
        )

        if probe.returncode != 0:
            detail = (
                probe.stderr
                or probe.stdout
                or f"exit {probe.returncode}"
            ).strip()

            raise RuntimeError(
                f"llama.cpp {key} failed --version: {detail}"
            )

    if not found:
        raise RuntimeError(
            "llama.cpp runtime contains no usable server or CLI"
        )

def install_llama_cpp(
    progress: ProgressFn | None = None,
    *,
    force: bool = False,
) -> dict[str, str]:
    """Reuse a verified native runtime or acquire a verified binary build."""

    LLAMA_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )
    BIN_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    if not force:
        native = (
            _discover_native_llama_cpp()
        )

        if native is not None:
            result = {
                **native,
                "acquisition": "reused",
            }

            _progress(
                progress,
                "Using existing native llama.cpp runtime: "
                + result["server"],
            )

            return result

    if (
        not force
        and _llama_libs_ok(
            LLAMA_RUNTIME_DIR
        )
    ):
        server_real = next(
            LLAMA_RUNTIME_DIR.rglob(
                "llama-server"
            ),
            None,
        )

        cli_real = next(
            (
                p
                for p in LLAMA_RUNTIME_DIR.rglob(
                    "*"
                )
                if (
                    p.is_file()
                    and p.name
                    in {
                        "llama-cli",
                        "llama-completion",
                        "main",
                    }
                )
            ),
            None,
        )

        lib_dirs = sorted(
            {
                p.parent
                for p in LLAMA_RUNTIME_DIR.rglob(
                    "*.so*"
                )
            }
        )

        if not lib_dirs:
            lib_dirs = [
                LLAMA_RUNTIME_DIR
            ]

        server_wrap = (
            _write_llama_wrapper(
                "llama-server",
                server_real,
                lib_dirs,
            )
            if server_real
            else None
        )

        cli_wrap = (
            _write_llama_wrapper(
                "llama-cli",
                cli_real,
                lib_dirs,
            )
            if cli_real
            else None
        )

        cached = {
            "server": (
                str(server_wrap)
                if server_wrap
                else ""
            ),
            "cli": (
                str(cli_wrap)
                if cli_wrap
                else ""
            ),
            "runtime": str(
                LLAMA_RUNTIME_DIR
            ),
            "acquisition": "reused",
        }

        try:
            _verify_llama_runtime_paths(
                cached
            )
        except RuntimeError as error:
            _progress(
                progress,
                "Cached llama.cpp runtime is unusable; "
                f"acquiring a fresh build ({error})",
            )
        else:
            return cached

    profile = profile_hardware()

    (
        tag,
        asset,
        asset_url,
    ) = _resolve_llama_cpp_binary_release(
        profile
    )

    archive = (
        MODELS_DIR
        / asset
    )

    if (
        not archive.exists()
        or archive.stat().st_size
        < 1024 * 100
    ):
        download_file(
            [
                asset_url,
            ],
            archive,
            progress=progress,
            min_bytes=1024 * 100,
        )
    else:
        _progress(
            progress,
            f"Using cached {archive.name}",
        )

    if LLAMA_RUNTIME_DIR.exists():
        shutil.rmtree(
            LLAMA_RUNTIME_DIR,
            ignore_errors=True,
        )

    LLAMA_RUNTIME_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    extraction = _run(
        [
            "tar",
            "-xzf",
            str(archive),
            "-C",
            str(LLAMA_RUNTIME_DIR),
        ],
        timeout=300,
    )

    if extraction.returncode != 0:
        raise RuntimeError(
            "Failed to extract llama.cpp: "
            f"{extraction.stderr or extraction.stdout}"
        )

    children = [
        p
        for p in LLAMA_RUNTIME_DIR.iterdir()
    ]

    if (
        len(children) == 1
        and children[0].is_dir()
    ):
        nested = children[0]

        for item in nested.iterdir():
            target = (
                LLAMA_RUNTIME_DIR
                / item.name
            )

            if target.exists():
                if target.is_dir():
                    shutil.rmtree(
                        target
                    )
                else:
                    target.unlink()

            shutil.move(
                str(item),
                str(target),
            )

        nested.rmdir()

    found_server = next(
        LLAMA_RUNTIME_DIR.rglob(
            "llama-server"
        ),
        None,
    )

    found_cli = None

    for path in LLAMA_RUNTIME_DIR.rglob(
        "*"
    ):
        if (
            path.is_file()
            and path.name
            in {
                "llama-cli",
                "llama-completion",
                "main",
            }
        ):
            found_cli = path
            break

    if (
        found_server is None
        and found_cli is None
    ):
        raise RuntimeError(
            "llama.cpp archive did not contain "
            "llama-server or llama-cli"
        )

    for path in LLAMA_RUNTIME_DIR.rglob(
        "*"
    ):
        if (
            path.is_file()
            and (
                path.name.startswith(
                    "llama"
                )
                or path.name.startswith(
                    "lib"
                )
                or path.suffix == ".so"
                or ".so." in path.name
            )
        ):
            try:
                path.chmod(
                    path.stat().st_mode
                    | 0o111
                )
            except OSError:
                pass

    lib_dirs = sorted(
        {
            p.parent
            for p in LLAMA_RUNTIME_DIR.rglob(
                "*.so*"
            )
        }
    )

    if not lib_dirs:
        lib_dirs = [
            LLAMA_RUNTIME_DIR
        ]

    if (
        LLAMA_RUNTIME_DIR
        not in lib_dirs
    ):
        lib_dirs.insert(
            0,
            LLAMA_RUNTIME_DIR,
        )

    server_wrap = (
        _write_llama_wrapper(
            "llama-server",
            found_server,
            lib_dirs,
        )
        if found_server
        else None
    )

    cli_wrap = (
        _write_llama_wrapper(
            "llama-cli",
            found_cli,
            lib_dirs,
        )
        if found_cli
        else None
    )

    binaries = {
        "server": (
            str(server_wrap)
            if server_wrap
            else ""
        ),
        "cli": (
            str(cli_wrap)
            if cli_wrap
            else ""
        ),
        "runtime": str(
            LLAMA_RUNTIME_DIR
        ),
        "acquisition": "installed",
    }

    # Do not claim readiness until the actual returned wrappers execute.
    _verify_llama_runtime_paths(
        binaries
    )

    try:
        archive.unlink(
            missing_ok=True
        )
    except OSError:
        pass

    path = os.environ.get(
        "PATH",
        "",
    )

    if (
        str(BIN_DIR)
        not in path.split(":")
    ):
        os.environ["PATH"] = (
            f"{BIN_DIR}:{path}"
        )

    os.environ[
        "LD_LIBRARY_PATH"
    ] = (
        ":".join(
            str(p)
            for p in lib_dirs
        )
        + ":"
        + os.environ.get(
            "LD_LIBRARY_PATH",
            "",
        )
    )

    _progress(
        progress,
        "llama.cpp runtime installed "
        f"from {tag} at {LLAMA_RUNTIME_DIR} "
        "(libs="
        f"{len(list(LLAMA_RUNTIME_DIR.rglob('*.so*')))}"
        ")",
    )

    return binaries

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
    """Delegate persistent llama-server ownership to local_server.

    SOPHYANE_LLAMA_SINGLE_OWNER_V1

    local_runtime may discover models and binaries, but only
    sophyane.local_server may create the persistent server process.
    """
    gguf_path = (
        Path(
            gguf_path
        )
        .expanduser()
        .resolve()
    )

    if not gguf_path.is_file():
        raise RuntimeError(
            f"GGUF model file "
            f"missing: {gguf_path}"
        )

    try:
        state = json.loads(
            GGUF_STATE_FILE.read_text(
                encoding="utf-8"
            )
        )
    except (
        OSError,
        json.JSONDecodeError,
    ):
        state = {}

    if not isinstance(
        state,
        dict,
    ):
        state = {}

    state[
        "gguf_path"
    ] = str(
        gguf_path
    )

    state[
        "endpoint"
    ] = LLAMA_SERVER_HOST

    if binaries:

        server = str(
            binaries.get(
                "server"
            )
            or ""
        ).strip()

        cli = str(
            binaries.get(
                "cli"
            )
            or ""
        ).strip()

        if server:
            state[
                "server"
            ] = server

        if cli:
            state[
                "cli"
            ] = cli

    explicit_server = str(
        os.environ.get(
            "SOPHYANE_LLAMA_SERVER_BIN",
            "",
        )
        or ""
    ).strip()

    if explicit_server:
        state[
            "server"
        ] = explicit_server

    STATE_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    GGUF_STATE_FILE.write_text(
        json.dumps(
            state,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )

    from sophyane.local_server import (
        ensure_server_background,
        failure_detail,
        wait_until_ready,
    )

    ok, message = (
        ensure_server_background()
    )

    if not ok:
        raise RuntimeError(
            message
        )

    timeout = max(
        20.0,
        float(
            os.environ.get(
                "SOPHYANE_LLAMA_READY_TIMEOUT",
                "120",
            )
        ),
    )

    if not wait_until_ready(
        timeout=timeout
    ):
        raise RuntimeError(
            "llama-server did not "
            "become inference-ready: "
            + (
                failure_detail()
                or message
            )
        )

    _progress(
        progress,
        "llama-server is ready",
    )



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

        if gguf_path is None:
            return LocalBootstrapResult(
                ok=False,
                provider="local_gguf",
                model=spec.key,
                hardware_tier=profile.tier,
                message=(
                    "GGUF download or discovery returned no model path. "
                    "No local runtime was started."
                ),
                actions=actions + ["gguf_path_missing"],
                runtime_url=LLAMA_SERVER_HOST,
            )

        gguf_path = Path(gguf_path).expanduser().resolve()

        if not gguf_path.is_file():
            return LocalBootstrapResult(
                ok=False,
                provider="local_gguf",
                model=spec.key,
                hardware_tier=profile.tier,
                message=f"GGUF model file is missing: {gguf_path}",
                actions=actions + ["gguf_file_missing"],
                runtime_url=LLAMA_SERVER_HOST,
            )

        actions.append(f"downloaded:{gguf_path.name}")

        binaries = install_llama_cpp(progress)
        acquisition = binaries.get(
            "acquisition",
            "installed",
        )
        actions.append(
            "llama_cpp_reused"
            if acquisition == "reused"
            else "llama_cpp_installed"
        )

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
        persist_local_provider(spec.key)
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
                "Sophyane will serve this model through llama.cpp."
            ),
            actions=actions,
            runtime_url=LLAMA_SERVER_HOST,
        )
    except Exception as error:  # noqa: BLE001
        LOGGER.exception("llama.cpp/GGUF bootstrap failed")
        return LocalBootstrapResult(
            ok=False,
            provider="local_gguf",
            model="",
            hardware_tier=profile.tier,
            message=str(error),
            actions=actions + [f"error:{error}"],
            runtime_url=LLAMA_SERVER_HOST,
        )


def ensure_local_open_model(
    *,
    progress: ProgressFn | None = None,
    force_pull: bool = False,
) -> LocalBootstrapResult:
    """Ensure Sophyane's llama.cpp/GGUF runtime is ready and selected."""
    profile = profile_hardware()

    _progress(
        progress,
        (
            f"Hardware profile: {profile.cpus} CPUs, "
            f"{profile.ram_mb}MB RAM, "
            f"{profile.disk_free_mb}MB free disk, "
            f"tier={profile.tier}, arch={profile.arch}, "
            f"virt={profile.virtualization}"
        ),
    )

    result = ensure_hf_gguf_runtime(
        progress=progress,
        force_pull=force_pull,
    )

    STATE_DIR.mkdir(parents=True, exist_ok=True)
    LOCAL_STATE_FILE.write_text(
        json.dumps(result.to_dict(), indent=2) + "\n",
        encoding="utf-8",
    )

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
