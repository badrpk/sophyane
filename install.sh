#!/usr/bin/env bash
# Sophyane public installer — always installs the **latest** released version
# from GitHub and sets up a venv + CLI wrappers + optional C++ train core.
#
# Public one-liner (main branch always hosts this script):
#   curl -fsSL https://raw.githubusercontent.com/badrpk/sophyane/main/install.sh | sh
#
# Pin a version (optional):
#   SOPHYANE_VERSION=16.9.0 curl -fsSL ... | sh
# Pin a commit (optional):
#   SOPHYANE_COMMIT=<sha> curl -fsSL ... | sh
set -Eeuo pipefail

REPO_HTTPS="https://github.com/badrpk/sophyane.git"
REPO_RAW="https://raw.githubusercontent.com/badrpk/sophyane"
BASE="${SOPHYANE_HOME:-$HOME/.local/share/sophyane}"
BIN="${SOPHYANE_BIN:-$HOME/.local/bin}"
RELEASES="$BASE/releases"
VENV="$BASE/venv"
TMP_DIR=""

cleanup() {
  [ -n "${TMP_DIR:-}" ] && rm -rf "$TMP_DIR"
}
trap cleanup EXIT

fail() {
  printf 'Error: %s\n' "$*" >&2
  exit 1
}

info() { printf '%s\n' "$*"; }

need_cmd() {
  command -v "$1" >/dev/null 2>&1 || fail "'$1' is required. Install it and re-run."
}

need_cmd git
need_cmd python3

# Optional but recommended
HAS_GPP=0
command -v g++ >/dev/null 2>&1 && HAS_GPP=1
command -v c++ >/dev/null 2>&1 && HAS_GPP=1
HAS_CURL=0
command -v curl >/dev/null 2>&1 && HAS_CURL=1

info "=== Sophyane installer (always latest release) ==="
info "Checking GitHub for the newest version..."

# Collect candidate versions from release branches AND tags
VERSION_LIST="$(
  {
    git ls-remote --heads "$REPO_HTTPS" 'refs/heads/release/v*' 2>/dev/null |
      awk '{sub("refs/heads/release/v", "", $2); print $2}'
    git ls-remote --tags "$REPO_HTTPS" 'refs/tags/v*' 2>/dev/null |
      awk '{
        sub("refs/tags/v", "", $2);
        sub("\\^\\{\\}", "", $2);
        print $2
      }'
  } | grep -E '^[0-9]+\.[0-9]+\.[0-9]+$' | sort -u | sort -V
)"

if [ -n "${SOPHYANE_VERSION:-}" ]; then
  VERSION="${SOPHYANE_VERSION#v}"
else
  VERSION="$(printf '%s\n' "$VERSION_LIST" | tail -n 1)"
fi

[ -n "$VERSION" ] || fail "No release/vX.Y.Z branch or vX.Y.Z tag found on GitHub"

# Prefer release branch; fall back to tag; then main (only if forced)
BRANCH="release/v$VERSION"
TAG="v$VERSION"
REF=""
REF_KIND=""

if git ls-remote --heads "$REPO_HTTPS" "refs/heads/$BRANCH" | grep -q .; then
  REF="$BRANCH"
  REF_KIND="branch"
elif git ls-remote --tags "$REPO_HTTPS" "refs/tags/$TAG" | grep -q .; then
  REF="$TAG"
  REF_KIND="tag"
elif [ "${SOPHYANE_ALLOW_MAIN:-}" = "1" ]; then
  REF="main"
  REF_KIND="branch"
  info "Note: using main (SOPHYANE_ALLOW_MAIN=1); prefer tagged releases for production."
else
  fail "Could not find $BRANCH or tag $TAG on GitHub"
fi

if [ -n "${SOPHYANE_COMMIT:-}" ]; then
  RELEASE_COMMIT="$SOPHYANE_COMMIT"
else
  if [ "$REF_KIND" = "tag" ]; then
    RELEASE_COMMIT="$(git ls-remote --tags "$REPO_HTTPS" "refs/tags/$REF" | awk 'NR==1 {print $1}')"
  else
    RELEASE_COMMIT="$(git ls-remote --heads "$REPO_HTTPS" "refs/heads/$REF" | awk 'NR==1 {print $1}')"
  fi
fi
[ -n "$RELEASE_COMMIT" ] || fail "Could not resolve commit for $REF"

info "Latest version selected: v$VERSION"
info "Source ref:             $REF ($REF_KIND)"
info "Pinned commit:          $RELEASE_COMMIT"
info "Install root:           $BASE"

TMP_DIR="$(mktemp -d)"
SOURCE="$TMP_DIR/source"
TARGET="$RELEASES/$VERSION-$RELEASE_COMMIT"

info "Cloning Sophyane $REF..."
if [ "$REF_KIND" = "tag" ]; then
  git clone --quiet --depth 1 --branch "$REF" --single-branch "$REPO_HTTPS" "$SOURCE"
else
  git clone --quiet --depth 1 --branch "$REF" --single-branch "$REPO_HTTPS" "$SOURCE"
fi

ACTUAL_COMMIT="$(git -C "$SOURCE" rev-parse HEAD)"
if [ -z "${SOPHYANE_COMMIT:-}" ] && [ "$ACTUAL_COMMIT" != "$RELEASE_COMMIT" ]; then
  # shallow clone of moving branch tip can differ if race; re-pin to actual
  info "Note: resolved tip $ACTUAL_COMMIT (remote advertised $RELEASE_COMMIT)"
  RELEASE_COMMIT="$ACTUAL_COMMIT"
  TARGET="$RELEASES/$VERSION-$RELEASE_COMMIT"
fi

if [ ! -f "$SOURCE/pyproject.toml" ] && [ ! -f "$SOURCE/setup.py" ]; then
  fail "Selected tree is not an installable Python package"
fi

# Preserve user data; only replace code tree + venv
mkdir -p "$BASE" "$BIN" "$RELEASES"
rm -rf "$TARGET"
mkdir -p "$TARGET"
cp -a "$SOURCE/." "$TARGET/"

info "Creating virtualenv and installing package + build tooling..."
rm -rf "$VENV"
python3 -m venv "$VENV"
# Dependencies: Sophyane is stdlib-first; still upgrade packaging tools for reliability
"$VENV/bin/python" -m pip install --disable-pip-version-check --upgrade pip setuptools wheel
# Install package (editable not needed for releases). Include nothing mandatory.
"$VENV/bin/python" -m pip install --disable-pip-version-check "$TARGET"
# Optional: pytest available for self-check if user wants (lightweight)
if [ "${SOPHYANE_INSTALL_DEV:-}" = "1" ]; then
  "$VENV/bin/python" -m pip install --disable-pip-version-check pytest >/dev/null 2>&1 || true
fi

ln -sfn "$TARGET" "$BASE/current"

# CLI wrappers
cat > "$BIN/sophyane" <<EOF
#!/usr/bin/env bash
set -Eeuo pipefail
exec "$VENV/bin/sophyane" "\$@"
EOF
chmod 0755 "$BIN/sophyane"

cat > "$BIN/sophyane-browser" <<EOF
#!/usr/bin/env bash
set -Eeuo pipefail
exec "$VENV/bin/sophyane" --browser "\$@"
EOF
chmod 0755 "$BIN/sophyane-browser"

# Optional pure-C++ continual train core (hardware-efficient)
if [ "$HAS_GPP" -eq 1 ] && [ -f "$TARGET/sdk/cpp/continual/src/train_core.cpp" ]; then
  info "Building C++ train core (sophyane-train-core)..."
  if "$BIN/sophyane" --train-build-core >/tmp/sophyane-train-build.log 2>&1; then
    info "C++ train core: OK"
  else
    info "C++ train core: skipped (see /tmp/sophyane-train-build.log)"
  fi
else
  info "C++ toolchain not found or sources missing — train core can be built later with: sophyane --train-build-core"
fi

cat > "$BASE/installed-release" <<EOF
VERSION=$VERSION
REF=$REF
REF_KIND=$REF_KIND
COMMIT=$RELEASE_COMMIT
INSTALLED_AT=$(date -u '+%Y-%m-%dT%H:%M:%SZ')
PUBLIC_INSTALL=curl -fsSL https://raw.githubusercontent.com/badrpk/sophyane/main/install.sh | sh
REPO=https://github.com/badrpk/sophyane
EOF

# Also expose a tiny LATEST pointer for tools
printf 'v%s\n%s\n' "$VERSION" "$RELEASE_COMMIT" > "$BASE/LATEST"

case ":$PATH:" in
  *":$BIN:"*) ;;
  *)
    if [ -f "$HOME/.bashrc" ]; then
      printf '\n# Sophyane CLI\nexport PATH="%s:$PATH"\n' "$BIN" >> "$HOME/.bashrc"
    fi
    export PATH="$BIN:$PATH"
    ;;
esac

hash -r 2>/dev/null || true

info ""
info "Verifying install..."
"$BIN/sophyane" --version || fail "sophyane --version failed"
if "$BIN/sophyane" --doctor >/tmp/sophyane-doctor.log 2>&1; then
  info "Doctor: OK"
else
  info "Doctor: completed with notes (see /tmp/sophyane-doctor.log)"
fi

# Lightweight post-install audit when not on tiny CI
if [ "${SOPHYANE_SKIP_AUDIT:-}" != "1" ]; then
  if "$BIN/sophyane" --audit >/tmp/sophyane-audit.log 2>&1; then
    info "Feature audit: OK"
  else
    info "Feature audit: partial (see /tmp/sophyane-audit.log) — core CLI is installed"
  fi
fi

info ""
info "✅ Sophyane v${VERSION} installed"
info "   Commit:  $RELEASE_COMMIT"
info "   Code:    $TARGET"
info "   CLI:     $BIN/sophyane"
info "   Repo:    https://github.com/badrpk/sophyane"
info "   Upgrade: curl -fsSL https://raw.githubusercontent.com/badrpk/sophyane/main/install.sh | sh"
info ""
info "Quick start:"
info "  sophyane --help"
info "  sophyane --audit"
info "  sophyane --exam-tough100 --expert-only"
info "  sophyane --boot"
info "  sophyane-browser"

if [ -n "${DISPLAY:-}${WAYLAND_DISPLAY:-}" ] && [ "${SOPHYANE_NO_BROWSER:-}" != "1" ]; then
  "$BIN/sophyane" --browser >/tmp/sophyane-browser-install.log 2>&1 &
fi
