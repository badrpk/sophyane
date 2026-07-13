#!/usr/bin/env bash
set -Eeuo pipefail
VERSION="9.0.4"
RELEASE_COMMIT="3f64256808a5cc0e007a00d8add8689e615d82ea"
ENTRY="sophyane-9.0.4.py"
EXPECTED_BLOB="f8547d8338cf80f96c412be3fc6b1e60d6bfcb04"
RAW="https://raw.githubusercontent.com/badrpk/sophyane/${RELEASE_COMMIT}"
BASE="$HOME/.local/share/sophyane"
BIN="$HOME/.local/bin"
APP="$BASE/sophyane.py"
TMP="$(mktemp)"
cleanup(){ rm -f "$TMP"; }
trap cleanup EXIT
mkdir -p "$BASE" "$BIN" "$HOME/.config/sophyane" "$HOME/.local/state/sophyane"
curl -fsSL "$RAW/$ENTRY" -o "$TMP"
SIZE=$(wc -c < "$TMP" | tr -d ' ')
ACTUAL_BLOB=$( { printf 'blob %s\0' "$SIZE"; cat "$TMP"; } | sha1sum | awk '{print $1}')
if [ "$ACTUAL_BLOB" != "$EXPECTED_BLOB" ]; then
  echo "Integrity verification failed" >&2
  echo "Release commit: $RELEASE_COMMIT" >&2
  echo "Expected blob: $EXPECTED_BLOB" >&2
  echo "Actual blob:   $ACTUAL_BLOB" >&2
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
