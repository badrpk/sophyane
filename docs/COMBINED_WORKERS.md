# Combined workers

Priority of identity (no design duplication):
1. Sophyane — policy, routing, token budget, auto-fetch orchestration
2. Neuron — SNN / STDP source of truth
3. NIFDU — product C++ runtime / harness host

## Flow
Request → Sophyane plans workers → ensure binaries (local path, symlink, or
git clone + cmake of badrpk/nifdu / badrpk/neuron into ~/.local/state/sophyane/native_cache)
→ run native tests/harness → return combined summary (LLM skipped when possible).

## Env
- SOPHYANE_NIFDU_BIN / SOPHYANE_NEURON_BIN
- SOPHYANE_NATIVE_BIN (default ~/.local/bin)
- SOPHYANE_NATIVE_TAG (default v2.1.0)
- SOPHYANE_NIFDU_REPO / SOPHYANE_NEURON_REPO

## Example prompts
- native accelerate: run neuron capabilities
- use neuron for spiking benchmark
- install nifdu and show native status
