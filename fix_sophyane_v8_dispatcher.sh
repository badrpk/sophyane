#!/usr/bin/env bash
set -Eeuo pipefail

BIN="$HOME/.local/bin"
CURRENT="$BIN/sophyane"
LEGACY="$BIN/sophyane-legacy"
GRAPH="$BIN/sophyane-graph"

mkdir -p "$BIN"

if [ ! -x "$GRAPH" ]; then
  echo "ERROR: $GRAPH not found. Install Sophyane v8 graph layer first." >&2
  exit 1
fi

if [ -e "$CURRENT" ] && [ ! -e "$LEGACY" ]; then
  cp -a "$CURRENT" "$LEGACY"
fi

cat > "$CURRENT.tmp" <<'EOF'
#!/usr/bin/env bash
set -e
if [ "${1:-}" = "graph" ]; then
  shift
  exec "$HOME/.local/bin/sophyane-graph" "$@"
fi
if [ -x "$HOME/.local/bin/sophyane-legacy" ]; then
  exec "$HOME/.local/bin/sophyane-legacy" "$@"
fi
echo "Sophyane legacy launcher not found. Use: sophyane graph --help" >&2
exit 1
EOF

chmod +x "$CURRENT.tmp"
rm -f "$CURRENT"
install -m 0755 "$CURRENT.tmp" "$CURRENT"
rm -f "$CURRENT.tmp"

# Remove duplicate ~/.local/bin PATH entries from this shell only.
case ":$PATH:" in
  *":$BIN:"*) ;;
  *) export PATH="$BIN:$PATH" ;;
esac

hash -r 2>/dev/null || true

printf 'Dispatcher installed: %s\n' "$CURRENT"
"$CURRENT" graph --version
"$CURRENT" graph self-test
