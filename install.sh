#!/usr/bin/env bash
set -Eeuo pipefail

REPO="https://github.com/badrpk/sophyane.git"
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

command -v git >/dev/null 2>&1 || fail "git is required (Termux: pkg install git)"
command -v python3 >/dev/null 2>&1 || fail "Python 3 is required (Termux: pkg install python)"

printf 'Checking GitHub for the latest Sophyane release...\n'

VERSION="$({
  git ls-remote --heads "$REPO" 'refs/heads/release/v*' |
    awk '{sub("refs/heads/release/v", "", $2); print $2}' |
    grep -E '^[0-9]+\.[0-9]+\.[0-9]+$' |
    sort -V |
    tail -n 1
} || true)"

[ -n "$VERSION" ] || fail "No release/vX.Y.Z branch was found"

BRANCH="release/v$VERSION"
RELEASE_COMMIT="$(
  git ls-remote --heads "$REPO" "refs/heads/$BRANCH" |
    awk 'NR == 1 {print $1}'
)"

[ -n "$RELEASE_COMMIT" ] || fail "Could not resolve $BRANCH"

printf 'Latest release: v%s\n' "$VERSION"
printf 'Release branch: %s\n' "$BRANCH"
printf 'Pinned commit: %s\n' "$RELEASE_COMMIT"

TMP_DIR="$(mktemp -d)"
SOURCE="$TMP_DIR/source"
TARGET="$RELEASES/$VERSION-$RELEASE_COMMIT"

git clone \
  --quiet \
  --depth 1 \
  --branch "$BRANCH" \
  --single-branch \
  "$REPO" \
  "$SOURCE"

ACTUAL_COMMIT="$(git -C "$SOURCE" rev-parse HEAD)"
[ "$ACTUAL_COMMIT" = "$RELEASE_COMMIT" ] || {
  printf 'Commit verification failed\nExpected: %s\nActual:   %s\n' \
    "$RELEASE_COMMIT" "$ACTUAL_COMMIT" >&2
  exit 1
}

if [ ! -f "$SOURCE/pyproject.toml" ] && \
   [ ! -f "$SOURCE/setup.py" ] && \
   [ ! -f "$SOURCE/setup.cfg" ]; then
  fail "The selected release is not an installable Python package"
fi

mkdir -p "$BASE" "$BIN" "$RELEASES"
rm -rf "$TARGET"
mkdir -p "$TARGET"
cp -a "$SOURCE/." "$TARGET/"

rm -rf "$VENV"
python3 -m venv "$VENV"
"$VENV/bin/python" -m pip install --disable-pip-version-check --upgrade pip setuptools wheel
"$VENV/bin/python" -m pip install --disable-pip-version-check "$TARGET"

ln -sfn "$TARGET" "$BASE/current"

cat > "$BIN/sophyane" <<EOF
#!/usr/bin/env bash
set -Eeuo pipefail
exec "$VENV/bin/sophyane" "\$@"
EOF
chmod 0755 "$BIN/sophyane"

cat > "$BASE/installed-release" <<EOF
VERSION=$VERSION
BRANCH=$BRANCH
COMMIT=$RELEASE_COMMIT
INSTALLED_AT=$(date -u '+%Y-%m-%dT%H:%M:%SZ')
EOF

case ":$PATH:" in
  *":$BIN:"*) ;;
  *)
    printf '\nexport PATH="$HOME/.local/bin:$PATH"\n' >> "$HOME/.bashrc"
    export PATH="$BIN:$PATH"
    ;;
esac

hash -r 2>/dev/null || true
"$BIN/sophyane" --version

if "$BIN/sophyane" self-test >/dev/null 2>&1; then
  printf 'Self-test passed.\n'
else
  printf 'Note: this release does not provide a passing self-test command.\n'
fi

printf '\n✅ Sophyane v%s installed from %s at %s.\n' \
  "$VERSION" "$BRANCH" "$RELEASE_COMMIT"
