#!/usr/bin/env bash
# Universal Sophyane installer/updater.
#
# Contract:
#   * every run installs the latest stable semantic release tag (vX.Y.Z) into
#     a fresh managed system directory and a fresh virtual environment;
#   * SOPHYANE_REF may explicitly override the release ref when needed;
#   * the previous managed Sophyane code/runtime is removed only after the new
#     installation validates successfully;
#   * user state/work stored outside the managed system/venv directories is
#     never deleted by an upgrade;
#   * legacy root-clone installs are retired safely: tracked Sophyane source is
#     removed, while local source edits are saved as patches and untracked work
#     is copied into user-work before cleanup.
set -Eeuo pipefail

REPO="https://github.com/badrpk/sophyane.git"
RAW="https://raw.githubusercontent.com/badrpk/sophyane/main"
BASE="${SOPHYANE_HOME:-$HOME/.local/share/sophyane}"
BIN="${SOPHYANE_BIN:-$HOME/.local/bin}"
SYSTEM="$BASE/system"
VENV="$BASE/venv"
USER_WORK="$BASE/user-work"
MANAGED_LAUNCHERS="$BASE/managed-launchers"
TMP=""
OLD_SYSTEM=""
OLD_VENV=""
SWAPPED=0

cleanup() {
  rc=$?
  [ -n "${TMP:-}" ] && rm -rf "$TMP"
  if [ "$rc" -ne 0 ] && [ "$SWAPPED" -eq 1 ]; then
    rm -rf "$SYSTEM" "$VENV"
    [ -e "$OLD_SYSTEM" ] && mv "$OLD_SYSTEM" "$SYSTEM"
    [ -e "$OLD_VENV" ] && mv "$OLD_VENV" "$VENV"
    printf 'Previous Sophyane managed installation restored.\n' >&2
  fi
  exit "$rc"
}
trap cleanup EXIT

fail() { printf 'Error: %s\n' "$*" >&2; exit 1; }
need() { command -v "$1" >/dev/null 2>&1 || fail "'$1' is required."; }

need git
need python3
mkdir -p "$BASE" "$BIN" "$USER_WORK"

archive_legacy_root_install() {
  # Older Sophyane installers may have cloned the repository directly into
  # SOPHYANE_HOME.  Retire that managed source without throwing away user work.
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

  # Remove only files Git identifies as tracked Sophyane source.  Modified
  # tracked files remain recoverable from working-tree.patch/index.patch.
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
  INSTALL_REF="$(
    git ls-remote --tags --refs "$REPO" "refs/tags/v*" |
    python3 -c 'import re, sys
items = []
for line in sys.stdin:
    ref = line.rstrip().split("\t")[-1]
    m = re.fullmatch(r"refs/tags/v(\d+)\.(\d+)\.(\d+)", ref)
    if m:
        version = tuple(map(int, m.groups()))
        tag = ref.rsplit("/", 1)[-1]
        items.append((version, tag))
if not items:
    raise SystemExit("No stable Sophyane release tags found")
print(max(items)[1])'
  )"
fi

printf 'Installing Sophyane ref: %s\n' "$INSTALL_REF"

git clone --quiet --depth 1 --single-branch   --branch "$INSTALL_REF"   "$REPO"   "$SOURCE"

# On Termux, install the repository-declared system dependency manifest before
# creating the candidate Python/native runtime.
if [ -n "${TERMUX_VERSION:-}" ] || [ -x "/data/data/com.termux/files/usr/bin/pkg" ]; then
  PKG="$(command -v pkg || true)"
  [ -n "$PKG" ] || fail "Termux detected but pkg is unavailable"

  mapfile -t TERMUX_DEPS < <(
    python3 - "$SOURCE/system-dependencies.json" <<'PYDEPS'
import json
import sys
from pathlib import Path

data = json.loads(
    Path(sys.argv[1]).read_text(encoding="utf-8")
)

for dep in data.get("termux", []):
    dep = str(dep).strip()
    if dep:
        print(dep)
PYDEPS
  )

  MISSING_DEPS=()

  for dep in "${TERMUX_DEPS[@]}"; do
    if command -v dpkg-query >/dev/null 2>&1 &&
       dpkg-query -W -f='${Status}' "$dep" 2>/dev/null |
         grep -Fq 'install ok installed'; then
      continue
    fi
    MISSING_DEPS+=("$dep")
  done

  if [ "${#MISSING_DEPS[@]}" -gt 0 ]; then
    printf 'Installing missing Termux dependencies: %s\n'       "${MISSING_DEPS[*]}"

    "$PKG" install -y "${MISSING_DEPS[@]}" ||
      fail "required Termux dependencies could not be installed"
  else
    printf '%s\n'       'Termux dependency manifest already satisfied.'
  fi
fi

COMMIT="$(git -C "$SOURCE" rev-parse HEAD)"
VERSION="$(python3 - "$SOURCE/pyproject.toml" <<'PY'
import re, sys
from pathlib import Path
text = Path(sys.argv[1]).read_text(encoding='utf-8')
m = re.search(r'^version\s*=\s*"([^"]+)"', text, re.M)
print(m.group(1) if m else 'unknown')
PY
)"

OLD_SYSTEM="$BASE/.old-system-$$"
OLD_VENV="$BASE/.old-venv-$$"
CAND_SYSTEM="$TMP/candidate-system"
CAND_VENV="$TMP/candidate-venv"

rm -rf "$OLD_SYSTEM" "$OLD_VENV" "$CAND_SYSTEM" "$CAND_VENV"

mkdir -p "$CAND_SYSTEM"
cp -a "$SOURCE/." "$CAND_SYSTEM/"
rm -rf "$CAND_SYSTEM/.git"

python3 -m venv "$CAND_VENV"
export PYTHONNOUSERSITE=1
unset PYTHONPATH PYTHONHOME
"$CAND_VENV/bin/python" -m pip install --disable-pip-version-check --no-cache-dir --upgrade pip setuptools wheel >/dev/null
"$CAND_VENV/bin/python" -m pip install --disable-pip-version-check --no-cache-dir --force-reinstall "$CAND_SYSTEM" >/dev/null

"$CAND_VENV/bin/python" -m pip check >/dev/null ||
  fail "Python dependency graph is broken"

"$CAND_VENV/bin/python" - <<'PYDEP'
import numpy
import pexpect
import sophyane

print("numpy =", numpy.__version__)
print("pexpect =", pexpect.__version__)
print("sophyane =", sophyane.__file__)
PYDEP

LAUNCHERS=(
  sophyane
  sophyane-web
  sophyane-doctor
  sophyane-browser
  sophyane-sli
  sophyane-sli-train
  sophyane-sli-migrate
  sophyane-vela
  sophyane-platform
  sophyane-memory
  sophyane-task
  sophyane-execute
  sophyane-coi
  sophyane-release
  sophyane-audit
  sophyane-benchmark
  sophyane-mcp
  sophyane-mission
)

# Validate every required console entry point in the candidate environment
# before changing the currently working managed installation.
for name in "${LAUNCHERS[@]}"; do
  target="$CAND_VENV/bin/$name"
  [ -x "$target" ] || fail "$name entry point was not installed"
done

SOPHYANE_SKIP_UPDATE_CHECK=1 \
SOPHYANE_SKIP_LOCAL_BOOTSTRAP=1 \
  "$CAND_VENV/bin/sophyane" --version >/dev/null ||
  fail "sophyane failed validation"

"$CAND_VENV/bin/sophyane-platform" status >/dev/null ||
  fail "sophyane-platform failed validation"
"$CAND_VENV/bin/sophyane-coi" status >/dev/null ||
  fail "sophyane-coi failed validation"
"$CAND_VENV/bin/sophyane-release" status >/dev/null ||
  fail "sophyane-release failed validation"
"$CAND_VENV/bin/sophyane-release" gate "$CAND_SYSTEM" --imports-only >/dev/null ||
  fail "release import gate failed"

"$CAND_VENV/bin/sophyane-audit" \
  --output "$TMP/install-audit.json" >/dev/null ||
  fail "comprehensive offline audit failed"

BENCH_LOG="$TMP/install-benchmark.log"
if ! "$CAND_VENV/bin/sophyane-benchmark" \
    --output "$TMP/install-benchmark.json" >"$BENCH_LOG" 2>&1; then
  printf '\n--- Product benchmark failure report ---\n' >&2
  cat "$BENCH_LOG" >&2 || true
  printf '%s\n' '--- End benchmark report ---' >&2
  fail "100-point offline product benchmark failed"
fi

# Publication phase.  Candidate validation above intentionally leaves the
# currently working managed installation untouched.
#
# Python virtual environments are not safely relocatable because generated
# console scripts contain absolute interpreter paths.  Therefore do not move
# CAND_VENV into place.  Keep the old managed venv callable while building a
# fresh final venv directly at its permanent path.

# Bridge existing Sophyane launchers across the short publication phase.
# Before the old venv is moved these fall through to the live venv.  After it
# is moved they prefer OLD_VENV until final publication completes.
for name in "${LAUNCHERS[@]}"; do
  cat > "$BIN/$name" <<WRAP
#!/usr/bin/env bash
set -Eeuo pipefail
BASE="\${SOPHYANE_HOME:-\$HOME/.local/share/sophyane}"
export PYTHONNOUSERSITE=1
unset PYTHONPATH PYTHONHOME
if [ -x "$OLD_VENV/bin/$name" ]; then
  exec "$OLD_VENV/bin/$name" "\$@"
fi
exec "\$BASE/venv/bin/$name" "\$@"
WRAP
  chmod 0755 "$BIN/$name"
done

rm -rf "$OLD_SYSTEM" "$OLD_VENV"

if [ -e "$SYSTEM" ]; then
  mv "$SYSTEM" "$OLD_SYSTEM"
fi

if [ -e "$VENV" ]; then
  if ! mv "$VENV" "$OLD_VENV"; then
    [ -e "$OLD_SYSTEM" ] && mv "$OLD_SYSTEM" "$SYSTEM"
    fail "could not preserve previous managed virtual environment"
  fi
fi

SWAPPED=1

# Publish the already validated source tree.
mv "$CAND_SYSTEM" "$SYSTEM"

# Build the final Python environment at its permanent path.  The previous
# launchers continue to execute OLD_VENV while this potentially slow step runs.
python3 -m venv "$VENV"
"$VENV/bin/python" -m pip install \
  --disable-pip-version-check \
  --no-cache-dir \
  --upgrade pip setuptools wheel >/dev/null

"$VENV/bin/python" -m pip install \
  --disable-pip-version-check \
  --no-cache-dir \
  --force-reinstall "$SYSTEM" >/dev/null

"$VENV/bin/python" -m pip check >/dev/null ||
  fail "published Python dependency graph is broken"

# Validate permanent-path console scripts.  This catches venv/shebang problems
# that candidate-only validation cannot detect.
for name in "${LAUNCHERS[@]}"; do
  [ -x "$VENV/bin/$name" ] ||
    fail "published $name entry point was not installed"
done

SOPHYANE_SKIP_UPDATE_CHECK=1 \
SOPHYANE_SKIP_LOCAL_BOOTSTRAP=1 \
  "$VENV/bin/sophyane" --version >/dev/null ||
  fail "published sophyane failed validation"

"$VENV/bin/sophyane-platform" status >/dev/null ||
  fail "published sophyane-platform failed validation"

"$VENV/bin/sophyane-coi" status >/dev/null ||
  fail "published sophyane-coi failed validation"

"$VENV/bin/sophyane-release" status >/dev/null ||
  fail "published sophyane-release failed validation"

"$VENV/bin/sophyane-release" gate "$SYSTEM" --imports-only >/dev/null ||
  fail "published release import gate failed"

# Replace bridge launchers with the normal stable managed launchers.
if [ -f "$MANAGED_LAUNCHERS" ]; then
  while IFS= read -r name; do
    case "$name" in
      sophyane|sophyane-*) rm -f -- "$BIN/$name" ;;
    esac
  done < "$MANAGED_LAUNCHERS"
fi

: > "$MANAGED_LAUNCHERS"

for name in "${LAUNCHERS[@]}"; do
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
    if [ -f "$HOME/.bashrc" ] &&
       ! grep -Fq "$BIN" "$HOME/.bashrc"; then
      printf '\n# Sophyane CLI\nexport PATH="%s:$PATH"\n' \
        "$BIN" >> "$HOME/.bashrc"
    fi
    export PATH="$BIN:$PATH"
    ;;
esac

hash -r 2>/dev/null || true

# Verify through the public launcher after publication.
SOPHYANE_SKIP_UPDATE_CHECK=1 \
SOPHYANE_SKIP_LOCAL_BOOTSTRAP=1 \
  "$BIN/sophyane" --version >/dev/null ||
  fail "public Sophyane launcher failed after publication"

# Candidate audit/benchmark evidence becomes persistent only after the live
# installation has also passed its permanent-path checks.
cp "$TMP/install-audit.json" "$BASE/install-audit.json"

if [ -f "$TMP/install-benchmark.json" ]; then
  cp "$TMP/install-benchmark.json" "$BASE/install-benchmark.json"
fi

if [ -f "$TMP/install-benchmark.log" ]; then
  cp "$TMP/install-benchmark.log" "$BASE/install-benchmark.log"
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
EOF

# New installation is fully validated.  Only now permanently delete the old
# managed code/runtime.  Everything else under BASE is persistent user state.
SWAPPED=0
rm -rf "$OLD_SYSTEM" "$OLD_VENV" "$TMP"
TMP=""

# Optional capabilities are bootstrapped only after the managed Sophyane
# transaction has committed.  Failures here must not roll back a validated
# core installation.  Persistent model/state paths use Sophyane defaults;
# executable wrappers honor the installer's permanent BIN directory.
if [ "${SOPHYANE_SKIP_LOCAL_BOOTSTRAP:-0}" != "1" ]; then
  printf 'Checking hardware-fit local GGUF/runtime...\n'
  if ! \
    SOPHYANE_SKIP_UPDATE_CHECK=1 \
    SOPHYANE_NATIVE_BIN="$BIN" \
    "$VENV/bin/python" - <<'PYLOCAL'
from sophyane.local_runtime import ensure_local_open_model

result = ensure_local_open_model(progress=print)
print("Local runtime =", result.to_dict())
if not result.ok:
    raise SystemExit(result.message)
PYLOCAL
  then
    printf '%s\n' \
      'Warning: local GGUF/runtime bootstrap unavailable; Sophyane core remains installed and startup can retry later.' \
      >&2
  fi
else
  printf '%s\n' \
    'Skipping local GGUF/runtime bootstrap because SOPHYANE_SKIP_LOCAL_BOOTSTRAP=1.'
fi

if [ "${SOPHYANE_SKIP_NATIVE_BOOTSTRAP:-0}" != "1" ]; then
  printf 'Checking NIFDU/Neuron native backends...\n'
  if ! \
    SOPHYANE_STATE_DIR="${SOPHYANE_STATE_DIR:-$HOME/.local/state/sophyane}" \
    SOPHYANE_NATIVE_BIN="$BIN" \
    "$VENV/bin/python" - <<'PYNATIVE'
from sophyane.collaborative_workers import ensure_neuron, ensure_nifdu

nifdu = ensure_nifdu()
neuron = ensure_neuron()

print("NIFDU =", nifdu)
print("Neuron =", neuron)

if not nifdu.get("available"):
    raise SystemExit("NIFDU unavailable after bootstrap")
PYNATIVE
  then
    printf '%s\n' \
      'Warning: NIFDU/Neuron bootstrap unavailable; Sophyane core installation remains usable.' \
      >&2
  fi
else
  printf '%s\n' \
    'Skipping NIFDU/Neuron bootstrap because SOPHYANE_SKIP_NATIVE_BOOTSTRAP=1.'
fi

printf '\n✅ Sophyane %s is installed and current\n' "$VERSION"
printf '   Commit: %.12s\n' "$COMMIT"
printf '   Managed system: %s\n' "$SYSTEM"
printf '   Managed venv:   %s\n' "$VENV"
printf '   Previous managed version: removed after validation\n'
printf '   User state/work: preserved under %s\n' "$BASE"
printf '   Legacy source edits (if any): %s\n' "$USER_WORK"
printf '   Offline audit report: %s/install-audit.json\n' "$BASE"
printf '   Product benchmark report: %s/install-benchmark.json\n' "$BASE"
printf '   Start: sophyane\n'
printf '   Universal install/update link:\n   curl -fsSL %s/install.sh | bash\n' "$RAW"
