#!/usr/bin/env bash
# Sophyane Local installer — installs the Local edition directly from its GitHub branch.
# No cloud API key is required. The first run presents the supported local-model catalog.
set -Eeuo pipefail

REPO="https://github.com/badrpk/sophyane.git"
REF="${SOPHYANE_LOCAL_REF:-fix/local-llm-termux-reliability}"
BASE="${SOPHYANE_HOME:-$HOME/.local/share/sophyane-local}"
BIN="${SOPHYANE_BIN:-$HOME/.local/bin}"
VENV="$BASE/venv"
SOURCE="$BASE/source"
LOG_DIR="${TMPDIR:-$HOME/.cache/sophyane-local}/logs"

fail() { printf 'Error: %s\n' "$*" >&2; exit 1; }
info() { printf '%s\n' "$*"; }
need_cmd() { command -v "$1" >/dev/null 2>&1 || fail "'$1' is required."; }

need_cmd git
need_cmd python3
mkdir -p "$BASE" "$BIN" "$LOG_DIR"

info "=== Sophyane Local installer ==="
info "Edition:       Local (GGUF / Ollama, no API key)"
info "Source branch: $REF"
info "Install root:  $BASE"

rm -rf "$SOURCE"
git clone --quiet --depth 1 --branch "$REF" --single-branch "$REPO" "$SOURCE"
COMMIT="$(git -C "$SOURCE" rev-parse HEAD)"

info "Creating isolated Python environment..."
rm -rf "$VENV"
python3 -m venv "$VENV"
"$VENV/bin/python" -m pip install --disable-pip-version-check --upgrade pip setuptools wheel
"$VENV/bin/python" -m pip install --disable-pip-version-check "$SOURCE"

cat > "$BIN/sophyane-local" <<EOF
#!/usr/bin/env bash
set -Eeuo pipefail
export SOPHYANE_EDITION=local
exec "$VENV/bin/sophyane" "\$@"
EOF
chmod 0755 "$BIN/sophyane-local"

# On a Local-only phone install, make `sophyane` point at the Local edition too.
ln -sfn "$BIN/sophyane-local" "$BIN/sophyane"

case ":$PATH:" in
  *":$BIN:"*) ;;
  *)
    printf '\n# Sophyane Local CLI\nexport PATH="%s:$PATH"\n' "$BIN" >> "$HOME/.bashrc"
    export PATH="$BIN:$PATH"
    ;;
esac

hash -r 2>/dev/null || true

info "Verifying install..."
"$BIN/sophyane-local" --version
"$BIN/sophyane-local" --doctor >"$LOG_DIR/doctor.log" 2>&1 || \
  info "Doctor completed with notes: $LOG_DIR/doctor.log"

cat > "$BASE/installed-local" <<EOF
EDITION=local
REF=$REF
COMMIT=$COMMIT
INSTALLED_AT=$(date -u '+%Y-%m-%dT%H:%M:%SZ')
REPO=https://github.com/badrpk/sophyane
EOF

info ""
info "✅ Sophyane Local installed"
info "   Commit: $COMMIT"
info "   CLI:    $BIN/sophyane-local"
info "   Alias:  $BIN/sophyane"
info "   API key: not required"
info ""
info "Next step:"
info "  sophyane"
info ""
info "Choose 'Local GGUF' to see every supported Hugging Face model, its"
info "download size, minimum RAM, compatibility status, and source URL."
