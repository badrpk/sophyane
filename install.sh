#!/usr/bin/env sh
set -eu

REPO_URL="https://github.com/badrpk/sophyane.git"
INSTALL_DIR="${SOPHYANE_HOME:-$HOME/.local/share/sophyane}"
BIN_DIR="${SOPHYANE_BIN:-$HOME/.local/bin}"

say() { printf '%s\n' "$*"; }
need() { command -v "$1" >/dev/null 2>&1; }

say "Sophyane cross-platform installer"
say "Install directory: $INSTALL_DIR"

if ! need python3; then
  if need pkg; then
    say "Installing Python and Git with Termux pkg..."
    pkg update -y
    pkg install -y python git
  elif need apt-get; then
    say "Python 3 is required. Installing with apt-get may request your password..."
    sudo apt-get update
    sudo apt-get install -y python3 python3-venv python3-pip git
  elif need brew; then
    say "Installing Python and Git with Homebrew..."
    brew install python git
  else
    say "Python 3.10+ is required. Install it, then rerun this script."
    exit 1
  fi
fi

if ! need git; then
  say "Git is required. Install Git, then rerun this script."
  exit 1
fi

PYTHON="$(command -v python3)"
"$PYTHON" - <<'PY'
import sys
if sys.version_info < (3, 10):
    raise SystemExit("Sophyane requires Python 3.10 or newer.")
print("Python", sys.version.split()[0], "detected")
PY

if [ -d "$INSTALL_DIR/.git" ]; then
  say "Updating existing Sophyane installation..."
  git -C "$INSTALL_DIR" pull --ff-only
else
  mkdir -p "$(dirname "$INSTALL_DIR")"
  git clone "$REPO_URL" "$INSTALL_DIR"
fi

if [ ! -d "$INSTALL_DIR/.venv" ]; then
  "$PYTHON" -m venv "$INSTALL_DIR/.venv"
fi

VENV_PY="$INSTALL_DIR/.venv/bin/python"
"$VENV_PY" -m pip install --upgrade pip setuptools wheel
"$VENV_PY" -m pip install --upgrade "$INSTALL_DIR"

mkdir -p "$BIN_DIR"
cat > "$BIN_DIR/sophyane" <<EOF
#!/usr/bin/env sh
exec "$INSTALL_DIR/.venv/bin/sophyane" "\$@"
EOF
cat > "$BIN_DIR/sophyane-web" <<EOF
#!/usr/bin/env sh
exec "$INSTALL_DIR/.venv/bin/sophyane-web" "\$@"
EOF
cat > "$BIN_DIR/sophyane-doctor" <<EOF
#!/usr/bin/env sh
exec "$INSTALL_DIR/.venv/bin/sophyane-doctor" "\$@"
EOF
chmod +x "$BIN_DIR/sophyane" "$BIN_DIR/sophyane-web" "$BIN_DIR/sophyane-doctor"

case ":$PATH:" in
  *":$BIN_DIR:"*) : ;;
  *)
    SHELL_RC="$HOME/.profile"
    [ -n "${SHELL:-}" ] && [ "$(basename "$SHELL")" = "zsh" ] && SHELL_RC="$HOME/.zshrc"
    printf '\nexport PATH="$HOME/.local/bin:$PATH"\n' >> "$SHELL_RC"
    say "Added $BIN_DIR to PATH in $SHELL_RC"
    ;;
esac

say ""
say "Installation complete."
say "Run: $BIN_DIR/sophyane"
say "Web UI: $BIN_DIR/sophyane-web"
say "Doctor: $BIN_DIR/sophyane-doctor"
say ""
say "On Android use Termux or UserLAnd. On iPhone/iPad, run Sophyane Web on another device and open its LAN URL in Safari."
