# Sophyane Mesh — multi-device control & resource sharing

When devices run Sophyane (or can accept a clone), they form a **mesh**:

- **WiFi / LAN** discovery and control  
- **USB** inventory + **ADB** (Android) / **SSH** install of Sophyane clones  
- **Shared compute** (offload chat/edge jobs to the strongest peer)  
- **Shared storage** (`~/.local/state/sophyane/mesh_share`)

## Quick start

**Device A (controller + peer):**
```bash
sophyane --mesh-serve --mesh-port 8777
```

**Device B (same WiFi):**
```bash
sophyane --mesh-serve --mesh-port 8777
```

**Discover peers:**
```bash
sophyane --mesh-discover
sophyane --mesh-status
```

**Install Sophyane clone on a peer** (requires confirmation):
```bash
# LAN Linux peer with SSH keys
sophyane --mesh-install <peer_id_or_host> --mesh-ssh-user pi --yes

# Android via USB ADB + Termux
sophyane --mesh-install adb:<serial> --yes
```

**Use another device's compute:**
```bash
sophyane --mesh-compute "Summarize system health in one line"
```

## Transports

| Link | What Sophyane does |
|------|--------------------|
| **WiFi / Ethernet** | UDP presence + HTTP mesh API scan |
| **USB serial** | Detect `/dev/ttyUSB*` / `ttyACM*` (gateway bootstrap) |
| **USB Android** | `adb devices` + Termux install script |
| **SSH over USB Ethernet / LAN** | Full clone install via `install.sh` |

## Security

- Remote shell only allows a **small allowlist** (`uname`, `uptime`, `sophyane --version`, …).  
- Optional shared secret: `export SOPHYANE_MESH_TOKEN=secret` on all peers.  
- **Clone install always requires `--yes`** — never silent.  
- Do not expose mesh ports to the public internet without TLS reverse proxy + token.

## API (port 8777)

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/v1/mesh/hello` | Identify as Sophyane peer |
| GET | `/v1/mesh/capabilities` | CPU/RAM/disk/backends |
| GET | `/v1/mesh/status` | Local node + known peers |
| POST | `/v1/mesh/discover` | Trigger discovery |
| POST | `/v1/mesh/install` | `{"peer_id":"...","yes":true}` |
| POST | `/v1/mesh/compute` | Offload edge chat |
| POST | `/v1/mesh/storage/put` | Share a text blob |
| POST | `/v1/mesh/storage/get` | Fetch shared blob |
| POST | `/v1/mesh/exec` | Allowlisted remote command |

## Resource pooling model

```
┌──────── Device A ────────┐     WiFi/USB      ┌──────── Device B ────────┐
│ Sophyane mesh peer       │◄─────────────────►│ Sophyane mesh peer       │
│ compute + mesh_share     │                   │ compute + mesh_share     │
│ local GPU/CPU/NPU        │                   │ local sensors/storage    │
└──────────────────────────┘                   └──────────────────────────┘
```

Sophyane picks the **best compute peer** (RAM/CPU/GPU hints) for offloaded work and can read/write shared mesh storage on peers.

## Limits

- Cannot force-install on locked iOS / proprietary PLCs without a host OS + SSH/ADB.  
- USB-only MCUs need a gateway Linux board that runs Sophyane.  
- ChromeOS/Crostini networking may limit broadcast; use `--mesh-install` with explicit host or USB ADB.
