#!/usr/bin/env bash
# Universal Sophyane installer/updater with transactional rollback and CLI verification.
set -Eeuo pipefail

REPO="https://github.com/badrpk/sophyane.git"
RAW="https://raw.githubusercontent.com/badrpk/sophyane/main"
BASE="${SOPHYANE_HOME:-$HOME/.local/share/sophyane}"
BIN="${SOPHYANE_BIN:-$HOME/.local/bin}"
SYSTEM="$BASE/system"
VENV="$BASE/venv"
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
    printf 'Previous Sophyane installation restored.\n' >&2
  fi
  exit "$rc"
}
trap cleanup EXIT
fail() { printf 'Error: %s\n' "$*" >&2; exit 1; }
need() { command -v "$1" >/dev/null 2>&1 || fail "'$1' is required."; }
need git
need python3
mkdir -p "$BASE" "$BIN"

printf '=== Sophyane universal installer ===\n'
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

make_wrapper() {
  name="$1"; module="$2"
  cat > "$BIN/$name" <<WRAP
#!/usr/bin/env bash
set -Eeuo pipefail
BASE="\${SOPHYANE_HOME:-\$HOME/.local/share/sophyane}"
export PYTHONNOUSERSITE=1
unset PYTHONPATH PYTHONHOME
exec "\$BASE/venv/bin/python" -I -m $module "\$@"
WRAP
  chmod 0755 "$BIN/$name"
}

make_wrapper sophyane sophyane.cli_entry
make_wrapper sophyane-platform sophyane.platform_cli
make_wrapper sophyane-coi sophyane.coi_cli
make_wrapper sophyane-release sophyane.release_cli
make_wrapper sophyane-audit sophyane.audit_cli
make_wrapper sophyane-benchmark sophyane.benchmark_cli

cat > "$BIN/sophyane-browser" <<'WRAP'
#!/usr/bin/env bash
set -Eeuo pipefail
exec "${SOPHYANE_BIN:-$HOME/.local/bin}/sophyane" --browser "$@"
WRAP
chmod 0755 "$BIN/sophyane-browser"

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

for command in sophyane sophyane-platform sophyane-coi sophyane-release sophyane-audit sophyane-benchmark; do
  [ -x "$BIN/$command" ] || fail "$command launcher was not created"
done
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
EOF

SWAPPED=0
rm -rf "$OLD_SYSTEM" "$OLD_VENV" "$TMP"
TMP=""
printf '\n✅ Sophyane %s is installed and current\n' "$VERSION"
printf '   Commit: %.12s\n' "$COMMIT"
printf '   System: %s\n' "$SYSTEM"
printf '   Verified CLIs: sophyane, sophyane-platform, sophyane-coi, sophyane-release, sophyane-audit, sophyane-benchmark\n'
printf '   Offline audit report: %s/install-audit.json\n' "$BASE"
printf '   Product benchmark report: %s/install-benchmark.json\n' "$BASE"
printf '   User work: unchanged\n'
printf '   Start: sophyane\n'
printf '   Universal install/update link:\n   curl -fsSL %s/install.sh | bash\n' "$RAW"
