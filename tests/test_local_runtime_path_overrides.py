import json
import os
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _probe(env):
    code = r'''
import json
from sophyane import local_runtime as r

print(json.dumps({
    "state": str(r.STATE_DIR),
    "local_state": str(r.LOCAL_STATE_FILE),
    "gguf_state": str(r.GGUF_STATE_FILE),
    "bin": str(r.BIN_DIR),
    "models": str(r.MODELS_DIR),
    "gguf": str(r.GGUF_DIR),
    "llama": str(r.LLAMA_DIR),
    "llama_runtime": str(r.LLAMA_RUNTIME_DIR),
}))
'''
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=True,
    )
    return json.loads(result.stdout)


def test_local_runtime_paths_honor_transaction_overrides(tmp_path):
    state = tmp_path / "state"
    native_bin = tmp_path / "bin"
    models = tmp_path / "models"

    env = os.environ.copy()
    env.update(
        {
            "SOPHYANE_STATE_DIR": str(state),
            "SOPHYANE_NATIVE_BIN": str(native_bin),
            "SOPHYANE_MODELS_DIR": str(models),
        }
    )

    paths = _probe(env)

    assert paths["state"] == str(state)
    assert paths["local_state"] == str(state / "local_runtime.json")
    assert paths["gguf_state"] == str(state / "gguf_runtime.json")

    assert paths["bin"] == str(native_bin)

    assert paths["models"] == str(models)
    assert paths["gguf"] == str(models / "gguf")
    assert paths["llama"] == str(models / "llama.cpp")
    assert paths["llama_runtime"] == str(models / "llama.cpp" / "runtime")


def test_local_runtime_paths_keep_existing_defaults(monkeypatch):
    env = os.environ.copy()
    env.pop("SOPHYANE_STATE_DIR", None)
    env.pop("SOPHYANE_NATIVE_BIN", None)
    env.pop("SOPHYANE_MODELS_DIR", None)

    paths = _probe(env)

    home = Path.home()

    assert paths["state"] == str(home / ".local/state/sophyane")
    assert paths["bin"] == str(home / ".local/bin")
    assert paths["models"] == str(home / ".local/share/sophyane/models")
