"""Modern Web Framework Component Tree Generator for Sophyane v21.3.0.

Synthesizes React, Next.js (App Router), and Vue 3 Composition API components.
"""
from pathlib import Path
from typing import Any

def compose_react_app(app_name: str, out_dir: Path) -> dict[str, Any]:
    """Generate modern React / Next.js component tree."""
    out_dir.mkdir(parents=True, exist_ok=True)
    
    app_tsx = f'''import React from "react";

export default function App() {{
  return (
    <div className="min-h-screen bg-slate-950 text-slate-100 flex flex-col items-center justify-center p-6">
      <h1 className="text-4xl font-bold text-sky-400 mb-4">{app_name}</h1>
      <p className="text-slate-400 text-lg">Synthesized by Sophyane v21.3.0 React/Next.js Engine</p>
    </div>
  );
}}
'''
    (out_dir / "App.tsx").write_text(app_tsx, encoding="utf-8")
    return {
        "ok": True,
        "framework": "React / Next.js",
        "files": ["App.tsx"],
        "out_dir": str(out_dir)
    }

def compose_vue_app(app_name: str, out_dir: Path) -> dict[str, Any]:
    """Generate modern Vue 3 Composition API component tree."""
    out_dir.mkdir(parents=True, exist_ok=True)
    
    app_vue = f'''<script setup lang="ts">
import {{ ref }} from 'vue'
const title = ref('{app_name}')
</script>

<template>
  <main class="vue-container">
    <h1>{{ title }}</h1>
    <p>Synthesized by Sophyane v21.3.0 Vue 3 Engine</p>
  </main>
</template>
'''
    (out_dir / "App.vue").write_text(app_vue, encoding="utf-8")
    return {
        "ok": True,
        "framework": "Vue 3 Composition API",
        "files": ["App.vue"],
        "out_dir": str(out_dir)
    }
