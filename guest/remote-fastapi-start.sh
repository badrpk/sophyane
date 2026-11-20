#!/bin/sh
set -eu

INPUT=/mnt/sophyane-input
OUTPUT=/mnt/sophyane-output
READINESS="$OUTPUT/qemu-readiness.json"
mkdir -p "$INPUT" "$OUTPUT"

write_stage() {
  python3 - "$READINESS" "$1" "$2" "$3" <<'PY'
import json, os, sys, tempfile
from datetime import datetime, timezone
path, name, state, diagnostic = sys.argv[1:]
try:
    with open(path, encoding="utf-8") as source:
        report = json.load(source)
except (OSError, ValueError):
    report = {"schema": "sophyane.qemu-readiness.v1", "stages": {}}
report.setdefault("stages", {})[name] = {
    "state": state,
    "diagnostic": diagnostic[-12000:],
    "timestamp": datetime.now(timezone.utc).isoformat(),
}
fd, temporary = tempfile.mkstemp(prefix=".qemu-readiness-", dir=os.path.dirname(path))
with os.fdopen(fd, "w", encoding="utf-8") as target:
    json.dump(report, target, sort_keys=True)
    target.write("\n")
    target.flush()
    os.fsync(target.fileno())
os.replace(temporary, path)
PY
}

mount_output() {
  mountpoint -q "$OUTPUT" || timeout 30 mount -t 9p -o trans=virtio,version=9p2000.L sophyane-output "$OUTPUT"
}

mount_option_present() {
  case ",$2," in
    *,"$1",*) return 0 ;;
    *) return 1 ;;
  esac
}

if ! mount_output; then
  echo "failed to mount writable output 9p share" >&2
  exit 71
fi
if ! OUTPUT_MOUNT_DETAILS=$(findmnt -n -o FSTYPE,OPTIONS --target "$OUTPUT"); then
  write_stage guest_output_mount failed "findmnt could not inspect output mount"
  exit 71
fi
OUTPUT_FSTYPE=${OUTPUT_MOUNT_DETAILS%% *}
OUTPUT_OPTIONS=${OUTPUT_MOUNT_DETAILS#* }
if [ "$OUTPUT_FSTYPE" != "9p" ] || ! mount_option_present rw "$OUTPUT_OPTIONS" || mount_option_present ro "$OUTPUT_OPTIONS"; then
  write_stage guest_output_mount failed "output 9p mount is not read-write: $OUTPUT_MOUNT_DETAILS"
  exit 71
fi
write_stage guest_output_mount passed "writable 9p output share confirmed: $OUTPUT_MOUNT_DETAILS"

if ! mountpoint -q "$INPUT"; then
  if ! INPUT_OUT=$(timeout 30 mount -t 9p -o trans=virtio,version=9p2000.L,ro sophyane "$INPUT" 2>&1); then
    write_stage guest_source_mount failed "$INPUT_OUT"
    exit 72
  fi
fi
if ! INPUT_MOUNT_DETAILS=$(findmnt -n -o FSTYPE,OPTIONS --target "$INPUT"); then
  write_stage guest_source_mount failed "findmnt could not inspect source mount"
  exit 72
fi
INPUT_FSTYPE=${INPUT_MOUNT_DETAILS%% *}
INPUT_OPTIONS=${INPUT_MOUNT_DETAILS#* }
if [ "$INPUT_FSTYPE" != "9p" ] || ! mount_option_present ro "$INPUT_OPTIONS" || mount_option_present rw "$INPUT_OPTIONS"; then
  write_stage guest_source_mount failed "source 9p mount is not read-only: $INPUT_MOUNT_DETAILS"
  exit 72
fi
write_stage guest_source_mount passed "read-only 9p source share confirmed: $INPUT_MOUNT_DETAILS"

. "$OUTPUT/runner.env"
PROJECT="$INPUT"

install_runner_ssh_key() {
  if ! getent passwd sophyane >/dev/null 2>&1; then
    write_stage guest_ssh_service failed "required sophyane account is missing"
    return 1
  fi
  if ! usermod --shell /bin/bash sophyane; then
    write_stage guest_ssh_service failed "could not set command-capable shell for sophyane"
    return 1
  fi
  case "$SOPHYANE_RUNNER_SSH_PUBLIC_KEY" in
    ssh-ed25519\ *) ;;
    *) write_stage guest_ssh_service failed "runner public key is empty or is not an Ed25519 key"; return 1 ;;
  esac
  mkdir -p /home/sophyane/.ssh
  KEY_TMP=/home/sophyane/.ssh/authorized_keys.new
  (umask 077; printf '%s\n' "$SOPHYANE_RUNNER_SSH_PUBLIC_KEY" > "$KEY_TMP")
  chown -R sophyane:sophyane /home/sophyane/.ssh
  chmod 0700 /home/sophyane/.ssh
  chmod 0600 "$KEY_TMP"
  mv -f "$KEY_TMP" /home/sophyane/.ssh/authorized_keys
  if ! sshd -t; then
    write_stage guest_ssh_service failed "sshd configuration validation failed"
    return 1
  fi
  if ! systemctl start ssh; then
    write_stage guest_ssh_service failed "systemctl start ssh failed"
    return 1
  fi
  if ! systemctl is-active --quiet ssh; then
    write_stage guest_ssh_service failed "sshd is not active"
    return 1
  fi
  write_stage guest_ssh_service passed "sshd active with per-job key"
}

if ! install_runner_ssh_key; then
  exit 73
fi

write_stage guest_cloud_init starting "waiting for cloud-init completion"
if ! CLOUD_INIT_OUT=$(timeout 600 cloud-init status --wait --long 2>&1); then
  write_stage guest_cloud_init failed "$CLOUD_INIT_OUT"
  exit 74
fi
CLOUD_INIT_JSON=$(cloud-init status --format=json 2>&1) || {
  write_stage guest_cloud_init failed "$CLOUD_INIT_JSON"
  exit 74
}
if ! printf '%s' "$CLOUD_INIT_JSON" | python3 -c 'import json,sys; x=json.load(sys.stdin); sys.exit(0 if x.get("status")=="done" and not x.get("errors") else 1)'; then
  write_stage guest_cloud_init failed "$CLOUD_INIT_OUT $CLOUD_INIT_JSON"
  exit 74
fi
write_stage guest_cloud_init passed "$CLOUD_INIT_OUT"

write_stage guest_postgres starting "waiting for PostgreSQL inventory readiness"
READY=0
for _ in $(seq 1 180); do
  if pg_isready -U sophyane -d inventory >/dev/null 2>&1; then
    READY=1
    break
  fi
  sleep 1
done
if [ "$READY" -ne 1 ]; then
  write_stage guest_postgres failed "PostgreSQL did not become ready within 180 seconds"
  exit 75
fi
write_stage guest_postgres passed "pg_isready succeeded for inventory"

VENV=/opt/sophyane-venv
if [ ! -x "$VENV/bin/python" ]; then
  write_stage guest_venv starting "creating bounded application virtualenv"
  if ! VENV_OUT=$(timeout 300 python3 -m venv "$VENV" 2>&1); then
    write_stage guest_venv failed "$VENV_OUT"
    exit 76
  fi
  write_stage guest_venv passed "$VENV_OUT"
else
  write_stage guest_venv passed "reusing pre-provisioned virtualenv"
fi

write_stage guest_dependencies starting "installing declared dependencies from offline wheel cache"
set +e
PIP_OUT=$(timeout 300 "$VENV/bin/pip" install --disable-pip-version-check --no-index --find-links=/opt/sophyane/wheels -r "$PROJECT/requirements.txt" 2>&1)
PIP_RC=$?
if [ "$PIP_RC" -eq 0 ]; then
  CHECK_OUT=$("$VENV/bin/pip" check 2>&1)
  CHECK_RC=$?
else
  CHECK_OUT="dependency installation failed; pip check skipped"
  CHECK_RC=1
fi
set -e
if [ "$PIP_RC" -eq 0 ] && [ "$CHECK_RC" -eq 0 ]; then
  write_stage guest_dependencies passed "$PIP_OUT\n$CHECK_OUT"
else
  write_stage guest_dependencies failed "pip_exit=$PIP_RC; pip_check_exit=$CHECK_RC; $PIP_OUT\n$CHECK_OUT"
fi

write_stage guest_migrations starting "applying SQL migration as the application database user"
set +e
MIGRATION_OUT=$(runuser -u sophyane -- env DATABASE_URL="$DATABASE_URL" psql -v ON_ERROR_STOP=1 -d "$DATABASE_URL" -f "$PROJECT/migrations/001_init.sql" 2>&1)
MIGRATION_RC=$?
set -e
SCHEMA_OUT=$(runuser -u sophyane -- env DATABASE_URL="$DATABASE_URL" psql -d "$DATABASE_URL" -Atc "SELECT to_regclass('public.inventory') IS NOT NULL" 2>&1) || SCHEMA_OUT="schema inspection failed: $SCHEMA_OUT"
if [ "$PIP_RC" -eq 0 ] && [ "$CHECK_RC" -eq 0 ] && [ "$MIGRATION_RC" -eq 0 ] && [ "$SCHEMA_OUT" = "t" ]; then
  write_stage guest_migrations passed "$MIGRATION_OUT\nschema_inventory=$SCHEMA_OUT"
else
  write_stage guest_migrations failed "pip_exit=$PIP_RC; pip_check_exit=$CHECK_RC; migration_exit=$MIGRATION_RC; schema=$SCHEMA_OUT; $MIGRATION_OUT"
fi

python3 - "$OUTPUT/qemu-execution.json" "$PIP_RC" "$CHECK_RC" "$MIGRATION_RC" "$PIP_OUT" "$CHECK_OUT" "$MIGRATION_OUT" "$SCHEMA_OUT" <<'PY'
import json, sys
path, pip_rc, check_rc, migration_rc, pip_out, check_out, migration_out, schema_out = sys.argv[1:]
with open(path, "w", encoding="utf-8") as handle:
    json.dump({
        "execution_environment": "qemu-linux-guest",
        "requirements_install_exit_code": int(pip_rc),
        "pip_check_exit_code": int(check_rc),
        "migration_exit_code": int(migration_rc),
        "schema_inventory_present": schema_out.strip() == "t",
        "requirements_install_output": pip_out[-12000:],
        "pip_check_output": check_out[-12000:],
        "migration_output": migration_out[-12000:],
    }, handle, sort_keys=True)
    handle.write("\n")
PY

if [ "$PIP_RC" -ne 0 ] || [ "$CHECK_RC" -ne 0 ] || [ "$MIGRATION_RC" -ne 0 ] || [ "$SCHEMA_OUT" != "t" ]; then
  exit 77
fi

write_stage guest_fastapi starting "starting actual backend.app FastAPI application"
exec runuser -u sophyane -- env \
  APP_ENV=production \
  DATABASE_URL="$DATABASE_URL" \
  JWT_SECRET="$JWT_SECRET" \
  PYTHONPATH="$PROJECT" \
  "$VENV/bin/uvicorn" backend.app:app --host 0.0.0.0 --port 8000
