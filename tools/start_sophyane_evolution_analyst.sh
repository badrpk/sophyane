#!/data/data/com.termux/files/usr/bin/bash
set -euo pipefail

PORT="${SOPHYANE_EVOLUTION_LOCAL_PORT:-8767}"
HOST="127.0.0.1"
LOG="${HOME}/sophyane-evolution-analyst-${PORT}.log"
PID_FILE="${HOME}/sophyane-evolution-analyst-${PORT}.pid"

LLAMA_SERVER="$(
    {
        command -v llama-server 2>/dev/null || true
        find \
          "$HOME/.local/bin" \
          "$HOME/llama.cpp" \
          "$HOME/.local/share/sophyane/models/llama.cpp" \
          -type f \
          -name llama-server \
          -perm -u+x \
          2>/dev/null
    } |
    awk 'NF && !seen[$0]++' |
    head -1
)"

if [ -z "$LLAMA_SERVER" ]; then
    echo "ERROR: llama-server executable not found."
    exit 1
fi

MODEL="${SOPHYANE_EVOLUTION_LOCAL_MODEL_PATH:-}"

if [ -z "$MODEL" ]; then
    MODEL="$(
        find \
          "$HOME/.local/share/sophyane/models/gguf" \
          "$HOME/models" \
          -maxdepth 2 \
          -type f \
          -iname '*.gguf' \
          ! -iname 'ggml-vocab-*' \
          \( \
            -iname '*coder*' \
            -o -iname '*instruct*' \
            -o -iname '*chat*' \
          \) \
          -printf '%s\t%p\n' \
          2>/dev/null |
        sort -nr |
        cut -f2- |
        head -1
    )"
fi

if [ -z "$MODEL" ] || [ ! -f "$MODEL" ]; then
    echo "ERROR: no suitable coding/instruct GGUF model found."
    echo
    echo "Available non-vocabulary GGUF files:"
    find \
      "$HOME/.local/share/sophyane/models/gguf" \
      "$HOME/models" \
      -maxdepth 2 \
      -type f \
      -iname '*.gguf' \
      ! -iname 'ggml-vocab-*' \
      -print \
      2>/dev/null |
    head -30
    exit 1
fi

if curl -fsS \
    "http://${HOST}:${PORT}/v1/models" \
    >/dev/null 2>&1
then
    echo "EVOLUTION_LOCAL_ANALYST=ALREADY_READY"
    echo "Endpoint: http://${HOST}:${PORT}"
    echo "Requested model: $MODEL"
    exit 0
fi

if [ -f "$PID_FILE" ]; then
    OLD_PID="$(
        cat "$PID_FILE" 2>/dev/null || true
    )"

    if [ -n "$OLD_PID" ]; then
        kill "$OLD_PID" 2>/dev/null || true
    fi

    rm -f "$PID_FILE"
fi

CONTEXT="$(
    printf '%s' \
      "${SOPHYANE_EVOLUTION_LOCAL_CONTEXT:-16384}"
)"
THREADS="$(
    printf '%s' \
      "${SOPHYANE_EVOLUTION_LOCAL_THREADS:-$(nproc)}"
)"

echo "Starting dedicated evolution analyst"
echo "Executable: $LLAMA_SERVER"
echo "Model: $MODEL"
echo "Model size: $(du -h "$MODEL" | cut -f1)"
echo "Endpoint: http://${HOST}:${PORT}"
echo "Context: $CONTEXT"
echo "Threads: $THREADS"
echo "Log: $LOG"

nohup "$LLAMA_SERVER" \
  --model "$MODEL" \
  --host "$HOST" \
  --port "$PORT" \
  --ctx-size "$CONTEXT" \
  --threads "$THREADS" \
  --alias local-evolution \
  >"$LOG" 2>&1 &

PID=$!
echo "$PID" > "$PID_FILE"

for attempt in $(seq 1 180); do
    if curl -fsS \
        "http://${HOST}:${PORT}/v1/models" \
        >/dev/null 2>&1
    then
        echo "EVOLUTION_LOCAL_ANALYST=READY"
        echo "PID: $PID"
        exit 0
    fi

    if ! kill -0 "$PID" 2>/dev/null; then
        echo "ERROR: analyst exited during startup."
        tail -100 "$LOG"
        rm -f "$PID_FILE"
        exit 1
    fi

    sleep 2
done

echo "ERROR: analyst did not become ready."
tail -100 "$LOG"
exit 1
