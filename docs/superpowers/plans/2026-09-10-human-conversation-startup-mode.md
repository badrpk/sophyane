# Human Conversation Startup Mode Implementation Plan

Goal: Add Mode 6 Human Conversation while preserving Modes 1-5.

Architecture:
- startup_policy selects SOPHYANE_SESSION_MODE=human_conversation.
- Mode 6 establishes transient `codex_cli -> nifdu_browser -> local_gguf` authority; persistent configuration remains unchanged.
- Mode 6 clears stale SLI, learning, and strict-local flags.
- cli_entry directly calls human_conversation_cli.main().
- v13_cli/tui_v2 remain unchanged for Mode 6.

Tasks:
1. Six-mode startup menu and option-6 session policy, TDD.
2. Direct cli_entry Human Conversation handoff, TDD.
3. Noninteractive human_conversation preservation, TDD.
4. Runtime identity/provider compatibility.
5. Startup and Human Conversation regression gate.
6. Live menu/handoff proof.
7. targeted_patch repository E2E through Mode 6.
8. Final verification; no automatic commit/merge.
