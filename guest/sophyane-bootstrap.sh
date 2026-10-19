#!/bin/bash
set -eu

INPUT_MOUNT=${1:-/mnt/sophyane-input}
OUTPUT_MOUNT=${2:-/mnt/sophyane-output}
export INPUT_MOUNT OUTPUT_MOUNT

python3 - <<'PY'
import json
import os
from pathlib import Path
import subprocess
import sys

input_mount = Path(os.environ["INPUT_MOUNT"]).resolve()
output_mount = Path(os.environ["OUTPUT_MOUNT"]).resolve()
manifest_path = input_mount / "task.json"
result_path = output_mount / "result.json"
temporary_path = output_mount / "result.json.tmp"
max_output = 65536
allowed = {"python", "python3", "pytest", "/usr/bin/python3", "/usr/bin/pytest"}

if result_path.exists() or not manifest_path.is_file() or not output_mount.is_dir():
    raise SystemExit("invalid or duplicate guest exchange")
payload = json.loads(manifest_path.read_text(encoding="utf-8"))
command = payload.get("command") if isinstance(payload, dict) else None
cwd_text = payload.get("cwd") if isinstance(payload, dict) else None
task_id = payload.get("task_id") if isinstance(payload, dict) else None
if (payload.get("schema_version") != 1 or not isinstance(task_id, str) or not task_id
        or not isinstance(command, list) or len(command) < 2 or len(command) > 64
        or any(not isinstance(item, str) or not item or len(item) > 4096 for item in command)
        or command[0] not in allowed or not isinstance(cwd_text, str)
        or (not cwd_text.startswith("/sophyane-input/candidate") or ".." in cwd_text.split("/"))
        or any(marker in item for item in command for marker in (";", "|", "&", "$", "`", "<", ">"))):
    raise SystemExit("manifest rejected")

cwd = Path(cwd_text)
try:
    cwd.relative_to(Path("/sophyane-input/candidate"))
except ValueError:
    raise SystemExit("working directory rejected")

try:
    completed = subprocess.run(command, cwd=cwd, shell=False, capture_output=True,
                               text=True, timeout=300, check=False)
    status = "passed" if completed.returncode == 0 else "failed"
    exit_code = completed.returncode
    stdout = completed.stdout[:max_output]
    stderr = completed.stderr[:max_output]
except subprocess.TimeoutExpired as error:
    status, exit_code = "failed", 124
    stdout = str(error.stdout or "")[:max_output]
    stderr = "guest task timeout"
except Exception as error:
    status, exit_code, stdout, stderr = "failed", 1, "", str(error)[:max_output]

result = {"schema_version": 1, "task_id": task_id, "status": status,
          "exit_code": int(exit_code), "stdout": stdout, "stderr": stderr}
temporary_path.write_text(json.dumps(result, sort_keys=True), encoding="utf-8")
os.replace(temporary_path, result_path)
PY
