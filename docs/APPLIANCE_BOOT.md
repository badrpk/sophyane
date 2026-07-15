# Sophyane Appliance — install & boot on processors / SoCs

## What “installed on chips” means

Sophyane boots as an **AI appliance** on any **Linux-capable processor**
(ARM/x86 SoCs, SBCs, industrial gateways, phones with Termux, cloud VMs, PCs):

| Layer | Sophyane |
|-------|----------|
| Silicon without OS (bare MCU) | Use a gateway board running Linux + Sophyane |
| Linux SoC / SBC / gateway | **Full appliance boot** (`sophyane --boot`) |
| Desktop / cloud | Same appliance or service units |

It is **not** a from-scratch silicon bootloader. It is an **OS-like agent runtime**
that starts after the board’s Linux kernel, brings up **Ethernet and Wi‑Fi**,
and runs the AI Kernel, mesh, and APIs.

## Chip / board install

```bash
# On the target board (Raspberry Pi, industrial ARM, x86, Termux, …)
curl -fsSL https://raw.githubusercontent.com/badrpk/sophyane/main/install.sh | sh

# Write helper + systemd user unit
sophyane --install-chip
sophyane --install-appliance-unit
systemctl --user daemon-reload
systemctl --user enable --now sophyane-appliance.service
```

Or one-shot boot:

```bash
# Ethernet (DHCP) + optional Wi‑Fi
export SOPHYANE_WIFI_SSID='MyWifi'
export SOPHYANE_WIFI_PSK='secret'
sophyane --boot --wifi-ssid "$SOPHYANE_WIFI_SSID" --wifi-psk "$SOPHYANE_WIFI_PSK"
```

Boot starts:

1. Platform probe  
2. Network bring-up (**cable Ethernet** via NetworkManager/dhclient, **Wi‑Fi** via nmcli/wpa)  
3. AI Kernel  
4. Hardware API `:8770`  
5. Mesh peer `:8777`  
6. Optional browser (`--boot-browser`)  
7. Self-improvement heartbeat block  

## Verify everything

```bash
sophyane --audit
sophyane --doctor
sophyane --platform
sophyane --mesh-status
sophyane --hardware
sophyane --improve-status
```

## Networking

| Medium | Support |
|--------|---------|
| Ethernet cable | `nmcli dev connect` / `dhclient` / `udhcpc` on `eth*` / `en*` |
| Wi‑Fi | `nmcli dev wifi connect SSID password …` or `wpa_supplicant` conf |
| USB net / ADB | Mesh discovery + clone install |
| Online check | ping 1.1.1.1 / 8.8.8.8 |

Boot is **idempotent**: if Hardware API `:8770` or Mesh `:8777` already listen,
a second `--boot` reuses them instead of failing with “Address already in use”.

Containers (ChromeOS Crostini, Docker) often only expose **Ethernet** (`eth0`);
Wi‑Fi radio is host-managed. On bare-metal SBCs both cable and Wi‑Fi interfaces
appear when hardware is present. Use env vars or flags for Wi‑Fi join:

```bash
sophyane --boot --wifi-ssid MyNet --wifi-psk 'secret'
# or
export SOPHYANE_WIFI_SSID=MyNet SOPHYANE_WIFI_PSK=secret
sophyane --boot
```

## Feature map (integrated)

| Requested capability | Command / module |
|---------------------|------------------|
| AI Kernel | `--kernel` |
| Hardware vendors / CUDA stacks | `--hardware` |
| Python/C++/JS API | `--hardware-api` |
| Browser | `--browser` / `sophyane-browser` |
| Web scrape + learn | `--fetch` / `--learn` |
| Daily self-improve chain | `--improve-export` + GitHub Action |
| Mesh USB/WiFi control | `--mesh-serve` / `--mesh-discover` |
| Apps web/Android/Harmony/iOS | `--create-app` |
| ERP Oracle/SAP/… | `--erp` |
| Appliance on SoC | `--boot` / `--install-chip` |
