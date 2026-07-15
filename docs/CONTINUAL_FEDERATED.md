# Sophyane Continual Federated Training (C++ core)

## Goal

Make the **Sophyane LLM continuously better** by:

1. Starting from **existing local model weights** (GGUF / `local_gguf`)
2. Running **parameter-efficient continual training** on each install
3. Pooling compute across **millions of user devices** via mesh (opt-in)
4. Keeping the **training hot path in pure C++** for hardware efficiency

## What this is (and is not)

| Is | Is not |
|----|--------|
| Federated **PEFT / LoRA-style adapters** on top of the base GGUF | Full from-scratch training of a 70B foundation model on every phone |
| C++17 local-step + FedAvg (`sophyane-train-core`) | Python matrix math in the hot path |
| Opt-in user compute contribution | Silent use of devices without consent |
| Adapter deltas shared over mesh | Uploading private chat text by default |
| Continuous rounds (CLI, mesh, appliance boot tick) | A replacement for datacenter pretraining alone |

Honest path to “best LLM”: massive coordinated federated PEFT + selective full-weight refinement on trusted aggregators, seeded from strong open bases (Qwen/Llama/etc.). This release ships the **device-side continuous loop** and **C++ aggregation core**.

## Architecture

```
┌─────────────────┐     experience digests      ┌──────────────────────┐
│ User chats/tools│ ──────────────────────────► │ Python orchestration │
└─────────────────┘   (privacy-preserving)      └──────────┬───────────┘
                                                           │ exec
                                                           ▼
                                                ┌──────────────────────┐
                                                │ sophyane-train-core  │
                                                │ (C++17 only)         │
                                                │ local-step / FedAvg  │
                                                └──────────┬───────────┘
                                                           │ adapter.bin
                           mesh :8777                      ▼
┌──────────────┐  contribute deltas  ┌─────────────────────────────────┐
│ Peer devices │ ◄──────────────────► │ Global adapter (FedAvg merge)   │
│ (millions)   │                      │ attached to base_hash of GGUF  │
└──────────────┘                      └─────────────────────────────────┘
```

Base GGUF weights **stay local**. Only small adapter tensors move.

## Commands

```bash
# Build pure C++ core (also auto-built on first train)
sophyane --train-build-core

# Opt this device into continuous contribution
sophyane --train-opt-in

# Record experience (stored as digests unless share_raw_text)
sophyane --train-record "user asked how to fix cmake on ARM"

# One local C++ step on existing weights fingerprint
sophyane --train-step

# Full round: local step → mesh publish → FedAvg
sophyane --train-round

# Status
sophyane --train-status
```

Environment:

| Variable | Meaning |
|----------|---------|
| `SOPHYANE_TRAIN_OPT_IN=1` | Opt-in without writing config |
| `SOPHYANE_TRAIN_ON_BOOT=1` | Appliance boot runs a train tick if opted in |
| `SOPHYANE_TRAIN_RANK` | LoRA rank (default 8) |

## C++ core API

```bash
sophyane-train-core status
sophyane-train-core local-step --experience FILE --out DIR --base-hash H --peer ID
sophyane-train-core aggregate --deltas DIR --out DIR
sophyane-train-core verify --dir DIR
```

Sources: `sdk/cpp/continual/` (header-only math + `train_core.cpp`).

## Mesh / HTTP

- `GET  /v1/mesh/train/status`
- `POST /v1/mesh/train/contribute` — ingest peer adapter
- `POST /v1/mesh/train/step` | `/round` | `/aggregate`
- `GET  /v1/train/status` (Hardware API)
- `POST /v1/train/step` | `/round`

## Privacy

- **Default off** until `--train-opt-in`
- Experiences stored as **digests** (hash + lengths), not full private text
- Mesh shares **adapter weights**, not chats
- Set `share_raw_text` only if the user explicitly wants richer local text features

## Path to stronger models

1. More opted-in devices → more diverse PEFT signal  
2. Trusted aggregators run FedAvg / FedProx at scale  
3. Periodically distill global adapters into refreshed GGUF releases  
4. Publish new base checkpoints for all installs to pull  

That flywheel is how a distributed Sophyane network competes with centralized labs — not by pretending every edge phone full-trains a frontier model alone.
