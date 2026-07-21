# Sophyane 18.14.0

This release establishes the filesystem and sandbox prerequisites expected by durable deep-agent workflows.

## Added

- Persistent Sophyane runtime root under `~/.sophyane`.
- Dedicated workspaces, sandboxes, artifacts, cache, logs, temporary files, and state directories.
- Writable-directory verification at startup.
- Per-workspace `input`, `output`, `tmp`, `logs`, and `.sophyane` directories.
- Per-task sandbox manifest recording isolation rules and detected tools.
- Capability discovery for Python, shell, Git, Node, npm, compiler, curl, and Termux browser launching.
- Environment variables for Sophyane home, workspace root, sandbox root, and temporary storage.
- A larger local-model generation budget so slow GGUF inference is not killed by the previous fixed 60-second limit.

## Behaviour

Every execution workspace is prepared before the agent writes or runs anything. External writes remain blocked by the existing runtime safety layer, while relative workspace paths remain available for tools and generated artifacts.
