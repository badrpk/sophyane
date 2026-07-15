# Sophyane AI Kernel

## What it is

The **Sophyane AI Kernel** is a **userspace, AI-focused control plane** — not a
replacement for the Linux kernel. It aims to be *as comprehensive in
integration surface as a modern OS* for agents:

| OS kernel metaphor | Sophyane AI Kernel |
|--------------------|--------------------|
| Process scheduler | Agent runtimes (chat, coding, multi-agent, edge) |
| Device drivers | Hardware registry + CUDA/ROCm/OpenVINO/Metal adapters |
| Filesystem / IPC | Kernel bus + memory store + daemon queue |
| Package manager | App factory (web / Android / Harmony / iOS / API) |
| Network services | Hardware API + ERP connectors |

It runs **on** Linux, Windows, macOS, Android Termux, and edge gateways.

## Boot & status

```bash
sophyane --kernel
sophyane --kernel-status
```

## Application factory

```bash
sophyane --create-app web --app-name "Shop Portal" --app-out ./apps/shop
sophyane --create-app android --app-name "FieldApp"
sophyane --create-app harmony --app-name "HarmonyClient"
sophyane --create-app ios --app-name "IOSClient"
sophyane --create-app desktop_python --app-name "DesktopHelper"
sophyane --create-app api_python --app-name "MiniAPI"
```

Scaffolds wire to the Sophyane Hardware API by default.

## CUDA + open-source stacks

```bash
sophyane --hardware
```

Detects / catalogs:

- **CUDA / TensorRT** (NVIDIA)
- **ROCm / HIP** (AMD)
- **OpenVINO / oneAPI** (Intel)
- **Metal / CoreML / MLX** (Apple)
- **QNN / TFLite** (Qualcomm / mobile)
- **llama.cpp, ONNX Runtime, PyTorch, Ollama**, MQTT, Modbus, OPC-UA, …

## ERP connectivity

```bash
sophyane --erp            # probe all known systems
sophyane --erp oracle
sophyane --erp sap
sophyane --erp odoo
```

Configure with environment variables (examples):

| System | Env |
|--------|-----|
| Oracle Fusion | `ORACLE_ERP_BASE_URL`, `ORACLE_ERP_TOKEN` |
| SAP OData | `SAP_ODATA_BASE_URL`, `SAP_TOKEN` |
| Odoo | `ODOO_URL`, `ODOO_API_KEY` |
| Dynamics 365 | `DYNAMICS_BASE_URL`, `DYNAMICS_TOKEN` |
| NetSuite | `NETSUITE_BASE_URL`, `NETSUITE_TOKEN` |
| ERPNext | `ERPNEXT_URL`, `ERPNEXT_KEY` |

API:

```http
GET  /v1/kernel
GET  /v1/erp
POST /v1/apps/create   {"target":"web","name":"Demo"}
POST /v1/erp/query     {"system":"odoo","path":"/jsonrpc"}
```

## Honest boundaries

1. **Not ring-0** — does not replace Linux/Windows kernels.  
2. **Not PLC firmware** — talks to industrial gear via gateways + open protocols.  
3. **App scaffolds** are production *starters*, not full App Store submissions.  
4. **ERP** needs your tenant URLs and credentials; Sophyane provides the uniform agent interface.

## Architecture

```
┌─────────────────────────────────────────────┐
│              Sophyane AI Kernel             │
│  bus · modules · security · memory · agents │
├──────────┬──────────┬──────────┬────────────┤
│ hardware │ software │ app      │ ERP        │
│ bus      │ bus      │ factory  │ connectors │
└────┬─────┴────┬─────┴────┬─────┴─────┬──────┘
     ▼          ▼          ▼           ▼
  CUDA/…     llama.cpp   web/APK/…  Oracle/SAP
  hosts      ONNX/MQTT   iOS/HMOS   Odoo/D365
     └──────────┴──────────┴───────────┘
                    real OS kernel
              (Linux / Windows / macOS)
```
