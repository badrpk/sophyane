#!/usr/bin/env bash
# Universal Sophyane installer/updater.
# Always installs the latest main branch, preserves user work, and removes old system copies.
#
# Universal link:
#   curl -fsSL https://raw.githubusercontent.com/badrpk/sophyane/main/install.sh | bash
set -Eeuo pipefail

REPO="https://github.com/badrpk/sophyane.git"
RAW="https://raw.githubusercontent.com/badrpk/sophyane/main"
BASE="${SOPHYANE_HOME:-$HOME/.local/share/sophyane}"
BIN="${SOPHYANE_BIN:-$HOME/.local/bin}"
SYSTEM="$BASE/system"
VENV="$BASE/venv"
TMP=""

cleanup() {
  [ -n "${TMP:-}" ] && rm -rf "$TMP"
}
trap cleanup EXIT

fail() { printf 'Error: %s\n' "$*" >&2; exit 1; }
info() { printf '%s\n' "$*"; }
need() { command -v "$1" >/dev/null 2>&1 || fail "'$1' is required."; }

need git
need python3

info "=== Sophyane universal installer ==="
info "Installing latest Sophyane from main..."

TMP="$(mktemp -d)"
SOURCE="$TMP/source"
NEW_SYSTEM="$TMP/system"
NEW_VENV="$TMP/venv"

git clone --quiet --depth 1 --single-branch --branch main "$REPO" "$SOURCE"
COMMIT="$(git -C "$SOURCE" rev-parse HEAD)"
VERSION="$(python3 - "$SOURCE/pyproject.toml" <<'PY'
import re, sys
from pathlib import Path
text = Path(sys.argv[1]).read_text(encoding="utf-8")
match = re.search(r'^version\s*=\s*"([^"]+)"', text, re.M)
print(match.group(1) if match else "unknown")
PY
)"

[ -f "$SOURCE/pyproject.toml" ] || fail "Repository is not an installable Sophyane tree."

cp -a "$SOURCE/." "$NEW_SYSTEM/"
rm -rf "$NEW_SYSTEM/.git"

info "Building isolated runtime..."
python3 -m venv "$NEW_VENV"
"$NEW_VENV/bin/python" -m pip install --disable-pip-version-check --upgrade pip setuptools wheel >/dev/null
"$NEW_VENV/bin/python" -m pip install --disable-pip-version-check "$NEW_SYSTEM" >/dev/null
"$NEW_VENV/bin/sophyane" --version >/dev/null || fail "New Sophyane runtime failed validation. Existing installation was not changed."

mkdir -p "$BASE" "$BIN"

# Preserve all user-owned data and repositories. Only Sophyane-managed system paths are replaced.
# User data remains in ~/.sophyane, project directories, and any path outside the managed paths below.
OLD_SYSTEM="$BASE/.old-system-$$"
OLD_VENV="$BASE/.old-venv-$$"
rm -rf "$OLD_SYSTEM" "$OLD_VENV"
[ -e "$SYSTEM" ] && mv "$SYSTEM" "$OLD_SYSTEM"
[ -e "$VENV" ] && mv "$VENV" "$OLD_VENV"
mv "$NEW_SYSTEM" "$SYSTEM"
mv "$NEW_VENV" "$VENV"

cat > "$BIN/sophyane" <<'WRAP'
#!/usr/bin/env bash
set -Eeuo pipefail
BASE="${SOPHYANE_HOME:-$HOME/.local/share/sophyane}"
INSTALL_URL="https://raw.githubusercontent.com/badrpk/sophyane/main/install.sh"
REPO="https://github.com/badrpk/sophyane.git"

check_update() {
  [ "${SOPHYANE_SKIP_UPDATE_CHECK:-0}" = "1" ] && return 0
  command -v git >/dev/null 2>&1 || return 0
  local installed remote answer
  installed="$(cat "$BASE/installed-commit" 2>/dev/null || true)"
  remote="$(git ls-remote "$REPO" refs/heads/main 2>/dev/null | awk 'NR==1 {print $1}')"
  if [ -z "$installed" ] || [ -z "$remote" ] || [ "$installed" = "$remote" ]; then
    return 0
  fi

  printf '\nSophyane update available.\n'
  printf 'Installed: %.12s\nLatest:    %.12s\n' "$installed" "$remote"
  if [ -t 0 ] && [ -t 1 ]; then
    printf 'Update now? Your repositories and work files will remain intact. [Y/n] '
    read -r answer
    case "${answer:-Y}" in
      n|N|no|NO) return 0 ;;
    esac
    if command -v curl >/dev/null 2>&1; then
      curl -fsSL "$INSTALL_URL" | bash
    elif command -v wget >/dev/null 2>&1; then
      wget -qO- "$INSTALL_URL" | bash
    else
      printf 'Install curl or wget to update.\n' >&2
      return 0
    fi
  else
    printf 'Run: curl -fsSL %s | bash\n' "$INSTALL_URL"
  fi
}

check_update
exec "$BASE/venv/bin/sophyane" "$@"
WRAP
chmod 0755 "$BIN/sophyane"

cat > "$BIN/sophyane-browser" <<'WRAP'
#!/usr/bin/env bash
set -Eeuo pipefail
exec "${SOPHYANE_BIN:-$HOME/.local/bin}/sophyane" --browser "$@"
WRAP
chmod 0755 "$BIN/sophyane-browser"

printf '%s\n' "$COMMIT" > "$BASE/installed-commit"
printf '%s\n' "$VERSION" > "$BASE/installed-version"
cat > "$BASE/install-info" <<EOF
VERSION=$VERSION
COMMIT=$COMMIT
SOURCE=main
UPDATED_AT=$(date -u '+%Y-%m-%dT%H:%M:%SZ')
INSTALL_URL=$RAW/install.sh
EOF

# Remove all obsolete Sophyane system copies created by older installers.
rm -rf "$OLD_SYSTEM" "$OLD_VENV"
rm -rf "$BASE/releases" "$BASE/current" "$BASE/LATEST" "$BASE/installed-release"
find "$BASE" -maxdepth 1 -type d \( -name '.old-system-*' -o -name '.old-venv-*' \) -exec rm -rf {} + 2>/dev/null || true

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
info ""
info "✅ Sophyane $VERSION is installed and current"
info "   System: $SYSTEM"
info "   User work: unchanged"
info "   Old Sophyane versions: removed"
info "   Start: sophyane"
info "   Universal install/update link:"
info "   curl -fsSL $RAW/install.sh | bash"
