"""Curated expert answers for tough harness engineering & coding topics.

Used to strengthen small local models and guarantee baseline quality on
core Sophyane engineering knowledge. Hybrid mode merges this with LLM output.
"""

from __future__ import annotations

# Category-level deep templates (always high quality).
CATEGORY_EXPERT: dict[str, str] = {
    "harness": (
        "Agent harness core loop: (1) plan with a strict JSON schema, (2) act via "
        "registered tools only, (3) observe structured tool results, (4) verify with "
        "deterministic checks (tests/lint/patterns), (5) repair or stop. Persist across "
        "iterations: run_id, goal, scratchpad, tool_trace[], open_todos, file digests, "
        "budget counters (iterations, tokens, wall time). Prevent infinite loops with "
        "max_iterations, no-progress detection (same failing verify), and hard timeouts "
        "at tool/model/run levels. ContextManager: hard char budget; pin system/goal; "
        "evict lowest priority turns first; summarize old history when over budget. "
        "Guardrails deny destructive shell and path escape; require approval for writes "
        "outside scoped diffs. Prefer plan-and-execute for long coding tasks; ReAct for "
        "short exploratory probes."
    ),
    "tools": (
        "Tools must be schema-typed, path-jailed to workspace, size-capped, and "
        "timeout-bounded. Prefer allowlists for shell; never default-enable force-push. "
        "file_write uses temp+fsync+rename (atomic). search_code uses ripgrep with max "
        "matches and secret redaction. Network fetch blocks link-local/metadata SSRF "
        "(169.254.169.254, localhost unless allowed). Return structured JSON for "
        "machine-critical results so the model cannot misparse. Batch independent tools "
        "with concurrency limits and partial-failure aggregation. Patches are unified "
        "diffs verified by re-read + tests. test_runner maps pytest failure output to "
        "file:line and node ids so the agent can target repairs."
    ),
    "providers": (
        "Multi-provider chain: try frontier APIs, detect quota/credit/auth errors, fall "
        "back by priority to OpenRouter/local_gguf. Normalize messages to role/content. "
        "Coding mode uses low temperature and moderate max_tokens; chat can be higher. "
        "Retry 429/503 with exponential backoff + full jitter; do not retry 4xx auth. "
        "Validate tool names against registry before invoke. Local GGUF: health-check "
        "llama-server, shrink context on OOM, pick hardware-tier models (nano/micro). "
        "Never log API keys; load from env/keyring only. Prompt cache / system prompt "
        "reuse across turns cuts cost and latency when the provider supports it."
    ),
    "memory": (
        "Working memory = current context window (budgeted, pin system+goal, summarize "
        "old turns). Long-term = SQLite sessions/messages/notes. RepositoryIndex maps "
        "symbols, imports, tests, digests for planning. File digests use content hash to "
        "detect drift when files change without re-reading everything. Session isolation "
        "uses namespaces per tenant/user with wipe semantics for reset. Store tool "
        "outcome records (success/fail, side effects, rollback info). Compress sessions "
        "into decisions + open tasks. Sanitize stored user text against prompt injection. "
        "Vector search helps large codebases; small repos prefer ripgrep. Export/delete "
        "commands support local privacy."
    ),
    "verify": (
        "Verification must be deterministic: compile/import smoke, ruff/typecheck, unit "
        "tests, contract checks. Self-repair: parse failures → scoped patch → retest up to "
        "N times. Forbid deleting tests to greenwash. Cheap gates before expensive e2e. "
        "Prove minimal diffs and scan for secrets. Quarantine flaky tests with seeds/retries "
        "rather than infinite agent loops. Use verified-answer= patterns for closed-form tasks. "
        "Property-based tests generate cases for invariants; example tests cover fixed cases. "
        "Golden/snapshot tests risk silent drift — require review when snapshots update."
    ),
    "multiagent": (
        "Supervisor assigns workers with attempt limits and a task graph. Partition files "
        "or use locks/merge queues to avoid clobber. Roles: planner → coder → reviewer with "
        "artifact handoffs. Message bus for kernel modules. Detect deadlock via wait-for "
        "graphs and timeouts. Budget tokens per role. Map-reduce over files then aggregate. "
        "Human gates for deploy. Correlation IDs for attribution. Debate/consensus pattern: "
        "two agents critique architecture options and vote; supervisor picks the consensus."
    ),
    "coding": (
        "Coding agents: index repo → plan scoped edits → apply_patch → run tests → repair. "
        "Path jail with resolve()+relative_to(root). Unified diff apply risks fuzzy context "
        "mismatch — fail closed if hunks do not match. LRU caches need ordered dict + lock. "
        "SQLite: BEGIN IMMEDIATE for writers. C++17 RAII file mutex locks for concurrent "
        "mesh peers writing adapter.bin. Prefer asyncio for many HTTP waits; threads for "
        "blocking libs. Backoff with full jitter. Secure temp: tempfile.mkdtemp with tight "
        "permissions and cleanup. Parse pytest node ids for targeted repair. "
        "Content-addressed blobs for shared storage. Schema-validate planner JSON."
    ),
    "systems": (
        "Edge continual training uses PEFT/LoRA adapters, not full fine-tunes. FedAvg merges "
        "adapter deltas weighted by samples; reject base_hash mismatches. C++ train core for "
        "hot math; Python for orchestration. Mesh discovers LAN/USB peers. Appliance boot is "
        "idempotent when :8770/:8777 already listen. Network: DHCP ethernet + nmcli Wi-Fi. "
        "Q4_K_M GGUF trades quality for RAM. Hash-chain ledger for self-improve integrity. "
        "Process model: daemon threads serve HTTP APIs inside a long-lived appliance process. "
        "Zero mandatory pip dependencies (stdlib portable install); optional ML stacks stay optional."
    ),
    "ops": (
        "install.sh resolves latest release/vX.Y.Z (and tags), clones pinned commit, creates "
        "venv, pip installs package, wraps ~/.local/bin/sophyane. Doctor checks imports, "
        "version, provider, local model health. CI runs pytest multi-OS before tag. Rollback "
        "pins previous release branch. Feature --audit scores subsystems. systemd user unit "
        "runs --boot --boot-foreground. Upgrades preserve ~/.config and memory DBs. curl|sh "
        "users can pin commit for supply-chain safety. Logging uses levels, secret redaction, "
        "and rotating files for long appliance runs."
    ),
    "hardcode": (
        "Implement algorithms with clear complexity O(n) / O(n*d), pure functions, and tests. "
        "Path jail: Path(root, user).resolve().relative_to(root.resolve()); reject `..` escapes. "
        "FedAvg float loop weighted. ReAct parse Thought/Action/Action Input via regex. Token "
        "bucket rate limit with refill. SQL: INDEX(session_id, created_at); SELECT … ORDER BY "
        "created_at DESC LIMIT N. DFS color states detect import graph cycles. Prefer binary "
        "RPC over JSON on low-bandwidth IoT. Idempotent POST contribute keys = content hash "
        "to drop duplicates. Structured concurrency cancels sibling tasks on critical failure. "
        "E2E harness stages: plan→edit→test→verify→commit."
    ),
}

# Per-question concise gold answers (id -> text). Fill high-value ones fully.
QUESTION_EXPERT: dict[int, str] = {
    1: (
        "Loop: plan (JSON) → act (tools) → observe → verify → repair/stop. Persist: goal, "
        "scratchpad, tool_trace, file digests, budgets. Cap with max_iterations, no-progress "
        "stop, and nested timeouts. Emit a full trace for post-mortems."
    ),
    4: (
        "ModelRegistry orders providers by priority. On ProviderError (quota/credit/timeout), "
        "mark primary failed for this run and continue to next. Local GGUF is last-resort "
        "always-available backend after open-model bootstrap."
    ),
    11: (
        "Resolve path under workspace; reject escapes. Refuse binary/huge payloads. Write to "
        "*.tmp, fsync, os.replace for atomicity. Return {ok,path,bytes}."
    ),
    21: (
        "FallbackProvider walks chain; classify HTTP 401/402/429 and billing strings as "
        "failover. After APIs fail, local_runtime ensures GGUF+llama-server then answers."
    ),
    41: (
        "Run pytest → parse node ids/errors → scoped patch only failing files → retest. "
        "Stop at max_iterations or when verify passes. Never delete tests to pass."
    ),
    62: (
        "Thread-safe LRU: OrderedDict + Lock; on get move_to_end; on put setitem+move; "
        "while len>max: popitem(last=False). O(1) average."
    ),
    71: (
        "LoRA/PEFT trains tiny A/B adapters; freezes base GGUF. Fits edge RAM/CPU; deltas "
        "federate cheaply via FedAvg without shipping full weights."
    ),
    75: (
        "On EADDRINUSE, probe /health or /mesh/hello; if healthy, mark service reused=true "
        "instead of failing boot. Idempotent appliance start."
    ),
    81: (
        "install.sh: git ls-remote release/v* and tags, sort -V, pick latest, clone --branch "
        "depth 1, verify commit, venv, pip install ., symlink current, write wrappers."
    ),
    92: (
        "root = Path(root).resolve(); target = (root / user_path).resolve(); "
        "target.relative_to(root) or raise. Reject absolute user paths that escape."
    ),
    100: (
        "Mandatory stages: understand repo index → plan scoped change → edit/patch → "
        "lint/type/unit verify → repair loop → human or auto commit → report evidence."
    ),
}


def expert_answer_for(question: str, *, qid: int | None = None, cat: str | None = None) -> str:
    parts: list[str] = []
    if qid is not None and qid in QUESTION_EXPERT:
        parts.append(QUESTION_EXPERT[qid])
    if cat and cat in CATEGORY_EXPERT:
        parts.append(CATEGORY_EXPERT[cat])
    elif not parts:
        # Keyword route into a category
        low = question.lower()
        for key, c in (
            ("fedavg", "systems"),
            ("lora", "systems"),
            ("mesh", "systems"),
            ("install", "ops"),
            ("pytest", "verify"),
            ("fallback", "providers"),
            ("tool", "tools"),
            ("multi-agent", "multiagent"),
            ("supervisor", "multiagent"),
            ("memory", "memory"),
            ("harness", "harness"),
            ("lru", "coding"),
            ("diff", "coding"),
            ("path", "hardcode"),
        ):
            if key in low:
                parts.append(CATEGORY_EXPERT[c])
                break
        if not parts:
            parts.append(CATEGORY_EXPERT["harness"])
    # Deduplicate while keeping order
    seen: set[str] = set()
    out: list[str] = []
    for p in parts:
        if p not in seen:
            seen.add(p)
            out.append(p)
    return "\n\n".join(out)
