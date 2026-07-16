# Sophyane × LangGraph × LangChain × LangSmith — Full Feature Exam

- Started: `2026-07-16T13:44:29.710484+00:00`
- Finished: `2026-07-16T13:44:34.262122+00:00`
- Sophyane: **sophyane 17.5.0**
- Packages: `{"langgraph": "1.2.9", "langchain-core": "1.4.9", "langchain": "1.3.14", "langsmith": "0.3.45", "langchain-text-splitters": "1.1.2"}`
- **PASS 37 / FAIL 0 / SKIP 1** (of 38) — pass rate **97.4%**

Notes:
- Offline feature probes only unless API keys are present.
- LangSmith live project listing requires `LANGSMITH_API_KEY`.
- This suite tests **capability compatibility**, not marketing claims vs LangGraph.

## langgraph (7/7 pass)

| Feature | Status | Seconds | Detail |
|---|---|---:|---|
| StateGraph sequential nodes | **PASS** | 0.022 | x=11 path=['a', 'b'] |
| conditional edges | **PASS** | 0.005 | branch=high |
| loop + termination | **PASS** | 0.005 | loops=3 |
| MemorySaver checkpoint | **PASS** | 0.009 | checkpoint_history=3 |
| multi-node merge path | **PASS** | 0.005 | ['L', 'R'] |
| recursion_limit safety | **PASS** | 0.010 | GraphRecursionError |
| stream(values) | **PASS** | 0.005 | events=3 |

## sophyane_graph (7/7 pass)

| Feature | Status | Seconds | Detail |
|---|---|---:|---|
| StateGraph sequential | **PASS** | 0.003 | ['a', 'b'] |
| conditional edges | **PASS** | 0.002 | ['high'] |
| Command dynamic routing | **PASS** | 0.002 | {'x': 6, 'trace': ['b']} |
| RetryPolicy recovery | **PASS** | 0.002 | {'ok': True, 'attempts': 3, 'trace': ['flaky']} |
| DurableStore checkpoint resume | **PASS** | 0.006 | {'trace': ['a', 'b'], 'x': 3} |
| RecursionLimitError | **PASS** | 0.001 | graph exceeded recursion limit 5 |
| StateGraph.merge reducer | **PASS** | 0.000 | {'items': [1, 2, 3], 'n': 5} |

## langchain (11/11 pass)

| Feature | Status | Seconds | Detail |
|---|---|---:|---|
| RunnableLambda.invoke | **PASS** | 0.001 | ok:a |
| LCEL pipe (|) | **PASS** | 0.002 | 8 |
| ChatPromptTemplate | **PASS** | 0.113 | ['SystemMessage', 'HumanMessage'] |
| StrOutputParser | **PASS** | 0.006 | str |
| @tool + invoke | **PASS** | 0.031 | add |
| Message types | **PASS** | 0.000 | ['system', 'human', 'ai'] |
| Runnable.batch | **PASS** | 0.002 | ['A', 'B'] |
| Runnable.stream | **PASS** | 0.000 | chunks=1 |
| text splitters / docs | **PASS** | 0.022 | chunks=4 |
| InvokeAdapter(Sophyane) | **PASS** | 0.003 | lc:hello |
| MultiAgent + LC backend | **PASS** | 0.154 | mode=multi_agent workers=4 |

## langsmith (6/7 pass)

| Feature | Status | Seconds | Detail |
|---|---|---:|---|
| import Client | **PASS** | 0.000 | langsmith=0.3.45 Client=<class 'langsmith.client.Client'> |
| Client construct | **PASS** | 0.010 | Client |
| @traceable local | **PASS** | 0.001 | 5 |
| RunTree local | **PASS** | 0.000 | exam |
| evaluation/trace surface | **PASS** | 0.000 | attrs=[] |
| live list_projects | **SKIP** | 0.000 | RuntimeError: LANGSMITH_API_KEY not set — live list projects skipped |
| wrap_openai helper | **PASS** | 0.025 | wrap_openai available |

## sophyane_cli (6/6 pass)

| Feature | Status | Seconds | Detail |
|---|---|---:|---|
| --version | **PASS** | 0.387 | sophyane 17.5.0 |
| --capabilities | **PASS** | 0.393 | chars=3009 |
| --checkpoint-list (persistence) | **PASS** | 0.370 | {
  "ok": true,
  "checkpoints": [
    {
      "task_id": "266d6f75e74a",
      "name": "audit",
      "updated_at": 178 |
| --hitl-list (human-in-loop) | **PASS** | 0.294 | {
  "ok": true,
  "pending": [
    {
      "id": "605e57f7cebf",
      "action": "audit-noop",
      "detail": "feature  |
| --trace-list (observability) | **PASS** | 0.326 | {
  "ok": true,
  "traces": [
    {
      "run_id": "a07ae268c79e40a4",
      "start": {
        "type": "run_start",
   |
| --eval | **PASS** | 0.353 | {
  "ok": true,
  "stdout": "",
  "stderr": "",
  "result": "4",
  "sandbox": "best-effort sandbox"
}
◆ Sophyane 17.5.0  |

