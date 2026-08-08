#!/usr/bin/env bash
# Universal Sophyane installer/updater.
#
# Contract:
#   * every run installs the current GitHub main branch into a fresh managed
#     system directory and a fresh virtual environment;
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
git clone --quiet --depth 1 --single-branch --branch main "$REPO" "$SOURCE"
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
rm -rf "$OLD_SYSTEM" "$OLD_VENV"
[ -e "$SYSTEM" ] && mv "$SYSTEM" "$OLD_SYSTEM"
[ -e "$VENV" ] && mv "$VENV" "$OLD_VENV"
SWAPPED=1

mkdir -p "$SYSTEM"
cp -a "$SOURCE/." "$SYSTEM/"
rm -rf "$SYSTEM/.git"

python3 -m venv "$VENV"
export PYTHONNOUSERSITE=1
unset PYTHONPATH PYTHONHOME
"$VENV/bin/python" -m pip install --disable-pip-version-check --no-cache-dir --upgrade pip setuptools wheel >/dev/null
"$VENV/bin/python" -m pip install --disable-pip-version-check --no-cache-dir --force-reinstall "$SYSTEM" >/dev/null

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

# Remove only launchers previously managed by this installer, then recreate the
# current launcher set so no old executable can shadow the new release.
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

SOPHYANE_SKIP_UPDATE_CHECK=1 "$BIN/sophyane" --version >/dev/null || fail "sophyane failed validation"
"$BIN/sophyane-platform" status >/dev/null || fail "sophyane-platform failed validation"
"$BIN/sophyane-coi" status >/dev/null || fail "sophyane-coi failed validation"
"$BIN/sophyane-release" status >/dev/null || fail "sophyane-release failed validation"
"$BIN/sophyane-release" gate "$SYSTEM" --imports-only >/dev/null || fail "release import gate failed"
"$BIN/sophyane-audit" --output "$BASE/install-audit.json" >/dev/null || fail "comprehensive offline audit failed"
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
SOURCE=main
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
