#!/usr/bin/env bash
# Universal Sophyane installer/updater.
#
# Contract:
#   * every run installs the latest stable semantic release tag (vX.Y.Z) into
#     a fresh managed system directory and a fresh virtual environment;
#   * SOPHYANE_REF may explicitly override the release ref when needed;
#   * the previous managed Sophyane code/runtime is restored automatically if
#     installation or validation fails;
#   * user state/work stored outside the managed system/venv directories is
#     never deleted by an upgrade;
#   * installer progress is always visible and detailed logs are persisted.
set -Eeuo pipefail

REPO="https://github.com/badrpk/sophyane.git"
RAW="https://raw.githubusercontent.com/badrpk/sophyane/main"
BASE="${SOPHYANE_HOME:-$HOME/.local/share/sophyane}"
BIN="${SOPHYANE_BIN:-$HOME/.local/bin}"
SYSTEM="$BASE/system"
VENV="$BASE/venv"
USER_WORK="$BASE/user-work"
MANAGED_LAUNCHERS="$BASE/managed-launchers"
LOG_DIR="$BASE/install-logs"
LOCK_DIR="$BASE/.install-lock"
TMP=""
OLD_SYSTEM=""
OLD_VENV=""
SWAPPED=0
LOCKED=0
CURRENT_STEP="startup"

step() {
  CURRENT_STEP="$1"
  printf '\n==> %s\n' "$CURRENT_STEP"
}

cleanup() {
  rc=$?
  trap - EXIT INT TERM HUP

  if [ "$rc" -ne 0 ]; then
    printf '\nInstallation failed during: %s\n' "$CURRENT_STEP" >&2
    [ -n "${INSTALL_LOG:-}" ] && printf 'Install log: %s\n' "$INSTALL_LOG" >&2
  fi

  [ -n "${TMP:-}" ] && rm -rf "$TMP"

  if [ "$rc" -ne 0 ] && [ "$SWAPPED" -eq 1 ]; then
    printf 'Restoring previous Sophyane managed runtime...\n' >&2
    rm -rf "$SYSTEM" "$VENV"
    [ -e "$OLD_SYSTEM" ] && mv "$OLD_SYSTEM" "$SYSTEM"
    [ -e "$OLD_VENV" ] && mv "$OLD_VENV" "$VENV"
    printf 'Previous Sophyane managed installation restored.\n' >&2
  fi

  if [ "$LOCKED" -eq 1 ]; then
    rm -rf "$LOCK_DIR"
  fi

  exit "$rc"
}
trap cleanup EXIT INT TERM HUP

fail() { printf 'Error: %s\n' "$*" >&2; exit 1; }
need() { command -v "$1" >/dev/null 2>&1 || fail "'$1' is required."; }

run_logged() {
  label="$1"
  shift
  step "$label"
  set +e
  "$@" 2>&1 | tee -a "$INSTALL_LOG"
  rc=${PIPESTATUS[0]}
  set -e
  [ "$rc" -eq 0 ] || fail "$label failed (exit $rc)"
}

retry() {
  attempts="$1"
  shift
  n=1
  while true; do
    "$@" && return 0
    rc=$?
    [ "$n" -ge "$attempts" ] && return "$rc"
    printf 'Attempt %d/%d failed; retrying...\n' "$n" "$attempts" >&2
    n=$((n + 1))
    sleep 2
  done
}

need git
need python3
need tee
mkdir -p "$BASE" "$BIN" "$USER_WORK" "$LOG_DIR"

if ! mkdir "$LOCK_DIR" 2>/dev/null; then
  fail "another Sophyane installer appears to be running ($LOCK_DIR exists)"
fi
LOCKED=1

STAMP="$(date -u '+%Y%m%dT%H%M%SZ')"
INSTALL_LOG="$LOG_DIR/install-$STAMP.log"
: > "$INSTALL_LOG"
printf 'Install log: %s\n' "$INSTALL_LOG"

step "Checking Python"
python3 - <<'PY'
import sys
if sys.version_info < (3, 10):
    raise SystemExit(f"Sophyane requires Python 3.10+; found {sys.version.split()[0]}")
print("Python", sys.version.split()[0])
PY

archive_legacy_root_install() {
  [ -d "$BASE/.git" ] || return 0

  stamp="$(date -u '+%Y%m%dT%H%M%SZ')"
  backup="$USER_WORK/legacy-source-$stamp"
  mkdir -p "$backup/untracked"

  printf 'Legacy root-clone installation detected; preserving local work...\n'
  git -C "$BASE" diff --binary > "$backup/working-tree.patch" || true
  git -C "$BASE" diff --cached --binary > "$backup/index.patch" || true
  git -C "$BASE" rev-parse HEAD > "$backup/original-commit" 2>/dev/null || true

  while IFS= read -r -d '' rel; do
    [ -n "$rel" ] || continue
    src="$BASE/$rel"
    dst="$backup/untracked/$rel"
    if [ -e "$src" ]; then
      mkdir -p "$(dirname "$dst")"
      cp -a "$src" "$dst"
    fi
  done < <(git -C "$BASE" ls-files --others --exclude-standard -z 2>/dev/null || true)

  while IFS= read -r -d '' rel; do
    case "$rel" in
      system/*|venv/*|user-work/*) continue ;;
    esac
    rm -f -- "$BASE/$rel"
  done < <(git -C "$BASE" ls-files -z)

  rm -rf "$BASE/.git" "$BASE/.venv"
  printf 'Legacy source changes preserved at: %s\n' "$backup"
}

printf '=== Sophyane universal installer/updater ===\n'
archive_legacy_root_install

TMP="$(mktemp -d)"
SOURCE="$TMP/source"
INSTALL_REF="${SOPHYANE_REF:-}"

if [ -z "$INSTALL_REF" ]; then
  step "Resolving latest stable release"
  INSTALL_REF="$(
    retry 3 git ls-remote --tags --refs "$REPO" "refs/tags/v*" |
    python3 -c 'import re, sys
items = []
for line in sys.stdin:
    ref = line.rstrip().split("\t")[-1]
    m = re.fullmatch(r"refs/tags/v(\d+)\.(\d+)\.(\d+)", ref)
    if m:
        items.append((tuple(map(int, m.groups())), ref.rsplit("/", 1)[-1]))
if not items:
    raise SystemExit("No stable Sophyane release tags found")
print(max(items)[1])'
  )"
fi

printf 'Installing Sophyane ref: %s\n' "$INSTALL_REF"

step "Downloading release source"
retry 3 git clone --depth 1 --single-branch --branch "$INSTALL_REF" "$REPO" "$SOURCE"

COMMIT="$(git -C "$SOURCE" rev-parse HEAD)"
VERSION="$(python3 - "$SOURCE/pyproject.toml" <<'PY'
import re, sys
from pathlib import Path
text = Path(sys.argv[1]).read_text(encoding='utf-8')
m = re.search(r'^version\s*=\s*"([^"]+)"', text, re.M)
print(m.group(1) if m else 'unknown')
PY
)"
printf 'Resolved version: %s\nResolved commit: %s\n' "$VERSION" "$COMMIT"

OLD_SYSTEM="$BASE/.old-system-$$"
OLD_VENV="$BASE/.old-venv-$$"
rm -rf "$OLD_SYSTEM" "$OLD_VENV"

step "Preparing transactional upgrade"
[ -e "$SYSTEM" ] && mv "$SYSTEM" "$OLD_SYSTEM"
[ -e "$VENV" ] && mv "$VENV" "$OLD_VENV"
SWAPPED=1

mkdir -p "$SYSTEM"
cp -a "$SOURCE/." "$SYSTEM/"
rm -rf "$SYSTEM/.git"

step "Creating isolated Python environment"
python3 -m venv "$VENV"
export PYTHONNOUSERSITE=1
unset PYTHONPATH PYTHONHOME
export PIP_DEFAULT_TIMEOUT="${PIP_DEFAULT_TIMEOUT:-120}"

run_logged "Updating Python packaging tools" \
  "$VENV/bin/python" -m pip install \
  --disable-pip-version-check --no-cache-dir --retries 3 \
  --upgrade pip setuptools wheel

run_logged "Installing Sophyane and runtime dependencies" \
  "$VENV/bin/python" -m pip install \
  --disable-pip-version-check --no-cache-dir --retries 3 \
  --force-reinstall "$SYSTEM"

run_logged "Checking Python dependency integrity" \
  "$VENV/bin/python" -m pip check

step "Checking required runtime imports"
"$VENV/bin/python" - <<'PYDEP'
import numpy
import pexpect
import sophyane
print("numpy =", numpy.__version__)
print("pexpect =", pexpect.__version__)
print("sophyane =", sophyane.__file__)
PYDEP

LAUNCHERS=(
  sophyane sophyane-web sophyane-doctor sophyane-browser
  sophyane-sli sophyane-sli-train sophyane-sli-migrate sophyane-vela
  sophyane-platform sophyane-memory sophyane-task sophyane-execute
  sophyane-coi sophyane-release sophyane-audit sophyane-benchmark
  sophyane-mcp sophyane-mission
)

step "Installing command launchers"
if [ -f "$MANAGED_LAUNCHERS" ]; then
  while IFS= read -r name; do
    case "$name" in
      sophyane|sophyane-*) rm -f -- "$BIN/$name" ;;
    esac
  done < "$MANAGED_LAUNCHERS"
fi

: > "$MANAGED_LAUNCHERS"
for name in "${LAUNCHERS[@]}"; do
  target="$VENV/bin/$name"
  [ -x "$target" ] || fail "$name entry point was not installed"
  cat > "$BIN/$name" <<WRAP
#!/usr/bin/env bash
set -Eeuo pipefail
BASE="\${SOPHYANE_HOME:-\$HOME/.local/share/sophyane}"
export PYTHONNOUSERSITE=1
unset PYTHONPATH PYTHONHOME
exec "\$BASE/venv/bin/$name" "\$@"
WRAP
  chmod 0755 "$BIN/$name"
  printf '%s\n' "$name" >> "$MANAGED_LAUNCHERS"
done

case ":$PATH:" in
  *":$BIN:"*) ;;
  *)
    if [ -f "$HOME/.bashrc" ] && ! grep -Fq "$BIN" "$HOME/.bashrc"; then
      printf '\n# Sophyane CLI\nexport PATH="%s:$PATH"\n' "$BIN" >> "$HOME/.bashrc"
    fi
    export PATH="$BIN:$PATH"
    ;;
esac
hash -r 2>/dev/null || true

step "Validating Sophyane commands"
SOPHYANE_SKIP_UPDATE_CHECK=1 "$BIN/sophyane" --version >/dev/null || fail "sophyane failed validation"
"$BIN/sophyane-platform" status >/dev/null || fail "sophyane-platform failed validation"
"$BIN/sophyane-coi" status >/dev/null || fail "sophyane-coi failed validation"
"$BIN/sophyane-release" status >/dev/null || fail "sophyane-release failed validation"
"$BIN/sophyane-release" gate "$SYSTEM" --imports-only >/dev/null || fail "release import gate failed"

step "Running offline audit"
"$BIN/sophyane-audit" --output "$BASE/install-audit.json" >/dev/null || fail "comprehensive offline audit failed"

step "Running offline product benchmark"
BENCH_LOG="$BASE/install-benchmark.log"
if ! "$BIN/sophyane-benchmark" --output "$BASE/install-benchmark.json" >"$BENCH_LOG" 2>&1; then
  printf '\n--- Product benchmark failure report ---\n' >&2
  cat "$BENCH_LOG" >&2 || true
  printf '%s\n' '--- End benchmark report ---' >&2
  fail "100-point offline product benchmark failed"
fi

printf '%s\n' "$COMMIT" > "$BASE/installed-commit"
printf '%s\n' "$VERSION" > "$BASE/installed-version"
cat > "$BASE/install-info" <<EOF
VERSION=$VERSION
COMMIT=$COMMIT
SOURCE=$INSTALL_REF
UPDATED_AT=$(date -u '+%Y-%m-%dT%H:%M:%SZ')
INSTALL_URL=$RAW/install.sh
MANAGED_SYSTEM=$SYSTEM
MANAGED_VENV=$VENV
USER_STATE_ROOT=$BASE
INSTALL_LOG=$INSTALL_LOG
EOF

step "Finalizing upgrade"
SWAPPED=0
rm -rf "$OLD_SYSTEM" "$OLD_VENV" "$TMP"
TMP=""

printf '\n✅ Sophyane %s is installed and current\n' "$VERSION"
printf '   Commit: %.12s\n' "$COMMIT"
printf '   Managed system: %s\n' "$SYSTEM"
printf '   Managed venv:   %s\n' "$VENV"
printf '   Previous managed version: removed after validation\n'
printf '   User state/work: preserved under %s\n' "$BASE"
printf '   Install log: %s\n' "$INSTALL_LOG"
printf '   Offline audit report: %s/install-audit.json\n' "$BASE"
printf '   Product benchmark report: %s/install-benchmark.json\n' "$BASE"
printf '   Start: sophyane\n'
printf '   Universal install/update link:\n   curl -fsSL %s/install.sh | bash\n' "$RAW"
