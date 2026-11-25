#!/usr/bin/env python3
"""Trusted GitHub-hosted qualification harness for python_jsonl_v1 candidates.

This file must be checked out from the protected workflow SHA. It never imports
or executes candidate Python in the runner process; the isolated container sees
only one read-only candidate file and one JSON request at a time.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import selectors
import shutil
import subprocess
import sys
import tempfile
import time
import uuid
from pathlib import Path

from sophyane.ssee.remote.github_hosted import (
    IMAGE,
    WORKFLOW_PATH,
    build_candidate_command,
)

MAX_CANDIDATE_BYTES = 64 * 1024
MAX_OUTPUT_BYTES = 64 * 1024
CASE_TIMEOUT_SECONDS = 5
DOCKER_TIMEOUT_SECONDS = 30
_SHA1 = re.compile(r"^[0-9a-f]{40}$")
_FIXTURES = {"candidate", "pass", "fail", "timeout", "network"}
_TEST_CASES = (
    ({"operation": "sum", "values": [1, 2, 3]}, {"value": 6}),
    ({"operation": "sum", "values": []}, {"value": 0}),
    ({"operation": "sum", "values": [-5, 8, 13]}, {"value": 16}),
    ({"operation": "sum", "values": [2147483648, -2147483647]}, {"value": 1}),
)


class QualificationInfrastructureError(RuntimeError):
    pass


def candidate_path_for(root: Path, fixture: str, trusted_root: Path | None = None) -> Path:
    if fixture not in _FIXTURES:
        raise ValueError("unsupported qualification fixture")
    if fixture == "candidate":
        path = root / "ssee_candidate.py"
        source_root = root
    else:
        source_root = trusted_root or root
        path = source_root / f"qualification_fixtures/{fixture}.py"
    if path.is_symlink() or not path.is_file():
        raise QualificationInfrastructureError("candidate entrypoint is missing or not a regular file")
    resolved_root = source_root.resolve(strict=True)
    resolved = path.resolve(strict=True)
    try:
        resolved.relative_to(resolved_root)
    except ValueError:
        raise QualificationInfrastructureError("candidate entrypoint escapes checkout") from None
    if resolved.stat().st_size > MAX_CANDIDATE_BYTES:
        raise QualificationInfrastructureError("candidate entrypoint exceeds 64 KiB")
    return resolved


def _docker_json(args, *, timeout=DOCKER_TIMEOUT_SECONDS):
    try:
        result = subprocess.run(args, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                stderr=subprocess.DEVNULL, timeout=timeout, check=False,
                                env={"PATH": "/usr/bin:/bin", "LC_ALL": "C"})
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise QualificationInfrastructureError(f"trusted Docker probe failed: {type(exc).__name__}") from None
    if result.returncode != 0 or len(result.stdout) > 128 * 1024:
        raise QualificationInfrastructureError("trusted Docker probe returned failure or oversized data")
    try:
        return json.loads(result.stdout.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise QualificationInfrastructureError("trusted Docker probe returned invalid JSON") from None


def ensure_image_pinned(docker="docker"):
    # Pull occurs before candidate execution and has a fixed digest, no candidate input.
    try:
        result = subprocess.run([docker, "pull", IMAGE], stdin=subprocess.DEVNULL,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                timeout=180, check=False,
                                env={"PATH": "/usr/bin:/bin", "LC_ALL": "C"})
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise QualificationInfrastructureError(f"pinned image pull failed: {type(exc).__name__}") from None
    if result.returncode != 0 or len(result.stdout) > 128 * 1024 or len(result.stderr) > 128 * 1024:
        raise QualificationInfrastructureError("pinned candidate image could not be fetched")
    image_info = _docker_json([docker, "image", "inspect", IMAGE])
    if not isinstance(image_info, list) or len(image_info) != 1 or image_info[0].get("RepoTags") is None:
        raise QualificationInfrastructureError("pinned candidate image inspect failed")
    repo_digests = image_info[0].get("RepoDigests", [])
    digest = IMAGE.split("@", 1)[1]
    if not any(item.endswith("@" + digest) for item in repo_digests):
        raise QualificationInfrastructureError("Docker image digest does not match trusted pin")


def verify_network_none(docker="docker"):
    # Independent probe, not a claim made by candidate code.
    probe = (
        "import socket,sys\n"
        "try:\n socket.create_connection(('1.1.1.1',443),timeout=2)\n"
        "except OSError:\n print('SSEE_NETWORK_BLOCKED');sys.exit(0)\n"
        "print('SSEE_NETWORK_AVAILABLE');sys.exit(23)\n"
    )
    args = [docker, "run", "--rm", "--network=none", "--read-only", "--memory=268435456",
            "--cpus=0.5", "--pids-limit=32", "--cap-drop=ALL",
            "--security-opt=no-new-privileges", "--security-opt=seccomp=default",
            "--user=65532:65532", "--tmpfs", "/tmp:rw,noexec,nosuid,nodev,size=16777216",
            "--entrypoint", "python3", IMAGE, "-I", "-c", probe]
    try:
        result = subprocess.run(args, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                stderr=subprocess.DEVNULL, timeout=8, check=False,
                                env={"PATH": "/usr/bin:/bin", "LC_ALL": "C"})
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise QualificationInfrastructureError(f"network isolation probe failed: {type(exc).__name__}") from None
    if result.returncode != 0 or result.stdout.strip() != b"SSEE_NETWORK_BLOCKED":
        raise QualificationInfrastructureError("Docker network-none negative probe did not confirm egress denial")


def _inspect_container(docker: str, name: str, candidate_file: Path):
    value = _docker_json([docker, "inspect", name])
    if not isinstance(value, list) or len(value) != 1:
        raise QualificationInfrastructureError("candidate container inspect returned an ambiguous result")
    item = value[0]
    host = item.get("HostConfig") or {}
    config = item.get("Config") or {}
    mounts = item.get("Mounts") or []
    candidate_mounts = [mount for mount in mounts if mount.get("Destination") == "/candidate.py"]
    tmp_mounts = [mount for mount in mounts if mount.get("Destination") == "/tmp"]
    env = config.get("Env") or []
    env_names = [entry.partition("=")[0] for entry in env]
    forbidden_names = ("GITHUB_", "GH_", "SSH_", "SOPHYANE_", "CODEX_", "AWS_", "TOKEN", "SECRET", "KEY")
    if any(name.startswith(prefix) or prefix in name for name in env_names for prefix in forbidden_names):
        raise QualificationInfrastructureError("candidate container environment includes a credential-like name")
    expected_bind = str(candidate_file)
    if (host.get("NetworkMode") != "none" or host.get("ReadonlyRootfs") is not True
            or host.get("Memory") != 268435456 or host.get("NanoCpus") != 500000000
            or host.get("PidsLimit") != 32 or host.get("CapDrop") != ["ALL"]
            or config.get("User") != "65532:65532"
            or config.get("Image") != IMAGE
            or "no-new-privileges:true" not in (host.get("SecurityOpt") or [])
            or "seccomp=default" not in (host.get("SecurityOpt") or [])
            or len(candidate_mounts) != 1 or candidate_mounts[0].get("RW") is not False
            or candidate_mounts[0].get("Source") != expected_bind
            or len(tmp_mounts) != 1 or tmp_mounts[0].get("Type") != "tmpfs"
            or any(mount.get("Destination") not in {"/candidate.py", "/tmp"} for mount in mounts)):
        raise QualificationInfrastructureError("candidate container did not enforce the fixed isolation profile")
    host_mounts = [mount.get("Source") for mount in mounts if mount.get("Type") == "bind"]
    if host_mounts != [expected_bind]:
        raise QualificationInfrastructureError("candidate container has an unexpected host bind mount")
    return {
        "network_mode": host["NetworkMode"], "readonly_rootfs": host["ReadonlyRootfs"],
        "memory_bytes": host["Memory"], "cpu_nanos": host["NanoCpus"],
        "pids_limit": host["PidsLimit"], "cap_drop": host["CapDrop"],
        "no_new_privileges": True, "candidate_mounts_readonly": True,
        "candidate_env_allowlist_only": True, "credential_names_observed": [],
        "host_mounts_observed": [], "container_image": config["Image"],
    }


def _kill_container(docker, name):
    subprocess.run([docker, "kill", name], stdin=subprocess.DEVNULL,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                   timeout=5, check=False, env={"PATH": "/usr/bin:/bin", "LC_ALL": "C"})


def _remove_container(docker, name):
    subprocess.run([docker, "rm", "-f", name], stdin=subprocess.DEVNULL,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                   timeout=5, check=False, env={"PATH": "/usr/bin:/bin", "LC_ALL": "C"})


def _run_one(candidate_file: Path, request: dict, expected: dict, *, docker="docker", timeout=CASE_TIMEOUT_SECONDS):
    name = "ssee-" + uuid.uuid4().hex[:24]
    command = build_candidate_command(docker=docker, image=IMAGE,
                                      candidate_file=str(candidate_file), container_name=name)
    try:
        process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                   stderr=subprocess.PIPE, bufsize=0,
                                   env={"PATH": "/usr/bin:/bin", "LC_ALL": "C"})
    except OSError as exc:
        raise QualificationInfrastructureError(f"Docker candidate launch failed: {type(exc).__name__}") from None
    payload = json.dumps(request, separators=(",", ":"), ensure_ascii=True).encode() + b"\n"
    try:
        try:
            process.stdin.write(payload)
        except (BrokenPipeError, OSError):
            # A candidate that exits before consuming a request is an ordinary
            # candidate failure; trusted isolation inspection still follows.
            pass
        process.stdin.close()
        selector = selectors.DefaultSelector()
        selector.register(process.stdout, selectors.EVENT_READ, "stdout")
        selector.register(process.stderr, selectors.EVENT_READ, "stderr")
        chunks = {"stdout": bytearray(), "stderr": bytearray()}
        deadline = time.monotonic() + timeout
        timed_out = False
        overflow = False
        while selector.get_map():
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                timed_out = True
                _kill_container(docker, name)
                break
            events = selector.select(min(remaining, 0.2))
            if not events and process.poll() is not None:
                # Drain EOF notifications from both pipe descriptors.
                events = [(key, selectors.EVENT_READ) for key in list(selector.get_map().values())]
            for key, _ in events:
                try:
                    data = os.read(key.fileobj.fileno(), 4096)
                except OSError:
                    data = b""
                if not data:
                    selector.unregister(key.fileobj)
                    continue
                chunks[key.data].extend(data)
                if sum(map(len, chunks.values())) > MAX_OUTPUT_BYTES:
                    overflow = True
                    _kill_container(docker, name)
                    break
            if overflow:
                break
        try:
            return_code = process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)
            return_code = -9
        selector.close()
        isolation = _inspect_container(docker, name, candidate_file)
        if timed_out:
            status, passed = "timed_out", False
        elif overflow:
            status, passed = "output_limit", False
        elif return_code != 0:
            status, passed = "process_failed", False
        else:
            raw = bytes(chunks["stdout"])
            try:
                lines = raw.decode("utf-8").splitlines()
                actual = json.loads(lines[0]) if len(lines) == 1 else None
            except (UnicodeDecodeError, json.JSONDecodeError, IndexError):
                actual = None
            passed = actual == expected
            status = "passed" if passed else "test_failed"
        isolation.update({"container_cleanup_verified": False,
                          "candidate_output_sha256": hashlib.sha256(chunks["stdout"]).hexdigest()})
        return {"status": status, "passed": passed, "timed_out": timed_out,
                "output_sha256": isolation.pop("candidate_output_sha256"),
                "isolation": isolation, "container_name": name}
    finally:
        try:
            process.stdin.close()
        except OSError:
            pass
        _remove_container(docker, name)


def _verify_removed(docker, name):
    try:
        result = subprocess.run([docker, "ps", "-a", "--filter", f"name=^/{name}$",
                                 "--format", "{{.Names}}"], stdin=subprocess.DEVNULL,
                                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                timeout=5, check=False,
                                env={"PATH": "/usr/bin:/bin", "LC_ALL": "C"})
    except (OSError, subprocess.TimeoutExpired):
        return False
    return result.returncode == 0 and result.stdout == b""


def _atomic_report(path: Path, report: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = json.dumps(report, sort_keys=True, separators=(",", ":"),
                     ensure_ascii=True, allow_nan=False).encode() + b"\n"
    if len(raw) > 128 * 1024:
        raise QualificationInfrastructureError("qualification report exceeds size limit")
    temp = path.with_suffix(path.suffix + ".tmp")
    with temp.open("wb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    temp.replace(path)
    digest_path = path.with_name("qualification-report.sha256")
    digest_temp = digest_path.with_suffix(digest_path.suffix + ".tmp")
    with digest_temp.open("w", encoding="ascii") as stream:
        stream.write(hashlib.sha256(raw).hexdigest() + "\n")
        stream.flush()
        os.fsync(stream.fileno())
    digest_temp.replace(digest_path)


def execute_qualification(*, candidate_root: Path, candidate_sha: str,
                          workflow_sha: str, run_id: int, request_id: str,
                          fixture: str, output_dir: Path, trusted_root: Path | None = None,
                          docker="docker"):
    if not _SHA1.fullmatch(candidate_sha) or not _SHA1.fullmatch(workflow_sha):
        raise ValueError("candidate and workflow must be full commit SHAs")
    if fixture not in _FIXTURES:
        raise ValueError("unsupported qualification fixture")
    candidate_file = candidate_path_for(candidate_root, fixture, trusted_root)
    candidate_digest = hashlib.sha256(candidate_file.read_bytes()).hexdigest()
    # Pull and isolation test happen before any candidate source is run.
    ensure_image_pinned(docker)
    verify_network_none(docker)
    tests = {"passed": 0, "failed": 0, "timed_out": 0}
    records = []
    aggregate_isolation = None
    with tempfile.TemporaryDirectory(prefix="ssee-candidate-") as scratch_name:
        staged = Path(scratch_name) / "candidate.py"
        shutil.copyfile(candidate_file, staged)
        staged.chmod(0o444)
        for inputs, expected in _TEST_CASES:
            # Expected outputs stay in this trusted host-side harness and are
            # never mounted or sent to the candidate process.
            result = _run_one(staged, {"input": inputs}, expected, docker=docker)
            if aggregate_isolation is None:
                aggregate_isolation = result["isolation"]
            elif any(result["isolation"].get(key) != aggregate_isolation.get(key)
                     for key in ("network_mode", "readonly_rootfs", "memory_bytes", "cpu_nanos", "pids_limit", "cap_drop", "container_image")):
                raise QualificationInfrastructureError("container isolation profile changed during qualification")
            if not _verify_removed(docker, result["container_name"]):
                raise QualificationInfrastructureError("candidate container cleanup could not be verified")
            result.pop("container_name")
            result["isolation"]["container_cleanup_verified"] = True
            records.append({key: value for key, value in result.items() if key != "isolation"})
            if result["timed_out"]:
                tests["timed_out"] += 1
            elif result["passed"]:
                tests["passed"] += 1
            else:
                tests["failed"] += 1
    if aggregate_isolation is None:
        raise QualificationInfrastructureError("trusted test suite contained no cases")
    status = "accepted" if tests["passed"] == len(_TEST_CASES) else "rejected"
    expected_counts = {
        "pass": {"passed": 4, "failed": 0, "timed_out": 0},
        "fail": {"passed": 0, "failed": 4, "timed_out": 0},
        "timeout": {"passed": 0, "failed": 0, "timed_out": 4},
        "network": {"passed": 0, "failed": 4, "timed_out": 0},
    }.get(fixture)
    expected_fixture_observed = expected_counts is None or tests == expected_counts
    report = {
        "schema_version": 1,
        "request_id": request_id,
        "candidate_sha": candidate_sha,
        "workflow_sha": workflow_sha,
        "workflow_path": WORKFLOW_PATH,
        "run_id": run_id,
        "execution_class": "python_jsonl_v1",
        "fixture": fixture,
        "candidate_status": status,
        "expected_fixture_outcome_observed": expected_fixture_observed,
        "tests": tests,
        "candidate_file_sha256": candidate_digest,
        "case_evidence": records,
        "isolation": {
            **aggregate_isolation,
            "runner_kind": "github-hosted-ephemeral-vm",
            "runner_image": os.environ.get("ImageOS", "ubuntu-24.04") + ":" + os.environ.get("ImageVersion", "unreported"),
            "network_probe_blocked": True,
        },
    }
    _atomic_report(output_dir / "qualification-report.json", report)
    if not expected_fixture_observed:
        raise QualificationInfrastructureError("fixture did not produce its independently expected result")
    return report


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--candidate-root", required=True, type=Path)
    parser.add_argument("--trusted-root", required=True, type=Path)
    parser.add_argument("--candidate-sha", required=True)
    parser.add_argument("--workflow-sha", required=True)
    parser.add_argument("--run-id", required=True, type=int)
    parser.add_argument("--request-id", required=True)
    parser.add_argument("--fixture", required=True, choices=sorted(_FIXTURES))
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--docker", default="docker")
    args = parser.parse_args(argv)
    try:
        execute_qualification(candidate_root=args.candidate_root,
                              candidate_sha=args.candidate_sha,
                              workflow_sha=args.workflow_sha, run_id=args.run_id,
                              request_id=args.request_id, fixture=args.fixture,
                              output_dir=args.output_dir, trusted_root=args.trusted_root,
                              docker=args.docker)
    except Exception as exc:
        # Never print candidate output or environment details in trusted logs.
        print(json.dumps({"error": type(exc).__name__}, sort_keys=True), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
