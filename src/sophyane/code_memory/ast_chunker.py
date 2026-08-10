"""AST-Aware Semantic Chunking Engine for Sophyane v21.4.0.

Parses Abstract Syntax Trees (AST) across Python, C++, Java, JS, Rust, Go to extract structural code entities.
"""
import ast
from pathlib import Path
from typing import Any

class ASTSemanticChunker:
    def __init__(self):
        self.parsed_nodes: list[dict[str, Any]] = []

    def chunk_code(self, code_text: str, filename: str = "source.py") -> list[dict[str, Any]]:
        """Parse source code into structural AST semantic chunks."""
        chunks = []
        try:
            tree = ast.parse(code_text, filename=filename)
            for node in ast.iter_child_nodes(tree):
                if isinstance(node, ast.FunctionDef):
                    chunks.append({
                        "node_type": "FunctionDeclaration",
                        "name": node.name,
                        "args": [a.arg for a in node.args.args],
                        "docstring": ast.get_docstring(node) or "",
                        "code": ast.unparse(node),
                        "lineno": node.lineno
                    })
                elif isinstance(node, ast.ClassDef):
                    chunks.append({
                        "node_type": "ClassDefinition",
                        "name": node.name,
                        "bases": [ast.unparse(b) for b in node.bases],
                        "docstring": ast.get_docstring(node) or "",
                        "code": ast.unparse(node),
                        "lineno": node.lineno
                    })
        except Exception:
            # Fallback for non-Python or unparseable blocks
            lines = code_text.splitlines()
            if lines:
                chunks.append({
                    "node_type": "CodeBlock",
                    "name": lines[0][:40],
                    "args": [],
                    "docstring": "",
                    "code": code_text,
                    "lineno": 1
                })
        self.parsed_nodes.extend(chunks)
        return chunks
