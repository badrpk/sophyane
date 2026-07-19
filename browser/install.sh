#!/usr/bin/env bash
# Compatibility link: all Sophyane editions now use the same universal installer.
set -Eeuo pipefail
URL="https://raw.githubusercontent.com/badrpk/sophyane/main/install.sh"
if command -v curl >/dev/null 2>&1; then
  curl -fsSL "$URL" | bash
elif command -v wget >/dev/null 2>&1; then
  wget -qO- "$URL" | bash
else
  echo "curl or wget is required" >&2
  exit 1
fi
exec "${SOPHYANE_BIN:-$HOME/.local/bin}/sophyane-browser" "$@"
