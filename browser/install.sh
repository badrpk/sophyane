#!/usr/bin/env bash
# Sophyane Browser — install from GitHub (badrpk/sophyane)
# AI search browser shell: ask + sources + agent tools + mesh.
# New-tab mode in your default browser remains available if Chromium is missing.
set -Eeuo pipefail
echo "=== Sophyane Browser (GitHub installer) ==="
echo "Repo: https://github.com/badrpk/sophyane"
if ! command -v curl >/dev/null && ! command -v wget >/dev/null; then
  echo "curl or wget required" >&2; exit 1
fi
if command -v curl >/dev/null; then
  curl -fsSL https://raw.githubusercontent.com/badrpk/sophyane/main/install.sh | sh
else
  wget -qO- https://raw.githubusercontent.com/badrpk/sophyane/main/install.sh | sh
fi
export PATH="$HOME/.local/bin:$PATH"
BIN="$HOME/.local/bin"
mkdir -p "$BIN"
if [ -x "$HOME/.local/share/sophyane/venv/bin/sophyane" ]; then
  cat > "$BIN/sophyane-browser" <<WRAP
#!/usr/bin/env bash
set -Eeuo pipefail
exec "$HOME/.local/share/sophyane/venv/bin/sophyane" --browser "\$@"
WRAP
else
  cat > "$BIN/sophyane-browser" <<'WRAP'
#!/usr/bin/env bash
set -Eeuo pipefail
exec sophyane --browser "$@"
WRAP
fi
chmod 0755 "$BIN/sophyane-browser"
hash -r 2>/dev/null || true
echo ""
echo "✅ Sophyane Browser installed"
echo "   Launch:  sophyane-browser"
echo "   Or:      sophyane --browser"
echo "   Force new tab in default browser:  SOPHYANE_BROWSER_MODE=tab sophyane-browser"
echo "   Download page: https://github.com/badrpk/sophyane/tree/main/browser"
echo "   Releases: https://github.com/badrpk/sophyane/releases"
if [ -n "${DISPLAY:-}${WAYLAND_DISPLAY:-}" ] || [ "$(uname -s)" = "Darwin" ]; then
  echo "Starting Sophyane Browser…"
  "$BIN/sophyane-browser" || true
fi
