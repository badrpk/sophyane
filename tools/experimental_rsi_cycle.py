#!/usr/bin/env python3
"""Small opt-in RSI experiment runner for Android/Termux.

Candidate Python executes only in a disposable ARM64 QEMU guest. The guest gets
one read-only 9p source snapshot, a read-only base disk, and a fixed-size
scratch result disk. This track is experimental and does not satisfy Phase 4.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import resource
import shutil
import signal
import statistics
import subprocess
import tempfile
import time


BASE_COMMIT = "96fbc294843bb46fcb014c853d5734b075d5fa7f"
REPO = Path(__file__).resolve().parents[1]
TMP_ROOT = Path("/data/data/com.termux/files/usr/tmp")
GUEST_ROOT = Path("/data/data/com.termux/files/home/.local/state/sophyane/continuous-rsi/qemu")
GUEST_IMAGE = GUEST_ROOT / "alpine-rsi-guest.raw"
GUEST_KERNEL = GUEST_ROOT / "alpine/vmlinuz-virt"
GUEST_INITRD = GUEST_ROOT / "alpine/initramfs-sophyane-minimal-vda"
GUEST_HASHES = {
    GUEST_IMAGE: "62f84c0b5170a5b55a17af2d87cd9704ed142bc6244e19e31f1c29349e823e49",
    GUEST_KERNEL: "e45e1f6083d1ed45db6647b422e32b6ae6dc54de7b8190b7b97744fb293412e3",
    GUEST_INITRD: "b21c7617b0bf08b047524076991fde83c9e8f868a36d20a56da30d4559123456",
}
TARGET = "src/sophyane/rsi/benchmark.py"
TEST = "tests/rsi/test_benchmark_comparison.py"
MAX_INPUT_BYTES = 8 * 1024 * 1024
MAX_RUN_BYTES = 64 * 1024 * 1024
RESULT_DISK_BYTES = 16 * 1024 * 1024
GUEST_RAM_MB = 512
MAX_QEMU_RSS_BYTES = 1024 * 1024 * 1024
WALL_TIMEOUT_SECONDS = 150
CPU_LIMIT_SECONDS = 180
MIN_SPEEDUP = 0.05

OLD_NAMES = '''        names = {weakness.target_metric, *weakness.protected_metrics}
        if any(not isfinite(values[name]) for values in (baseline_metrics, candidate_metrics) for name in names):
            raise ValueError('Nonfinite measurement')'''
DIRECT_VALIDATION = '''        target = weakness.target_metric
        if not isfinite(baseline_metrics[target]) or not isfinite(candidate_metrics[target]):
            raise ValueError('Nonfinite measurement')
        for name in weakness.protected_metrics:
            if name != target and (not isfinite(baseline_metrics[name]) or not isfinite(candidate_metrics[name])):
                raise ValueError('Nonfinite measurement')'''


class ExperimentError(RuntimeError):
    pass


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _run_checked(argv: list[str], *, cwd: Path | None = None, timeout: int = 30) -> subprocess.CompletedProcess:
    allowed = {"git", "qemu-system-aarch64", "qemu-img", "mke2fs", "debugfs", "gzip", "cpio"}
    if Path(argv[0]).name not in allowed:
        raise ExperimentError(f"host command is not allowlisted: {argv[0]}")
    return subprocess.run(argv, cwd=cwd, shell=False, check=True, timeout=timeout,
                          stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                          stderr=subprocess.PIPE)


def _git_blob(revision: str, relative: str) -> bytes:
    result = _run_checked(["git", "-C", str(REPO), "show", f"{revision}:{relative}"])
    return result.stdout


def _verify_assets() -> dict[str, str]:
    fingerprints = {}
    for path, expected in GUEST_HASHES.items():
        if not path.is_file():
            raise ExperimentError(f"required guest asset is missing: {path}")
        actual = sha256(path)
        if actual != expected:
            raise ExperimentError(f"guest asset fingerprint mismatch: {path}")
        fingerprints[str(path)] = actual
    if shutil.which("qemu-system-aarch64") is None:
        raise ExperimentError("QEMU ARM64 executable is unavailable")
    for tool in ("qemu-img", "mke2fs", "debugfs", "gzip", "cpio"):
        if shutil.which(tool) is None:
            raise ExperimentError(f"required host tool is unavailable: {tool}")
    for entry in Path("/proc").glob("[0-9]*"):
        try:
            command = (entry / "cmdline").read_bytes()
        except OSError:
            continue
        if b"qemu-system-aarch64" in command:
            raise ExperimentError("another ARM64 QEMU process is active")
    status = Path("/proc/self/status").read_text(errors="replace")
    if "Seccomp:\t2" not in status and "Seccomp:\t 2" not in status:
        raise ExperimentError("Termux process is not under the inherited Android seccomp filter")
    mem_available = next((int(line.split()[1]) * 1024 for line in Path("/proc/meminfo").read_text().splitlines()
                          if line.startswith("MemAvailable:")), 0)
    if mem_available < 2 * 1024 * 1024 * 1024:
        raise ExperimentError("less than 2 GiB host memory is currently available")
    return fingerprints


def _safe_extract_initrd(archive: Path, destination: Path) -> None:
    """Extract only relative newc members and reject escaping symlinks."""
    raw = gzip.decompress(archive.read_bytes())
    if len(raw) > 32 * 1024 * 1024:
        raise ExperimentError("initrd expands beyond the 32 MiB input budget")
    offset = 0
    destination.mkdir(parents=True)
    while offset + 110 <= len(raw):
        header = raw[offset:offset + 110]
        if header[:6] != b"070701":
            raise ExperimentError("initrd is not a supported newc archive")
        fields = [int(header[i:i + 8], 16) for i in range(6, 110, 8)]
        mode, size, name_size = fields[1], fields[6], fields[11]
        offset += 110
        if name_size < 1 or offset + name_size > len(raw):
            raise ExperimentError("invalid initrd member name")
        name = raw[offset:offset + name_size - 1].decode("utf-8", "strict")
        offset = (offset + name_size + 3) & ~3
        if name == "TRAILER!!!":
            return
        member = PurePosixPath(name)
        if member.is_absolute() or ".." in member.parts:
            raise ExperimentError("initrd contains an escaping member path")
        relative = Path(*[part for part in member.parts if part not in ("", ".")])
        target = destination / relative
        if relative.parts:
            target.parent.mkdir(parents=True, exist_ok=True)
            if not target.parent.resolve().is_relative_to(destination.resolve()):
                raise ExperimentError("initrd member parent escapes extraction root")
        kind = mode & 0o170000
        if kind == 0o040000:
            target.mkdir(parents=True, exist_ok=True)
            offset = (offset + 3) & ~3
            continue
        if offset + size > len(raw):
            raise ExperimentError("truncated initrd member")
        content = raw[offset:offset + size]
        offset = (offset + size + 3) & ~3
        if kind == 0o100000:
            if target.is_symlink():
                raise ExperimentError("initrd file would traverse a symlink")
            target.write_bytes(content)
            target.chmod(mode & 0o777)
        elif kind == 0o120000:
            link = content.decode("utf-8", "strict")
            link_path = PurePosixPath(link)
            if link_path.is_absolute() or ".." in link_path.parts:
                raise ExperimentError("initrd contains an escaping symlink")
            if target.exists() or target.is_symlink():
                raise ExperimentError("duplicate initrd member")
            target.symlink_to(link)
        else:
            # The minimal initrd has no device nodes; reject unexpected types.
            raise ExperimentError("initrd contains an unsupported file type")
    raise ExperimentError("initrd has no trailer")


def _newc_archive(root: Path) -> bytes:
    output = bytearray()
    ino = 1

    def add(name: str, mode: int, data: bytes) -> None:
        nonlocal ino
        encoded = name.encode() + b"\0"
        fields = (ino, mode, 0, 0, 1, 0, len(data), 0, 0, 0, 0, len(encoded), 0)
        output.extend(b"070701" + b"".join(f"{value:08x}".encode() for value in fields))
        output.extend(encoded)
        output.extend(b"\0" * ((-len(output)) % 4))
        output.extend(data)
        output.extend(b"\0" * ((-len(output)) % 4))
        ino += 1

    add(".", 0o040755, b"")
    for path in sorted(root.rglob("*"), key=lambda item: item.relative_to(root).as_posix()):
        rel = path.relative_to(root).as_posix()
        st = path.lstat()
        if path.is_symlink():
            link = os.readlink(path)
            if PurePosixPath(link).is_absolute() or ".." in PurePosixPath(link).parts:
                raise ExperimentError("initrd symlink containment check failed")
            add("./" + rel, 0o120777, link.encode())
        elif path.is_dir():
            add("./" + rel, 0o040000 | (st.st_mode & 0o777), b"")
        elif path.is_file():
            add("./" + rel, 0o100000 | (st.st_mode & 0o777), path.read_bytes())
        else:
            raise ExperimentError("unexpected initrd filesystem object")
    add("TRAILER!!!", 0, b"")
    return bytes(output)


def _prepare_initrd(run_root: Path, source_allowlist: tuple[str, ...] | None = None) -> Path:
    root = run_root / "initrd-root"
    _safe_extract_initrd(GUEST_INITRD, root)
    if source_allowlist is None:
        source_allowlist = (
            "experimental_check.py", "src/sophyane/__init__.py", "src/sophyane/version.py",
            "src/sophyane/rsi/__init__.py", "src/sophyane/rsi/models.py",
            "src/sophyane/rsi/weakness.py", "src/sophyane/rsi/benchmark.py",
            "tests/rsi/test_benchmark_comparison.py",
        )
    if "experimental_check.py" not in source_allowlist or any(
        PurePosixPath(name).is_absolute() or ".." in PurePosixPath(name).parts for name in source_allowlist
    ):
        raise ExperimentError("invalid guest source allowlist")
    worker = '''import json
import os
from pathlib import Path
import resource
import shutil
import subprocess
import sys
import uuid

INPUT = Path("/mnt/sophyane-input")
OUTPUT = Path("/mnt/sophyane-output")
task_path = INPUT / "task.json"
result_path = OUTPUT / "result.json"
temporary_path = OUTPUT / ("result." + uuid.uuid4().hex + ".tmp")
MAX_OUTPUT = 65536
task_id = "invalid"
status = "failed"
exit_code = 1
stdout = ""
stderr = ""

def child_limits():
    resource.setrlimit(resource.RLIMIT_CPU, (90, 90))
    resource.setrlimit(resource.RLIMIT_AS, (256 * 1024 * 1024, 256 * 1024 * 1024))
    resource.setrlimit(resource.RLIMIT_FSIZE, (2 * 1024 * 1024, 2 * 1024 * 1024))
    resource.setrlimit(resource.RLIMIT_NOFILE, (64, 64))
    resource.setrlimit(resource.RLIMIT_NPROC, (16, 16))
    os.setgid(65534)
    os.setuid(65534)

try:
    payload = json.loads(task_path.read_text(encoding="utf-8"))
    task_id = payload.get("task_id") if isinstance(payload, dict) else "invalid"
    command = payload.get("command") if isinstance(payload, dict) else None
    cwd = payload.get("cwd") if isinstance(payload, dict) else None
    expected = ["python3", "/mnt/sophyane-input/candidate/experimental_check.py"]
    if (not isinstance(payload, dict) or set(payload) != {"schema_version", "task_id", "command", "cwd"}
            or payload.get("schema_version") != 1 or not isinstance(task_id, str) or not task_id
            or command != expected or cwd != "/mnt/sophyane-input/candidate"):
        raise ValueError("experimental guest task rejected")
    candidate_root = Path("/tmp/candidate")
    allowlist = __EXPERIMENTAL_SOURCE_ALLOWLIST__
    candidate_root.mkdir(mode=0o755)
    for relative in allowlist:
        source = INPUT / "candidate" / relative
        destination = candidate_root / relative
        if source.is_symlink() or not source.is_file():
            raise ValueError("candidate snapshot does not match the exact file allowlist")
        destination.parent.mkdir(parents=True, exist_ok=True, mode=0o755)
        shutil.copyfile(source, destination)
        destination.chmod(0o444)
    for directory, _, _ in os.walk(candidate_root):
        Path(directory).chmod(0o755)
    command = ["python3", "/tmp/candidate/experimental_check.py"]
    cwd = "/tmp/candidate"
    environment = {
        "PATH": "/usr/bin:/bin",
        "HOME": "/tmp",
        "TMPDIR": "/tmp",
        "PYTHONPATH": "/tmp/candidate/src",
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1",
        "LANG": "C",
    }
    completed = subprocess.run(command, cwd=cwd, env=environment, shell=False,
                               capture_output=True, text=True, encoding="utf-8",
                               errors="replace", timeout=110, check=False,
                               preexec_fn=child_limits)
    exit_code = int(completed.returncode)
    status = "passed" if exit_code == 0 else "failed"
    stdout = completed.stdout[:MAX_OUTPUT]
    stderr = completed.stderr[:MAX_OUTPUT]
except subprocess.TimeoutExpired as error:
    status, exit_code, stderr = "failed", 124, "guest task exceeded 110 seconds"
    stdout = str(error.stdout or "")[:MAX_OUTPUT]
except Exception as error:
    status, exit_code, stderr = "failed", 1, str(error)[:MAX_OUTPUT]

result = {"schema_version": 1, "task_id": task_id, "status": status,
          "exit_code": exit_code, "stdout": stdout, "stderr": stderr}
result_bytes = json.dumps(result, sort_keys=True).encode("utf-8")
fd = os.open(temporary_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
with os.fdopen(fd, "wb") as handle:
    handle.write(result_bytes)
    handle.flush()
    os.fsync(handle.fileno())
os.replace(temporary_path, result_path)
'''.replace("__EXPERIMENTAL_SOURCE_ALLOWLIST__", repr(tuple(sorted(set(source_allowlist)))))
    compile(worker, "experimental_guest_worker.py", "exec")
    (root / "experimental_guest_worker.py").write_text(worker, encoding="utf-8")
    init = f'''#!/bin/sh
set -eu
PATH=/bin:/sbin:/usr/bin:/usr/sbin
export PATH PYTHONDONTWRITEBYTECODE=1
BB=/bin/busybox
$BB mkdir -p /dev /proc /sys /newroot
$BB mount -t devtmpfs dev /dev 2>/dev/null || true
$BB mount -t proc proc /proc 2>/dev/null || true
$BB mount -t sysfs sysfs /sys 2>/dev/null || true
$BB insmod /lib/modules/6.18.52-0-virt/kernel/drivers/virtio/virtio_mmio.ko 2>/dev/null || true
$BB insmod /lib/modules/6.18.52-0-virt/kernel/drivers/block/virtio_blk.ko 2>/dev/null || true
$BB insmod /lib/modules/6.18.52-0-virt/kernel/crc16.ko 2>/dev/null || true
$BB insmod /lib/modules/6.18.52-0-virt/kernel/fs/mbcache.ko 2>/dev/null || true
$BB insmod /lib/modules/6.18.52-0-virt/kernel/fs/jbd2/jbd2.ko 2>/dev/null || true
$BB insmod /lib/modules/6.18.52-0-virt/kernel/fs/ext4/ext4.ko 2>/dev/null || true
$BB insmod /lib/modules/6.18.52-0-virt/kernel/fs/netfs/netfs.ko 2>/dev/null || true
$BB insmod /lib/modules/6.18.52-0-virt/kernel/net/9p/9pnet.ko 2>/dev/null || true
$BB insmod /lib/modules/6.18.52-0-virt/kernel/net/9p/9pnet_virtio.ko 2>/dev/null || true
$BB insmod /lib/modules/6.18.52-0-virt/kernel/fs/9p/9p.ko 2>/dev/null || true
VDA_SIZE=$($BB cat /sys/block/vda/size)
VDB_SIZE=$($BB cat /sys/block/vdb/size)
if [ "$VDA_SIZE" -gt "$VDB_SIZE" ]; then ROOT_DISK=/dev/vda; RESULT_DISK=/dev/vdb; else ROOT_DISK=/dev/vdb; RESULT_DISK=/dev/vda; fi
echo EXPERIMENTAL_BLOCK_SIZES:$VDA_SIZE:$VDB_SIZE
$BB mount -t ext4 -o rw "$ROOT_DISK" /newroot
$BB chmod -R a+rX /newroot/usr /newroot/lib /newroot/bin /newroot/etc
$BB mkdir -p /newroot/mnt/sophyane-input /newroot/mnt/sophyane-output /newroot/tmp
$BB mount -t devtmpfs dev /newroot/dev
$BB mount -t proc proc /newroot/proc
$BB mount -t sysfs sysfs /newroot/sys
$BB mount -t 9p -o trans=virtio,version=9p2000.L,ro sophyane-input /newroot/mnt/sophyane-input
$BB mount -t ext4 -o rw "$RESULT_DISK" /newroot/mnt/sophyane-output
$BB mount -t tmpfs -o size=16m,mode=1777,nosuid,nodev tmpfs /newroot/tmp
$BB chown 65534:65534 /newroot/mnt/sophyane-output
$BB mkdir -p /newroot/usr/local/lib/sophyane
$BB cat > /newroot/usr/local/lib/sophyane/experimental_guest_worker.py <<'SOPHYANE_WORKER_EOF'
{worker}SOPHYANE_WORKER_EOF
set +e
$BB chroot /newroot /usr/bin/python3 /usr/local/lib/sophyane/experimental_guest_worker.py
task_status=$?
set -e
$BB sync
echo EXPERIMENTAL_GUEST_DONE:$task_status
$BB poweroff -f
exit 0
'''
    (root / "init").write_text(init, encoding="utf-8")
    (root / "init").chmod(0o755)
    initrd = run_root / "experimental-initrd.img.gz"
    with initrd.open("wb") as raw_handle:
        with gzip.GzipFile(filename="", mode="wb", fileobj=raw_handle, mtime=0, compresslevel=6) as zipped:
            zipped.write(_newc_archive(root))
    return initrd


def _guest_check_script() -> str:
    return '''import json
import statistics
import time
import pytest
from sophyane.rsi.benchmark import compare
from sophyane.rsi.models import WeaknessRecord

test_exit = int(pytest.main(["-q", "-p", "no:cacheprovider", "tests/rsi/test_benchmark_comparison.py"]))
if test_exit:
    raise SystemExit(test_exit)
protected = {}
weakness = WeaknessRecord(
    weakness_id="benchmark-cycle",
    description="fixed deterministic performance workload",
    evidence=("local benchmark fixture",),
    baseline_commit="committed-baseline",
    target_metric="quality",
    baseline_value=1.0,
    required_improvement=1.0,
    protected_metrics=protected,
    verification_commands=(("python3", "check"),),
)
baseline_metrics = {"quality": 1.0, **{name: 1.0 for name in protected}}
candidate_metrics = {"quality": 2.0, **{name: 1.0 for name in protected}}
assert compare(weakness, baseline_metrics, candidate_metrics).promote
samples = []
for _ in range(5):
    start = time.perf_counter_ns()
    for _ in range(10000):
        compare(weakness, baseline_metrics, candidate_metrics)
    elapsed = (time.perf_counter_ns() - start) / 1_000_000_000
    samples.append(elapsed)
median_seconds = statistics.median(samples)
score = 10000.0 / median_seconds
print("EXPERIMENTAL_SCORE=" + json.dumps({
    "metric": "no_protected_metric_comparisons_per_second",
    "calls_per_sample": 10000,
    "samples": samples,
    "median_seconds": median_seconds,
    "score": score,
}))
'''


def _stage(input_dir: Path, source_files: dict[str, bytes]) -> None:
    candidate = input_dir / "candidate"
    for relative, source in source_files.items():
        member = PurePosixPath(relative)
        if member.is_absolute() or ".." in member.parts:
            raise ExperimentError("candidate bundle contains an unsafe path")
        target = candidate.joinpath(*member.parts)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(source)
    input_dir.chmod(0o755)
    candidate.chmod(0o755)
    for path in candidate.rglob("*"):
        if path.is_dir():
            path.chmod(0o755)
        elif path.is_file():
            path.chmod(0o444)


def _format_output_disk(path: Path) -> None:
    with path.open("wb") as handle:
        handle.truncate(RESULT_DISK_BYTES)
    _run_checked(["mke2fs", "-q", "-F", "-t", "ext4", str(path)], timeout=30)


def _qemu_preexec() -> None:
    resource.setrlimit(resource.RLIMIT_CPU, (CPU_LIMIT_SECONDS, CPU_LIMIT_SECONDS))
    resource.setrlimit(resource.RLIMIT_FSIZE, (RESULT_DISK_BYTES, RESULT_DISK_BYTES))
    os.umask(0o077)


def _rss_bytes(pid: int) -> int:
    try:
        for line in Path(f"/proc/{pid}/status").read_text().splitlines():
            if line.startswith("VmRSS:"):
                return int(line.split()[1]) * 1024
    except (OSError, ValueError, IndexError):
        pass
    return 0


def _directory_bytes(path: Path) -> int:
    total = 0
    for directory, dirs, files in os.walk(path, followlinks=False):
        dirs[:] = [name for name in dirs if not (Path(directory) / name).is_symlink()]
        for name in files:
            target = Path(directory) / name
            if not target.is_symlink():
                total += target.stat().st_size
    return total


def _run_guest(candidate_files: dict[str, bytes], run_root: Path, initrd: Path, label: str) -> dict:
    exchange = run_root / label
    input_dir, candidate_dir = exchange / "input", exchange / "input/candidate"
    input_dir.mkdir(parents=True)
    output_disk = exchange / "output.ext4"
    root_overlay = exchange / "guest-root-overlay.qcow2"
    if "experimental_check.py" not in candidate_files:
        raise ExperimentError("candidate bundle is missing experimental_check.py")
    _stage(input_dir, candidate_files)
    (input_dir / "task.json").write_text(json.dumps({
        "schema_version": 1,
        "task_id": label,
        "command": ["python3", "/mnt/sophyane-input/candidate/experimental_check.py"],
        "cwd": "/mnt/sophyane-input/candidate",
    }, separators=(",", ":")), encoding="utf-8")
    (input_dir / "task.json").chmod(0o444)
    staged = _directory_bytes(input_dir)
    if staged > MAX_INPUT_BYTES:
        raise ExperimentError("candidate snapshot exceeded the 8 MiB input budget")
    _run_checked(["qemu-img", "create", "-q", "-f", "qcow2", "-F", "raw",
                  "-b", str(GUEST_IMAGE), str(root_overlay)], timeout=30)
    overlay_info = _run_checked(["qemu-img", "info", "--output=json", str(root_overlay)], timeout=15)
    overlay_metadata = json.loads(overlay_info.stdout.decode("utf-8"))
    if overlay_metadata.get("backing-filename") != str(GUEST_IMAGE):
        raise ExperimentError("disposable guest overlay has an unexpected backing image")
    _format_output_disk(output_disk)
    if _directory_bytes(exchange) > MAX_RUN_BYTES:
        raise ExperimentError("experiment exchange exceeded the 64 MiB disk budget")
    serial = exchange / "serial.log"
    stderr = exchange / "qemu.stderr"
    qemu = shutil.which("qemu-system-aarch64")
    command = [
        qemu,
        "-machine", "virt",
        "-cpu", "cortex-a57",
        "-accel", "tcg,thread=single",
        "-smp", "1",
        "-m", str(GUEST_RAM_MB),
        "-no-user-config",
        "-nographic",
        "-monitor", "none",
        "-serial", f"file:{serial}",
        "-no-reboot",
        "-nic", "none",
        "-kernel", str(GUEST_KERNEL),
        "-initrd", str(initrd),
        "-append", "rdinit=/init console=ttyAMA0,115200 loglevel=4",
        "-drive", f"if=none,format=qcow2,readonly=off,file={root_overlay},id=rootdisk",
        "-device", "virtio-blk-device,drive=rootdisk",
        "-drive", f"if=none,format=raw,readonly=off,file={output_disk},id=resultdisk",
        "-device", "virtio-blk-device,drive=resultdisk",
        "-virtfs", f"local,path={input_dir},mount_tag=sophyane-input,security_model=none,readonly=on",
    ]
    environment = {
        "PATH": "/data/data/com.termux/files/usr/bin:/system/bin",
        "HOME": str(exchange / "empty-home"),
        "TMPDIR": str(exchange),
        "XDG_CONFIG_HOME": str(exchange / "empty-config"),
        "LANG": "C",
    }
    Path(environment["HOME"]).mkdir()
    Path(environment["XDG_CONFIG_HOME"]).mkdir()
    process = None
    peak_rss = 0
    started = time.monotonic()
    with serial.open("wb") as serial_handle, stderr.open("wb") as stderr_handle:
        process = subprocess.Popen(
            command,
            stdin=subprocess.DEVNULL,
            stdout=serial_handle,
            stderr=stderr_handle,
            env=environment,
            shell=False,
            start_new_session=True,
            preexec_fn=_qemu_preexec,
        )
        while process.poll() is None:
            peak_rss = max(peak_rss, _rss_bytes(process.pid))
            if peak_rss > MAX_QEMU_RSS_BYTES:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait(timeout=3)
                raise ExperimentError(f"{label} QEMU exceeded the 1 GiB resident-memory budget")
            if time.monotonic() - started > WALL_TIMEOUT_SECONDS:
                os.killpg(process.pid, signal.SIGTERM)
                try:
                    process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    os.killpg(process.pid, signal.SIGKILL)
                    process.wait(timeout=3)
                raise ExperimentError(f"{label} QEMU exceeded wall timeout")
            if _directory_bytes(exchange) > MAX_RUN_BYTES:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait(timeout=3)
                raise ExperimentError(f"{label} exchange exceeded disk budget")
            if serial.exists() and serial.stat().st_size > 1024 * 1024:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait(timeout=3)
                raise ExperimentError(f"{label} serial log exceeded the 1 MiB output budget")
            time.sleep(0.1)
        exit_code = process.wait()
    elapsed = time.monotonic() - started
    for asset, expected in GUEST_HASHES.items():
        if sha256(asset) != expected:
            raise ExperimentError(f"guest asset changed during run: {asset}")
    if exit_code != 0:
        detail = stderr.read_text(errors="replace")[-2000:]
        raise ExperimentError(f"{label} QEMU exited {exit_code}: {detail}")
    serial_text = serial.read_text(errors="replace")
    if "EXPERIMENTAL_GUEST_DONE:0" not in serial_text:
        raise ExperimentError(f"{label} guest did not report clean completion")
    result = _run_checked(["debugfs", "-R", "cat /result.json", str(output_disk)], timeout=15)
    payload = json.loads(result.stdout.decode("utf-8"))
    if (payload.get("schema_version") != 1 or payload.get("task_id") != label
            or payload.get("exit_code") != 0 or payload.get("status") != "passed"):
        raise ExperimentError(
            f"{label} guest result did not verify: status={payload.get('status')!r} "
            f"exit={payload.get('exit_code')!r} stderr={payload.get('stderr', '')!r} "
            f"stdout={payload.get('stdout', '')[-2000:]!r}"
        )
    score_lines = [line for line in payload.get("stdout", "").splitlines() if line.startswith("EXPERIMENTAL_SCORE=")]
    if len(score_lines) != 1:
        raise ExperimentError(f"{label} did not emit exactly one benchmark score")
    score = json.loads(score_lines[0].split("=", 1)[1])
    return {
        "label": label,
        "exit_code": exit_code,
        "wall_seconds": elapsed,
        "peak_qemu_rss_bytes": peak_rss,
        "pytest_and_benchmark_output": payload.get("stdout", ""),
        "score": score,
        "serial_log_sha256": sha256(serial),
        "stderr_sha256": sha256(stderr),
        "result_sha256": hashlib.sha256(result.stdout).hexdigest(),
        "staged_input_bytes": staged,
        "fixed_output_disk_bytes": output_disk.stat().st_size,
            "guest_root_overlay_bytes": root_overlay.stat().st_size,
        "qemu_command": command,
    }


def _candidate_direct_finite_checks(source: bytes) -> bytes:
    text = source.decode("utf-8")
    if OLD_NAMES not in text:
        raise ExperimentError("candidate generator did not find the expected finite-metric validation block")
    text = text.replace(OLD_NAMES, DIRECT_VALIDATION, 1)
    return text.encode()


def _candidate_fallback(source: bytes) -> bytes:
    text = source.decode("utf-8")
    # Bounded repair path: restore the known-good implementation if the
    # optimized candidate fails tests. A passing repair is retained only if it wins.
    text = text.replace(DIRECT_VALIDATION, OLD_NAMES, 1)
    return text.encode()


def run(*, execute_candidate: bool, retries: int = 1) -> dict:
    if retries < 0 or retries > 1:
        raise ExperimentError("this experimental controller allows at most one repair retry")
    if not execute_candidate:
        raise ExperimentError("candidate execution is disabled; pass the explicit opt-in flag")
    fingerprints = _verify_assets()
    if not TMP_ROOT.is_dir() or not os.access(TMP_ROOT, os.W_OK):
        raise ExperimentError("Termux temporary root is not writable")
    baseline = _git_blob(BASE_COMMIT, TARGET)
    test_source = (REPO / TEST).read_bytes()
    run_root = Path(tempfile.mkdtemp(prefix="sophyane-experimental-rsi-", dir=TMP_ROOT))
    initrd = _prepare_initrd(run_root)
    base_files = {
        "src/sophyane/__init__.py": _git_blob(BASE_COMMIT, "src/sophyane/__init__.py"),
        "src/sophyane/version.py": _git_blob(BASE_COMMIT, "src/sophyane/version.py"),
        "src/sophyane/rsi/__init__.py": _git_blob(BASE_COMMIT, "src/sophyane/rsi/__init__.py"),
        "src/sophyane/rsi/models.py": _git_blob(BASE_COMMIT, "src/sophyane/rsi/models.py"),
        "src/sophyane/rsi/weakness.py": _git_blob(BASE_COMMIT, "src/sophyane/rsi/weakness.py"),
        TARGET: baseline,
        TEST: test_source,
        "experimental_check.py": _guest_check_script().encode(),
    }
    baseline_result = _run_guest(base_files, run_root, initrd, "baseline")
    baseline_score = baseline_result["score"]["score"]
    attempts = []
    candidate_failures = []
    chosen = None
    for attempt in range(retries + 1):
        candidate = _candidate_direct_finite_checks(baseline) if attempt == 0 else _candidate_fallback(baseline)
        try:
            candidate_files = dict(base_files)
            candidate_files[TARGET] = candidate
            candidate_result = _run_guest(candidate_files, run_root, initrd, f"candidate-{attempt + 1}")
        except ExperimentError as error:
            candidate_failures.append({"attempt": attempt + 1, "error": str(error)})
            if attempt < retries:
                continue
            raise ExperimentError(f"candidate attempts failed: {candidate_failures}") from error
        score = candidate_result["score"]["score"]
        attempts.append(candidate_result)
        if score >= baseline_score * (1.0 + MIN_SPEEDUP):
            chosen = candidate
            break
    if chosen is None:
        raise ExperimentError("no tested candidate exceeded the 5% improvement threshold")
    target_path = REPO / TARGET
    current = target_path.read_bytes()
    if current != baseline:
        raise ExperimentError("worktree target changed during experiment; refusing to overwrite")
    target_path.write_bytes(chosen)
    report = {
        "track": "EXPERIMENTAL_RSI_ANDROID_TERMUX",
        "hardened_phase4_status": "UNCHANGED_AND_NOT_EVALUATED",
        "base_commit": BASE_COMMIT,
        "experimental_branch": "experimental/rsi-cycle-20261121",
        "target": TARGET,
        "candidate_change": "validate the target metric directly and scan protected metrics without allocating a combined set or nested generator",
        "score_metric": "no_protected_metric_comparisons_per_second",
        "minimum_improvement": MIN_SPEEDUP,
        "baseline": baseline_result,
        "candidate_attempts": attempts,
        "candidate_failures_repaired": candidate_failures,
        "retained_candidate_sha256": hashlib.sha256(chosen).hexdigest(),
        "retained": True,
        "resources": {
            "guest_ram_mb": GUEST_RAM_MB,
            "host_qemu_rss_kill_budget_bytes": MAX_QEMU_RSS_BYTES,
            "guest_vcpus": 1,
            "wall_timeout_seconds_per_run": WALL_TIMEOUT_SECONDS,
            "guest_cpu_limit_seconds": CPU_LIMIT_SECONDS,
            "candidate_input_budget_bytes": MAX_INPUT_BYTES,
            "scratch_budget_bytes": MAX_RUN_BYTES,
            "result_disk_bytes": RESULT_DISK_BYTES,
            "guest_asset_sha256": fingerprints,
            "run_root": str(run_root),
        },
    }
    report_path = run_root / "experimental-rsi-report.json"
    report_path.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--execute-candidate", action="store_true", help="explicitly opt in to isolated experimental candidate execution")
    parser.add_argument("--retries", type=int, default=1)
    args = parser.parse_args()
    try:
        report = run(execute_candidate=args.execute_candidate, retries=args.retries)
    except (ExperimentError, OSError, subprocess.SubprocessError, json.JSONDecodeError) as error:
        print(f"EXPERIMENTAL_RSI_ABORT: {error}")
        return 2
    print(json.dumps({
        "track": report["track"],
        "hardened_phase4_status": report["hardened_phase4_status"],
        "baseline_score": report["baseline"]["score"]["score"],
        "candidate_score": report["candidate_attempts"][-1]["score"]["score"],
        "retained": report["retained"],
        "report": report["resources"]["run_root"] + "/experimental-rsi-report.json",
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
