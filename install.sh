#!/usr/bin/env bash
set -Eeuo pipefail
RAW="https://raw.githubusercontent.com/badrpk/sophyane/main"
BASE="$HOME/.local/share/sophyane"
OLD_BASE="$HOME/.local/share/sophyane-v8"
BIN="$HOME/.local/bin"
APP="$BASE/sophyane.py"
MANIFEST="$(mktemp)"
TMP="$(mktemp)"
mkdir -p "$BASE" "$BIN" "$HOME/.config/sophyane" "$HOME/.local/state/sophyane"
cleanup(){ rm -f "$MANIFEST" "$TMP"; }
trap cleanup EXIT
curl -fsSL "$RAW/manifest.json" -o "$MANIFEST"
VERSION=$(python3 -c 'import json,sys;print(json.load(open(sys.argv[1]))["version"])' "$MANIFEST")
ENTRY=$(python3 -c 'import json,sys;print(json.load(open(sys.argv[1]))["entrypoint"])' "$MANIFEST")
EXPECTED=$(python3 -c 'import json,sys;print(json.load(open(sys.argv[1]))["sha256"])' "$MANIFEST")
curl -fsSL "$RAW/$ENTRY" -o "$TMP"
ACTUAL=$(sha256sum "$TMP" | awk '{print $1}')
[ "$ACTUAL" = "$EXPECTED" ] || { echo "Checksum verification failed" >&2; exit 1; }
python3 -m py_compile "$TMP"
if [ -x "$BIN/sophyane" ] && [ ! -e "$BIN/sophyane-legacy" ]; then cp -a "$BIN/sophyane" "$BIN/sophyane-legacy"; fi
install -m 0755 "$TMP" "$APP"
cat > "$BIN/sophyane" <<EOF
#!/usr/bin/env bash
exec python3 "$APP" "\$@"
EOF
chmod +x "$BIN/sophyane"
case ":$PATH:" in *":$BIN:"*) ;; *) echo 'export PATH="$HOME/.local/bin:$PATH"' >> "$HOME/.bashrc" ;; esac
if [ -d "$OLD_BASE" ] && [ "$OLD_BASE" != "$BASE" ]; then
  mkdir -p "$HOME/.local/share/sophyane-backups"
  mv "$OLD_BASE" "$HOME/.local/share/sophyane-backups/sophyane-v8-$(date +%Y%m%d-%H%M%S)" 2>/dev/null || true
fi
"$BIN/sophyane" self-test
printf '\n✅ Sophyane %s installed.\n\nRun:\n  sophyane\n  sophyane build "make a snake game in browser"\n  sophyane web\n  sophyane --version\n' "$VERSION"
