#!/usr/bin/env bash
set -Eeuo pipefail
VERSION="10.0.0"
RELEASE_COMMIT="5f0fd2343199b0fc88fce8ae0797b51e974dd80a"
ENTRY="sophyane-10.0.0.py"
EXPECTED_BLOB="2ff60a22bc3b31e9958a1d9c2ae0091a93c98dd7"
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
"$BIN/sophyane" self-test
printf '\n✅ Sophyane %s installed from pinned release %s.\n' "$VERSION" "$RELEASE_COMMIT"
