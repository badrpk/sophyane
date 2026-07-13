#!/usr/bin/env bash
set -Eeuo pipefail
VERSION="9.0.3"
RELEASE_COMMIT="4285b2caa3b9f79b6876fc06b010c8459608cf98"
ENTRY="sophyane-9.0.3.py"
EXPECTED="7a33f62da3dfc90274170b6aa6c1fef327590d30214d4870e28c3b183b2aaa7c"
RAW="https://raw.githubusercontent.com/badrpk/sophyane/${RELEASE_COMMIT}"
BASE="$HOME/.local/share/sophyane"
BIN="$HOME/.local/bin"
APP="$BASE/sophyane.py"
TMP="$(mktemp)"
cleanup(){ rm -f "$TMP"; }
trap cleanup EXIT
mkdir -p "$BASE" "$BIN" "$HOME/.config/sophyane" "$HOME/.local/state/sophyane"
curl -fsSL "$RAW/$ENTRY" -o "$TMP"
ACTUAL=$(sha256sum "$TMP" | awk '{print $1}')
if [ "$ACTUAL" != "$EXPECTED" ]; then
  echo "Checksum verification failed" >&2
  echo "Release commit: $RELEASE_COMMIT" >&2
  echo "Expected: $EXPECTED" >&2
  echo "Actual:   $ACTUAL" >&2
  exit 1
fi
python3 -m py_compile "$TMP"
install -m 0755 "$TMP" "$APP"
cat > "$BIN/sophyane" <<EOF
#!/usr/bin/env bash
exec python3 "$APP" "\$@"
EOF
chmod +x "$BIN/sophyane"
case ":$PATH:" in *":$BIN:"*) ;; *) echo 'export PATH="$HOME/.local/bin:$PATH"' >> "$HOME/.bashrc" ;; esac
hash -r 2>/dev/null || true
"$BIN/sophyane" --version
printf '\n✅ Sophyane %s installed from pinned release %s.\n' "$VERSION" "$RELEASE_COMMIT"
