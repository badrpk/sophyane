"""Sophyane AI Kernel — userspace intelligence control plane.

This is not a ring-0 operating system kernel. It is an AI-focused supervisor
that runs on Linux/Windows/macOS (and edge gateways) and coordinates:

- hardware capability buses (NVIDIA CUDA, Intel, AMD, Qualcomm, …)
- open-source + vendor software stacks
- application factories (web, Android, HarmonyOS, iOS, desktop)
- ERP connectors (Oracle, SAP, Odoo, Dynamics, …)

Think of it as the *agent kernel* of the Sophyane system: schedulers, buses,
drivers (adapters), and services — as portable as Linux in *scope of
integration*, while still hosted by a real OS.
"""

from sophyane.kernel.core import AIKernel, boot_kernel, kernel_status

__all__ = ["AIKernel", "boot_kernel", "kernel_status"]
