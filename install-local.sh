#!/usr/bin/env bash
# Sophyane Local one-shot installer and runtime manager.
# Installs Sophyane, preserves downloaded GGUF models, builds a native backend
# on Android/Termux, verifies inference, starts llama-server, and persists state.
set -Eeuo pipefail

REPO="https://github.com/badrpk/sophyane.git"
REF="${SOPHYANE_LOCAL_REF:-fix/local-llm-termux-reliability}"
BASE="${SOPHYANE_HOME:-$HOME/.local/share/sophyane-local}"
BIN="${SOPHYANE_BIN:-$HOME/.local/bin}"
VENV="$BASE/venv"
SOURCE="$BASE/source"
CACHE_BASE="${XDG_CACHE_HOME:-$HOME/.cache}/sophyane-local"
LOG_DIR="$CACHE_BASE/logs"
MODELS_BASE="$HOME/.local/share/sophyane/models"
GGUF_DIR="$MODELS_BASE/gguf"
LLAMA_BASE="$MODELS_BASE/llama.cpp"
LLAMA_SRC="$LLAMA_BASE/source-termux"
LLAMA_RUNTIME="$LLAMA_BASE/runtime"
STATE_DIR="$HOME/.local/state/sophyane"
CONFIG_DIR="$HOME/.config/sophyane"
SERVER_HOST="127.0.0.1"
SERVER_PORT="${SOPHYANE_LLAMA_PORT:-8766}"
SERVER_URL="http://$SERVER_HOST:$SERVER_PORT"

fail() {
  printf '\nError: %s\n' "$*" >&2
  printf 'Logs: %s\n' "$LOG_DIR" >&2
  exit 1
}
info() { printf '%s\n' "$*"; }
need_cmd() { command -v "$1" >/dev/null 2>&1 || fail "'$1' is required."; }

mkdir -p "$BASE" "$BIN" "$LOG_DIR" "$GGUF_DIR" "$STATE_DIR" "$CONFIG_DIR"
need_cmd git
need_cmd python3

info "=== Sophyane Local one-shot setup ==="
info "Edition:       Local GGUF / Ollama (no API key)"
info "Source branch: $REF"
info "Install root:  $BASE"
info "Models:        $GGUF_DIR"

# Install/update Sophyane without removing cached models.
rm -rf "$SOURCE"
git clone --quiet --depth 1 --branch "$REF" --single-branch "$REPO" "$SOURCE"
COMMIT="$(git -C "$SOURCE" rev-parse HEAD)"

info "Installing Sophyane Local runtime..."
rm -rf "$VENV"
python3 -m venv "$VENV"
"$VENV/bin/python" -m pip install --disable-pip-version-check --upgrade pip setuptools wheel
"$VENV/bin/python" -m pip install --disable-pip-version-check "$SOURCE"

cat > "$BIN/sophyane-local" <<EOF
#!/usr/bin/env bash
set -Eeuo pipefail
export SOPHYANE_EDITION=local
export SOPHYANE_LLAMA_SERVER="$SERVER_URL"
exec "$VENV/bin/sophyane" "\$@"
EOF
chmod 0755 "$BIN/sophyane-local"
ln -sfn "$BIN/sophyane-local" "$BIN/sophyane"

case ":$PATH:" in
  *":$BIN:"*) ;;
  *)
    printf '\n# Sophyane Local CLI\nexport PATH="%s:$PATH"\n' "$BIN" >> "$HOME/.bashrc"
    export PATH="$BIN:$PATH"
    ;;
esac
hash -r 2>/dev/null || true

is_termux=0
if [ -n "${TERMUX_VERSION:-}" ] || [ -n "${PREFIX:-}" ] && [ "${PREFIX:-}" = "/data/data/com.termux/files/usr" ]; then
  is_termux=1
fi

native_backend_ok() {
  [ -x "$LLAMA_RUNTIME/llama-cli" ] || return 1
  [ -x "$LLAMA_RUNTIME/llama-server" ] || return 1
  "$LLAMA_RUNTIME/llama-cli" --version >/dev/null 2>&1 || return 1
  "$LLAMA_RUNTIME/llama-server" --version >/dev/null 2>&1 || return 1
}

if [ "$is_termux" -eq 1 ]; then
  info "Platform: Android/Termux detected; using native Bionic-compatible llama.cpp."
  if ! native_backend_ok; then
    info "Installing native build dependencies..."
    pkg install -y clang cmake ninja git curl >"$LOG_DIR/pkg-install.log" 2>&1 || \
      fail "Could not install Termux build dependencies."

    info "Building optimized native llama.cpp backend..."
    rm -rf "$LLAMA_SRC"
    git clone --quiet --depth 1 https://github.com/ggml-org/llama.cpp.git "$LLAMA_SRC" || \
      fail "Could not clone llama.cpp."

    jobs="$(getconf _NPROCESSORS_ONLN 2>/dev/null || nproc 2>/dev/null || echo 2)"
    [ "$jobs" -gt 8 ] 2>/dev/null && jobs=8

    cmake -S "$LLAMA_SRC" -B "$LLAMA_SRC/build" -G Ninja \
      -DCMAKE_BUILD_TYPE=Release \
      -DGGML_OPENMP=OFF \
      -DGGML_NATIVE=ON \
      -DLLAMA_CURL=OFF \
      -DBUILD_SHARED_LIBS=OFF \
      -DLLAMA_BUILD_TESTS=OFF \
      -DLLAMA_BUILD_EXAMPLES=ON \
      -DLLAMA_BUILD_SERVER=ON \
      >"$LOG_DIR/llama-cmake.log" 2>&1 || \
      fail "llama.cpp configuration failed."

    cmake --build "$LLAMA_SRC/build" --target llama-cli llama-server -j"$jobs" \
      >"$LOG_DIR/llama-build.log" 2>&1 || \
      fail "llama.cpp native build failed."

    mkdir -p "$LLAMA_RUNTIME"
    rm -rf "$LLAMA_RUNTIME"/*
    cp "$LLAMA_SRC/build/bin/llama-cli" "$LLAMA_RUNTIME/llama-cli"
    cp "$LLAMA_SRC/build/bin/llama-server" "$LLAMA_RUNTIME/llama-server"
    chmod 0755 "$LLAMA_RUNTIME/llama-cli" "$LLAMA_RUNTIME/llama-server"
  else
    info "Using verified cached native llama.cpp backend."
  fi
else
  info "Platform: non-Termux; Sophyane will select the compatible local backend."
fi

if [ -x "$LLAMA_RUNTIME/llama-cli" ]; then
  ln -sfn "$LLAMA_RUNTIME/llama-cli" "$BIN/llama-cli"
fi
if [ -x "$LLAMA_RUNTIME/llama-server" ]; then
  ln -sfn "$LLAMA_RUNTIME/llama-server" "$BIN/llama-server"
fi

if [ "$is_termux" -eq 1 ] && ! native_backend_ok; then
  fail "Native Termux llama.cpp verification failed."
fi

# Find the newest/largest completed GGUF, if a user already selected one.
MODEL_PATH=""
if find "$GGUF_DIR" -maxdepth 1 -type f -name '*.gguf' -size +1M -print -quit 2>/dev/null | grep -q .; then
  MODEL_PATH="$(find "$GGUF_DIR" -maxdepth 1 -type f -name '*.gguf' -size +1M -printf '%T@ %p\n' 2>/dev/null | sort -nr | head -n1 | cut -d' ' -f2-)"
fi

# Android toybox/find may not support -printf; portable fallback.
if [ -z "$MODEL_PATH" ]; then
  for candidate in "$GGUF_DIR"/*.gguf; do
    [ -f "$candidate" ] || continue
    [ "$(wc -c < "$candidate" 2>/dev/null || echo 0)" -gt 1048576 ] || continue
    MODEL_PATH="$candidate"
    break
  done
fi

MODEL_KEY=""
BACKEND="not-configured"
HEALTH="not-run"
INFERENCE="not-run"
THREADS="$(getconf _NPROCESSORS_ONLN 2>/dev/null || nproc 2>/dev/null || echo 2)"
[ "$THREADS" -gt 8 ] 2>/dev/null && THREADS=8
RAM_MB="$(awk '/MemTotal:/ {print int($2/1024)}' /proc/meminfo 2>/dev/null || echo 2048)"
if [ "$RAM_MB" -lt 3500 ]; then CONTEXT=2048; elif [ "$RAM_MB" -lt 8000 ]; then CONTEXT=4096; else CONTEXT=8192; fi

if [ -n "$MODEL_PATH" ]; then
  MODEL_KEY="$(basename "$MODEL_PATH" .gguf | sed -E 's/-instruct-q[0-9_]+.*$//I; s/-q[0-9_]+.*$//I')"
  info "Found selected GGUF: $(basename "$MODEL_PATH")"
  info "Verifying native one-shot inference..."

  if timeout 180 "$LLAMA_RUNTIME/llama-cli" \
      -m "$MODEL_PATH" -c "$CONTEXT" -t "$THREADS" -n 8 \
      -p "Reply with exactly OK" --no-display-prompt \
      >"$LOG_DIR/llama-cli-smoke.log" 2>&1; then
    INFERENCE="passed"
  else
    fail "The selected GGUF could not complete native llama-cli inference."
  fi

  pkill -f "llama-server.*$SERVER_PORT" 2>/dev/null || true
  info "Starting optimized llama-server on $SERVER_URL..."
  nohup "$LLAMA_RUNTIME/llama-server" \
    -m "$MODEL_PATH" --host "$SERVER_HOST" --port "$SERVER_PORT" \
    -c "$CONTEXT" -t "$THREADS" --parallel 1 \
    >"$STATE_DIR/llama-server.log" 2>&1 &
  SERVER_PID=$!
  printf '%s\n' "$SERVER_PID" > "$STATE_DIR/llama-server.pid"

  ready=0
  for _ in $(seq 1 120); do
    if curl -fsS "$SERVER_URL/health" >/dev/null 2>&1 || \
       curl -fsS "$SERVER_URL/v1/models" >/dev/null 2>&1; then
      ready=1
      break
    fi
    sleep 1
  done

  if [ "$ready" -eq 1 ]; then
    BACKEND="llama-server"
    HEALTH="passed"
  else
    kill "$SERVER_PID" 2>/dev/null || true
    BACKEND="llama-cli"
    HEALTH="server-failed-cli-passed"
    info "llama-server did not become healthy; verified llama-cli fallback retained."
  fi

  "$VENV/bin/python" - "$MODEL_KEY" "$MODEL_PATH" "$BACKEND" "$SERVER_URL" "$CONTEXT" "$THREADS" <<'PY'
import json
import sys
import time
from pathlib import Path

model, gguf, backend, endpoint, context, threads = sys.argv[1:]
home = Path.home()
state_dir = home / ".local" / "state" / "sophyane"
config_dir = home / ".config" / "sophyane"
state_dir.mkdir(parents=True, exist_ok=True)
config_dir.mkdir(parents=True, exist_ok=True)
cli = home / ".local" / "bin" / "llama-cli"
server = home / ".local" / "bin" / "llama-server"
payload = {
    "provider": "local_gguf",
    "model": model,
    "gguf_path": gguf,
    "backend": backend,
    "endpoint": endpoint,
    "cli": str(cli),
    "server": str(server),
    "context": int(context),
    "threads": int(threads),
    "updated": time.time(),
}
(state_dir / "gguf_runtime.json").write_text(json.dumps(payload, indent=2) + "\n")
(state_dir / "local_runtime.json").write_text(json.dumps(payload, indent=2) + "\n")
config = {
    "provider": "local_gguf",
    "model": model,
    "timeout": 300,
    "temperature": 0.2,
    "max_tokens": 350,
}
(config_dir / "config.json").write_text(json.dumps(config, indent=2) + "\n")
llm = {
    "active_provider": "local_gguf",
    "fallback_order": ["local_gguf"],
    "providers": {
        "local_gguf": {
            "enabled": True,
            "api_key_env": [],
            "model": model,
            "base_url": endpoint,
        }
    },
}
(config_dir / "llm.json").write_text(json.dumps(llm, indent=2) + "\n")
PY
else
  info "No completed GGUF found yet. Sophyane will present the compatible model catalog."
fi

"$BIN/sophyane-local" --version
"$BIN/sophyane-local" --doctor >"$LOG_DIR/doctor.log" 2>&1 || true

cat > "$BASE/installed-local" <<EOF
EDITION=local
REF=$REF
COMMIT=$COMMIT
INSTALLED_AT=$(date -u '+%Y-%m-%dT%H:%M:%SZ')
MODEL=$MODEL_KEY
MODEL_PATH=$MODEL_PATH
BACKEND=$BACKEND
SERVER_URL=$SERVER_URL
CONTEXT=$CONTEXT
THREADS=$THREADS
API_KEY_REQUIRED=no
REPO=https://github.com/badrpk/sophyane
EOF

info ""
info "✅ Sophyane Local setup complete"
info "   Commit:      $COMMIT"
info "   Platform:    $([ "$is_termux" -eq 1 ] && echo 'Android Termux' || uname -s) $(uname -m)"
info "   RAM:         ${RAM_MB} MB"
info "   Model:       ${MODEL_KEY:-select on first run}"
info "   GGUF:        ${MODEL_PATH:-not selected}"
info "   Backend:     $BACKEND"
info "   Context:     $CONTEXT"
info "   Threads:     $THREADS"
info "   Health:      $HEALTH"
info "   Inference:   $INFERENCE"
info "   API key:     not required"
info "   Logs:        $LOG_DIR"
info ""
if [ -z "$MODEL_PATH" ]; then
  info "Run: sophyane"
  info "Then choose Local GGUF and select a compatible model."
else
  info "Test: sophyane 'Reply with exactly: Sophyane Local works'"
fi
