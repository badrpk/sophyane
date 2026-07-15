# Sophyane Hardware & Software API

Sophyane exposes a **unified API** so the same agent intelligence works across
chip ecosystems and languages.

## Scope (read this)

| Layer | What Sophyane does |
|-------|--------------------|
| **Host OS** (Linux/Windows/macOS/Android Termux) | Runs the agent, tools, local models |
| **CPU/GPU/NPU vendors** (NVIDIA, Intel, AMD, Qualcomm, Arm, Apple, …) | Detects stacks; recommends backends (CUDA, ROCm, OpenVINO, Metal, QNN, …) |
| **Memory vendors** (Micron, SK hynix, Samsung memory) | Host memory/storage awareness — not bare-die execution |
| **Foundries** (TSMC, GlobalFoundries) | Catalog only (they fabricate other vendors’ chips) |
| **MCU/PLC chips** (TI, NXP, ST, Infineon, Renesas) | Via **gateway host** + open adapters (Modbus/MQTT/OPC-UA) |

Sophyane is **not** a replacement for vendor IDE firmware flash tools. It is the
**intelligence layer** that integrates with those toolchains and open-source runtimes.

## Top vendor catalog (20+)

NVIDIA · Intel · AMD · Qualcomm · AMD Xilinx · Apple · Arm · Broadcom · MediaTek ·
Samsung · Micron · SK hynix · Texas Instruments · NXP · Infineon · STMicro ·
Analog Devices · Marvell · IBM · TSMC · GlobalFoundries · Renesas · Microchip ·
Raspberry Pi (Broadcom SoC)

## Languages

| Language | Support |
|----------|---------|
| **Python** | Native package `sophyane` + `sophyane.hardware_api` |
| **C++** | Header client `sdk/cpp/include/sophyane_client.hpp` (libcurl) |
| **JavaScript** | `sdk/js/sophyane-client.js` (Node 18+ / browser fetch) |

## HTTP API (default port 8770)

```bash
sophyane --hardware-api --hardware-port 8770
```

| Method | Path | Description |
|--------|------|-------------|
| GET | `/v1/hardware/health` | Health + platform |
| GET | `/v1/hardware/platform` | Equipment class probe |
| GET | `/v1/hardware/compat` | Full vendor + software report |
| GET | `/v1/hardware/backends` | Recommended backends |
| GET | `/v1/hardware/software` | Open-source stack detection |
| POST | `/v1/hardware/chat` | `{"message":"...","edge":true}` |
| POST | `/v1/hardware/rpc` | `{"method":"hardware","params":{}}` |

## CLI

```bash
sophyane --hardware          # text compatibility report
sophyane --hardware-json     # JSON report
sophyane --platform
sophyane --edge-health
sophyane --hardware-api      # serve multi-language API
```

## Open-source / freeware stacks

llama.cpp · ONNX Runtime · PyTorch · TensorFlow/TFLite · Ollama · OpenVINO ·
pymodbus · Paho MQTT · asyncua/open62541 · Node.js · g++/clang/cmake

## Proprietary vendor stacks (integration surfaces)

CUDA / TensorRT · ROCm/HIP · oneAPI/OpenVINO · Metal/CoreML · Hexagon/QNN ·
JetPack · Vitis · STM32Cube · MCUXpresso · CCS (TI)

## Examples

```bash
# Python
python sdk/python/example_hardware_api.py

# JS (API server must be running)
node sdk/js/example.mjs

# C++
cd sdk/cpp && cmake -B build && cmake --build build
./build/hello_sophyane
```
