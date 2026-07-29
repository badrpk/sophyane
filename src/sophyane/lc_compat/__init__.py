"""LangChain / LangGraph compatibility layer for Sophyane (no LC dependency)."""
from sophyane.lc_compat.prompt_templates import PromptTemplate, chat_prompt
from sophyane.lc_compat.output_parsers import JsonOutputParser, ListOutputParser
from sophyane.lc_compat.tools import Tool, ToolRegistry, tool
from sophyane.lc_compat.memory import BufferMemory, SummaryMemory, PersistentMemory
from sophyane.lc_compat.streaming import wrap_graph_stream
from sophyane.lc_compat.graph_viz import to_mermaid

__all__ = [
    "PromptTemplate", "chat_prompt",
    "JsonOutputParser", "ListOutputParser",
    "Tool", "ToolRegistry", "tool",
    "BufferMemory", "SummaryMemory", "PersistentMemory",
    "wrap_graph_stream", "to_mermaid",
]
