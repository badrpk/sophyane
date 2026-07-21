"""Canonical MCP compatibility module.

The implementation lives in :mod:`sophyane.mcp_bridge`; this module provides the
stable public import path used by audits, plugins, and external integrations.
"""
from __future__ import annotations

from sophyane.mcp_bridge import call_tool, export_catalog, list_tools

__all__ = ["call_tool", "export_catalog", "list_tools"]
