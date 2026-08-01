# Sophyane Repository Audit

Generated: 2026-08-01T22:09:14+05:00

## Automated Verification

| Check | Exit code | Evidence |
|---|---:|---|
| Full pytest suite | 0 | `reports/audit-evidence/pytest.txt` |
| Python compilation | 0 | `reports/audit-evidence/compileall.txt` |
| Pyflakes | 1 | `reports/audit-evidence/pyflakes.txt` |
| Bandit security scan | 1 | `reports/audit-evidence/bandit.txt` |
| Vulture dead-code scan | 3 | `reports/audit-evidence/vulture.txt` |
| Cyclomatic complexity | 0 | `reports/audit-evidence/complexity.txt` |
| Maintainability index | 0 | `reports/audit-evidence/maintainability.txt` |

## Test Baseline

```text
........................................................................ [ 17%]
........................................................................ [ 34%]
........................................................................ [ 52%]
........................................................................ [ 69%]
........................................................................ [ 87%]
....................................................                     [100%]
412 passed in 27.97s
```

## Compilation

```text

```

## Static Correctness Candidates

```text
src/sophyane/adaptive_execution.py:10:1: 'json' imported but unused
src/sophyane/adaptive_execution.py:621:9: local variable 'execution_contract' is assigned to but never used
src/sophyane/capabilities.py:10:1: 'dataclasses.field' imported but unused
src/sophyane/capability_executors.py:13:1: 'dataclasses.asdict' imported but unused
src/sophyane/coding_runtime.py:11:1: 'fnmatch' imported but unused
src/sophyane/coding_runtime.py:14:1: 'os' imported but unused
src/sophyane/collaborative_workers.py:10:1: 'json' imported but unused
src/sophyane/collaborative_workers.py:15:1: 'urllib.request' imported but unused
src/sophyane/failure_memory.py:13:1: 'typing.Iterable' imported but unused
src/sophyane/feature_audit.py:5:1: 'json' imported but unused
src/sophyane/feature_audit.py:7:1: 'urllib.request' imported but unused
src/sophyane/feature_audit.py:8:1: 'dataclasses.field' imported but unused
src/sophyane/feature_audit.py:9:1: 'pathlib.Path' imported but unused
src/sophyane/feature_audit.py:119:9: redefinition of unused 'Path' from line 9
src/sophyane/feature_audit.py:186:9: redefinition of unused 'Path' from line 119
src/sophyane/goal_execution.py:7:1: 'collections.abc.Mapping' imported but unused
src/sophyane/goal_scheduler.py:7:1: 'typing.Iterable' imported but unused
src/sophyane/hardware_api.py:14:1: 'sophyane.edge_agent.EDGE_SYSTEM_PROMPT' imported but unused
src/sophyane/hardware_fit.py:17:1: 'sophyane.config.save_config' imported but unused
src/sophyane/hardware_registry.py:17:1: 'json' imported but unused
src/sophyane/hardware_registry.py:18:1: 'os' imported but unused
src/sophyane/hardware_registry.py:20:1: 're' imported but unused
src/sophyane/incremental_browser_edit.py:9:1: 'html as html_lib' imported but unused
src/sophyane/interactive_coding_doer.py:4:1: 'json' imported but unused
src/sophyane/live_coding_doer.py:15:1: 'dataclasses.asdict' imported but unused
src/sophyane/live_coding_doer.py:17:1: 'typing.Callable' imported but unused
src/sophyane/local_runtime.py:438:9: local variable 'lib_dir' is assigned to but never used
src/sophyane/main.py:7:1: 'sys' imported but unused
src/sophyane/main.py:21:1: 'sophyane.tools.tools_description' imported but unused
src/sophyane/memory_architecture.py:20:1: 'time' imported but unused
src/sophyane/multiagent.py:19:1: 'typing.Callable' imported but unused
src/sophyane/native_worker_pool.py:21:1: 'pathlib.Path' imported but unused
src/sophyane/platform_kernel.py:11:1: 'os' imported but unused
src/sophyane/platform_kernel.py:13:1: 'subprocess' imported but unused
src/sophyane/platform_probe.py:212:9: f-string is missing placeholders
src/sophyane/repository.py:7:1: 'os' imported but unused
src/sophyane/request_intercepts.py:325:1: redefinition of unused 'install_input_capture' from line 274
src/sophyane/runtime_intent_refinement_patch.py:4:1: 'json' imported but unused
src/sophyane/runtime_sli_mission_os.py:12:1: 're' imported but unused
src/sophyane/sli_learner.py:4:1: 'pathlib.Path' imported but unused
src/sophyane/state_graph.py:18:1: 'typing.MutableMapping' imported but unused
src/sophyane/tools.py:14:1: 'typing.Callable' imported but unused
src/sophyane/tui_v2.py:175:13: 'dataclasses.asdict' imported but unused
src/sophyane/tui_v2.py:690:5: local variable 'has_machine' is assigned to but never used
src/sophyane/v13_cli.py:720:13: redefinition of unused 'generate' from line 713
src/sophyane/local_coding_capability.py:11:1: 'shlex' imported but unused
src/sophyane/runtime_snake_semantic_repair.py:10:1: 'typing.Any' imported but unused
src/sophyane/runtime_stagnation_patch.py:4:1: 'json' imported but unused
src/sophyane/setup_wizard.py:19:1: 'sophyane.model_catalog.ModelChoice' imported but unused
src/sophyane/task_execution.py:17:1: 'sys' imported but unused
src/sophyane/task_execution.py:1131:17: local variable 'failure' is assigned to but never used
src/sophyane/v16_doer.py:6:1: 'pathlib.Path' imported but unused
src/sophyane/harness_workspace.py:5:1: 're' imported but unused
src/sophyane/cloud/auto_messaging_setup.py:16:1: 'sophyane.cloud.messaging.MESSAGING_ENV' imported but unused
src/sophyane/cloud/auto_messaging_setup.py:16:1: 'sophyane.cloud.messaging.send_email' imported but unused
src/sophyane/cloud/auto_messaging_setup.py:16:1: 'sophyane.cloud.messaging.send_whatsapp' imported but unused
src/sophyane/cloud/messaging.py:248:13: local variable 'e' is assigned to but never used
src/sophyane/cloud/namecheap.py:207:9: local variable 'root' is assigned to but never used
src/sophyane/cloud/portal.py:6:1: 'os' imported but unused
src/sophyane/cloud/portal.py:12:1: 'urllib.parse.parse_qs' imported but unused
src/sophyane/cloud/portal.py:1193:39: undefined name 'primary_snip'
src/sophyane/cloud/portal.py:1220:50: undefined name 'primary_snip'
src/sophyane/cloud/product_knowledge.py:9:1: 're' imported but unused
src/sophyane/cloud/product_knowledge.py:10:1: 'typing.Any' imported but unused
src/sophyane/cloud/telegram_bot.py:19:1: 'sophyane.cloud.messaging.send_telegram' imported but unused
src/sophyane/competitive/auth.py:9:1: 'typing.Any' imported but unused
src/sophyane/competitive/auth.py:11:1: 'urllib.error.URLError' imported but unused
src/sophyane/competitive/auth.py:11:1: 'urllib.error.HTTPError' imported but unused
src/sophyane/competitive/payments.py:6:1: 'hashlib' imported but unused
src/sophyane/continual/engine.py:333:9: local variable 'peer' is assigned to but never used
src/sophyane/expert/exam.py:51:5: local variable 'error' is assigned to but never used
src/sophyane/expert/exam.py:53:36: undefined name 'error'
src/sophyane/lc_compat/llm.py:56:9: 'sophyane.providers.gemini.GeminiProvider' imported but unused
src/sophyane/lc_compat/memory.py:7:1: 'typing.Any' imported but unused
src/sophyane/lc_compat/streaming.py:3:1: 'dataclasses.field' imported but unused
src/sophyane/mesh/core.py:25:1: 'sophyane.mesh.federation.remote_capabilities' imported but unused
src/sophyane/mesh/core.py:25:1: 'sophyane.mesh.federation.remote_exec_safe' imported but unused
src/sophyane/mesh/discovery.py:8:1: 'struct' imported but unused
src/sophyane/mesh/install_peer.py:6:1: 'shlex' imported but unused
src/sophyane/observability/__init__.py:114:1: redefinition of unused 'list_traces' from line 16
src/sophyane/providers/fallback.py:8:1: 'pathlib.Path' imported but unused
src/sophyane/providers/openai_compatible.py:7:1: 'sophyane.providers.base.ProviderMetadata' imported but unused
src/sophyane/self_improve/ledger.py:12:1: 'os' imported but unused
tests/test_browser_partial_recovery.py:1:1: 'pathlib.Path' imported but unused
tests/test_future_agent.py:6:1: 'sophyane.hitl.list_pending' imported but unused
tests/test_mesh.py:3:1: 'json' imported but unused
tests/test_new_tab_preview_and_gemini_tool_guard.py:2:1: 'types.SimpleNamespace' imported but unused
tests/test_runtime_root_scan_guard.py:1:1: 'tempfile' imported but unused
tests/test_runtime_root_scan_guard.py:3:1: 'pathlib.Path' imported but unused
tests/test_state_graph_unittest.py:2:1: 'sophyane.state_graph.START' imported but unused
tests/test_tui_mobile_filesystem.py:3:1: 'json' imported but unused
tests/test_tui_mobile_filesystem.py:17:5: local variable 'original_home' is assigned to but never used
```

## Security Candidates

These require manual data-flow verification. Matches for shell execution,
eval, exec, subprocess, or hard-coded strings are not automatically exploitable.

```text
Run started:2026-08-01 17:08:53.064676+00:00

Test results:
>> Issue: [B110:try_except_pass] Try, Except, Pass detected.
   Severity: Low   Confidence: High
   CWE: CWE-703 (https://cwe.mitre.org/data/definitions/703.html)
   More Info: https://bandit.readthedocs.io/en/1.9.4/plugins/b110_try_except_pass.html
   Location: src/sophyane/agent.py:76:8
75	                return AgentResponse(_cr)
76	        except Exception:
77	            pass
78	        message = message.strip()

--------------------------------------------------
>> Issue: [B110:try_except_pass] Try, Except, Pass detected.
   Severity: Low   Confidence: High
   CWE: CWE-703 (https://cwe.mitre.org/data/definitions/703.html)
   More Info: https://bandit.readthedocs.io/en/1.9.4/plugins/b110_try_except_pass.html
   Location: src/sophyane/agent.py:87:8
86	                return AgentResponse(_native)
87	        except Exception:
88	            pass
89

--------------------------------------------------
>> Issue: [B110:try_except_pass] Try, Except, Pass detected.
   Severity: Low   Confidence: High
   CWE: CWE-703 (https://cwe.mitre.org/data/definitions/703.html)
   More Info: https://bandit.readthedocs.io/en/1.9.4/plugins/b110_try_except_pass.html
   Location: src/sophyane/agent.py:96:8
95	                return AgentResponse(gap)
96	        except Exception:
97	            pass
98

--------------------------------------------------
>> Issue: [B110:try_except_pass] Try, Except, Pass detected.
   Severity: Low   Confidence: High
   CWE: CWE-703 (https://cwe.mitre.org/data/definitions/703.html)
   More Info: https://bandit.readthedocs.io/en/1.9.4/plugins/b110_try_except_pass.html
   Location: src/sophyane/agent.py:109:8
108	                return AgentResponse(kernel_reply)
109	        except Exception:
110	            # Preserve existing routing if a kernel capability fails to load.
111	            pass
112

--------------------------------------------------
>> Issue: [B110:try_except_pass] Try, Except, Pass detected.
   Severity: Low   Confidence: High
   CWE: CWE-703 (https://cwe.mitre.org/data/definitions/703.html)
   More Info: https://bandit.readthedocs.io/en/1.9.4/plugins/b110_try_except_pass.html
   Location: src/sophyane/agent.py:122:8
121	                return AgentResponse(executor_reply)
122	        except Exception:
123	            # Existing routing remains the safe fallback.
124	            pass
125

--------------------------------------------------
>> Issue: [B404:blacklist] Consider possible security implications associated with the subprocess module.
   Severity: Low   Confidence: High
   CWE: CWE-78 (https://cwe.mitre.org/data/definitions/78.html)
   More Info: https://bandit.readthedocs.io/en/1.9.4/blacklists/blacklist_imports.html#b404-import-subprocess
   Location: src/sophyane/agent_runtime.py:22:0
21	import sqlite3
22	import subprocess
23	from datetime import datetime, timezone

--------------------------------------------------
>> Issue: [B603:subprocess_without_shell_equals_true] subprocess call - check for execution of untrusted input.
   Severity: Low   Confidence: High
   CWE: CWE-78 (https://cwe.mitre.org/data/definitions/78.html)
   More Info: https://bandit.readthedocs.io/en/1.9.4/plugins/b603_subprocess_without_shell_equals_true.html
   Location: src/sophyane/agent_runtime.py:280:17
279	    try:
280	        result = subprocess.run(
281	            arguments,
282	            cwd=str(cwd or Path.cwd()),
283	            capture_output=True,
284	            text=True,
285	            timeout=timeout,
286	            check=False,
287	            env={
288	                **os.environ,
289	                "LC_ALL": "C.UTF-8",
290	                "LANG": "C.UTF-8",
291	            },
292	        )
293	    except subprocess.TimeoutExpired:

--------------------------------------------------
>> Issue: [B404:blacklist] Consider possible security implications associated with the subprocess module.
   Severity: Low   Confidence: High
   CWE: CWE-78 (https://cwe.mitre.org/data/definitions/78.html)
   More Info: https://bandit.readthedocs.io/en/1.9.4/blacklists/blacklist_imports.html#b404-import-subprocess
   Location: src/sophyane/appliance.py:22:0
21	import socket
22	import subprocess
23	import time

--------------------------------------------------
>> Issue: [B603:subprocess_without_shell_equals_true] subprocess call - check for execution of untrusted input.
   Severity: Low   Confidence: High
   CWE: CWE-78 (https://cwe.mitre.org/data/definitions/78.html)
   More Info: https://bandit.readthedocs.io/en/1.9.4/plugins/b603_subprocess_without_shell_equals_true.html
   Location: src/sophyane/appliance.py:57:20
56	    try:
57	        completed = subprocess.run(
58	            cmd,
59	            capture_output=True,
60	            text=True,
61	            timeout=timeout,
62	            check=False,
63	        )
64	        return completed.returncode, ((completed.stdout or "") + (completed.stderr or "")).strip()

--------------------------------------------------
>> Issue: [B104:hardcoded_bind_all_interfaces] Possible binding to all interfaces.
   Severity: Medium   Confidence: Medium
   CWE: CWE-605 (https://cwe.mitre.org/data/definitions/605.html)
   More Info: https://bandit.readthedocs.io/en/1.9.4/plugins/b104_hardcoded_bind_all_interfaces.html
   Location: src/sophyane/appliance.py:384:39
383
384	            return ensure_hardware_api("0.0.0.0", 8770, create_default_api())
385

--------------------------------------------------
>> Issue: [B104:hardcoded_bind_all_interfaces] Possible binding to all interfaces.
   Severity: Medium   Confidence: Medium
   CWE: CWE-605 (https://cwe.mitre.org/data/definitions/605.html)
   More Info: https://bandit.readthedocs.io/en/1.9.4/plugins/b104_hardcoded_bind_all_interfaces.html
   Location: src/sophyane/appliance.py:394:61
393
394	            return get_mesh_node(8777).serve_background(host="0.0.0.0")
395

--------------------------------------------------
>> Issue: [B404:blacklist] Consider possible security implications associated with the subprocess module.
   Severity: Low   Confidence: High
   CWE: CWE-78 (https://cwe.mitre.org/data/definitions/78.html)
   More Info: https://bandit.readthedocs.io/en/1.9.4/blacklists/blacklist_imports.html#b404-import-subprocess
   Location: src/sophyane/audit_cli.py:9:0
8	import shutil
9	import subprocess
10	import tempfile

--------------------------------------------------
>> Issue: [B603:subprocess_without_shell_equals_true] subprocess call - check for execution of untrusted input.
   Severity: Low   Confidence: High
   CWE: CWE-78 (https://cwe.mitre.org/data/definitions/78.html)
   More Info: https://bandit.readthedocs.io/en/1.9.4/plugins/b603_subprocess_without_shell_equals_true.html
   Location: src/sophyane/audit_cli.py:140:25
139	            def run(argv=argv) -> str:
140	                result = subprocess.run(argv, capture_output=True, text=True, timeout=30, env={**os.environ, "SOPHYANE_SKIP_UPDATE_CHECK": "1"})
141	                if result.returncode != 0:

--------------------------------------------------
>> Issue: [B404:blacklist] Consider possible security implications associated with the subprocess module.
   Severity: Low   Confidence: High
   CWE: CWE-78 (https://cwe.mitre.org/data/definitions/78.html)
   More Info: https://bandit.readthedocs.io/en/1.9.4/blacklists/blacklist_imports.html#b404-import-subprocess
   Location: src/sophyane/autonomous_builder.py:12:0
11	import shutil
12	import subprocess
13	import sys

--------------------------------------------------
>> Issue: [B603:subprocess_without_shell_equals_true] subprocess call - check for execution of untrusted input.
   Severity: Low   Confidence: High
   CWE: CWE-78 (https://cwe.mitre.org/data/definitions/78.html)
   More Info: https://bandit.readthedocs.io/en/1.9.4/plugins/b603_subprocess_without_shell_equals_true.html
   Location: src/sophyane/autonomous_builder.py:378:13
377	    state.test_command = [sys.executable, "-m", "unittest", "-v"]
378	    result = subprocess.run(
379	        state.test_command,
380	        cwd=state.project,
381	        text=True,
382	        capture_output=True,
383	        timeout=60,
384	        check=False,
385	    )
386	    state.test_exit_code = result.returncode

--------------------------------------------------
>> Issue: [B404:blacklist] Consider possible security implications associated with the subprocess module.
   Severity: Low   Confidence: High
   CWE: CWE-78 (https://cwe.mitre.org/data/definitions/78.html)
   More Info: https://bandit.readthedocs.io/en/1.9.4/blacklists/blacklist_imports.html#b404-import-subprocess
   Location: src/sophyane/benchmark_cli.py:11:0
10	import shutil
11	import subprocess
12	import tempfile

--------------------------------------------------
>> Issue: [B603:subprocess_without_shell_equals_true] subprocess call - check for execution of untrusted input.
   Severity: Low   Confidence: High
   CWE: CWE-78 (https://cwe.mitre.org/data/definitions/78.html)
   More Info: https://bandit.readthedocs.io/en/1.9.4/plugins/b603_subprocess_without_shell_equals_true.html
   Location: src/sophyane/benchmark_cli.py:52:17
51	    def run_cmd(argv: list[str], cwd: Path, timeout: int = 45) -> str:
52	        result = subprocess.run(argv, cwd=cwd, text=True, capture_output=True, timeout=timeout)
53	        if result.returncode != 0:

--------------------------------------------------
>> Issue: [B404:blacklist] Consider possible security implications associated with the subprocess module.
   Severity: Low   Confidence: High
   CWE: CWE-78 (https://cwe.mitre.org/data/definitions/78.html)
   More Info: https://bandit.readthedocs.io/en/1.9.4/blacklists/blacklist_imports.html#b404-import-subprocess
   Location: src/sophyane/browser/launcher.py:8:0
7	import socket
8	import subprocess
9	import threading

--------------------------------------------------
>> Issue: [B603:subprocess_without_shell_equals_true] subprocess call - check for execution of untrusted input.
   Severity: Low   Confidence: High
   CWE: CWE-78 (https://cwe.mitre.org/data/definitions/78.html)
   More Info: https://bandit.readthedocs.io/en/1.9.4/plugins/b603_subprocess_without_shell_equals_true.html
   Location: src/sophyane/browser/launcher.py:134:19
133	        try:
134	            proc = subprocess.Popen(
135	                args,
136	                stdout=subprocess.DEVNULL,
137	                stderr=subprocess.DEVNULL,
138	                start_new_session=True,
139	            )
140	            pid = proc.pid

--------------------------------------------------
>> Issue: [B404:blacklist] Consider possible security implications associated with the subprocess module.
   Severity: Low   Confidence: High
   CWE: CWE-78 (https://cwe.mitre.org/data/definitions/78.html)
   More Info: https://bandit.readthedocs.io/en/1.9.4/blacklists/blacklist_imports.html#b404-import-subprocess
   Location: src/sophyane/browser_runtime_v2.py:9:0
8	import shutil
9	import subprocess
10	import threading

--------------------------------------------------
>> Issue: [B310:blacklist] Audit url open for permitted schemes. Allowing use of file:/ or custom schemes is often unexpected.
   Severity: Medium   Confidence: High
   CWE: CWE-22 (https://cwe.mitre.org/data/definitions/22.html)
   More Info: https://bandit.readthedocs.io/en/1.9.4/blacklists/blacklist_calls.html#b310-urllib-urlopen
   Location: src/sophyane/browser_runtime_v2.py:45:17
44	            request = urllib.request.Request(url, headers={"User-Agent": "Sophyane/21 premium-demo image fetcher"})
45	            with urllib.request.urlopen(request, timeout=15) as response:
46	                content_type = str(response.headers.get("Content-Type") or "").lower()

--------------------------------------------------
>> Issue: [B603:subprocess_without_shell_equals_true] subprocess call - check for execution of untrusted input.
   Severity: Low   Confidence: High
   CWE: CWE-78 (https://cwe.mitre.org/data/definitions/78.html)
   More Info: https://bandit.readthedocs.io/en/1.9.4/plugins/b603_subprocess_without_shell_equals_true.html
   Location: src/sophyane/browser_runtime_v2.py:95:26
94	            try:
95	                process = subprocess.Popen(
96	                    command,
97	                    stdout=subprocess.DEVNULL,
98	                    stderr=subprocess.DEVNULL,
99	                    start_new_session=True,
100	                )
101	            except OSError:

--------------------------------------------------
>> Issue: [B310:blacklist] Audit url open for permitted schemes. Allowing use of file:/ or custom schemes is often unexpected.
   Severity: Medium   Confidence: High
   CWE: CWE-22 (https://cwe.mitre.org/data/definitions/22.html)
   More Info: https://bandit.readthedocs.io/en/1.9.4/blacklists/blacklist_calls.html#b310-urllib-urlopen
   Location: src/sophyane/browser_runtime_v2.py:121:13
120	    try:
121	        with urllib.request.urlopen(url, timeout=5) as response:
122	            body = response.read()

--------------------------------------------------
>> Issue: [B607:start_process_with_partial_path] Starting a process with a partial executable path
   Severity: Low   Confidence: High
   CWE: CWE-78 (https://cwe.mitre.org/data/definitions/78.html)
   More Info: https://bandit.readthedocs.io/en/1.9.4/plugins/b607_start_process_with_partial_path.html
   Location: src/sophyane/browser_runtime_v2.py:136:20
135	    if shutil.which("termux-open-url"):
136	        completed = subprocess.run(["termux-open-url", url], text=True, capture_output=True)
137	        return completed.returncode == 0, (

--------------------------------------------------
>> Issue: [B603:subprocess_without_shell_equals_true] subprocess call - check for execution of untrusted input.
   Severity: Low   Confidence: High
   CWE: CWE-78 (https://cwe.mitre.org/data/definitions/78.html)
   More Info: https://bandit.readthedocs.io/en/1.9.4/plugins/b603_subprocess_without_shell_equals_true.html
   Location: src/sophyane/browser_runtime_v2.py:136:20
135	    if shutil.which("termux-open-url"):
136	        completed = subprocess.run(["termux-open-url", url], text=True, capture_output=True)
137	        return completed.returncode == 0, (

--------------------------------------------------
>> Issue: [B607:start_process_with_partial_path] Starting a process with a partial executable path
   Severity: Low   Confidence: High
   CWE: CWE-78 (https://cwe.mitre.org/data/definitions/78.html)
   More Info: https://bandit.readthedocs.io/en/1.9.4/plugins/b607_start_process_with_partial_path.html
   Location: src/sophyane/browser_runtime_v2.py:144:20
143	    if shutil.which("am"):
144	        completed = subprocess.run(
145	            [
146	                "am", "start", "--activity-new-task", "-a",
147	                "android.intent.action.VIEW", "-d", url,
148	            ],
149	            text=True,
150	            capture_output=True,
151	        )
152	        return completed.returncode == 0, (

--------------------------------------------------
>> Issue: [B603:subprocess_without_shell_equals_true] subprocess call - check for execution of untrusted input.
   Severity: Low   Confidence: High
   CWE: CWE-78 (https://cwe.mitre.org/data/definitions/78.html)
   More Info: https://bandit.readthedocs.io/en/1.9.4/plugins/b603_subprocess_without_shell_equals_true.html
   Location: src/sophyane/browser_runtime_v2.py:144:20
143	    if shutil.which("am"):
144	        completed = subprocess.run(
145	            [
146	                "am", "start", "--activity-new-task", "-a",
147	                "android.intent.action.VIEW", "-d", url,
148	            ],
149	            text=True,
150	            capture_output=True,
151	        )
152	        return completed.returncode == 0, (

--------------------------------------------------
>> Issue: [B105:hardcoded_password_string] Possible hardcoded password: '500000'
   Severity: Low   Confidence: Medium
   CWE: CWE-259 (https://cwe.mitre.org/data/definitions/259.html)
   More Info: https://bandit.readthedocs.io/en/1.9.4/plugins/b105_hardcoded_password_string.html
   Location: src/sophyane/budget.py:13:4
12	_DEFAULT = {
13	    "token_budget": 500_000,
14	    "tokens_used": 0,
15	    "cost_budget_usd": 10.0,
16	    "cost_used_usd": 0.0,
17	    "time_budget_sec": 3600,
18	}
19
20

--------------------------------------------------
>> Issue: [B110:try_except_pass] Try, Except, Pass detected.
   Severity: Low   Confidence: High
   CWE: CWE-703 (https://cwe.mitre.org/data/definitions/703.html)
   More Info: https://bandit.readthedocs.io/en/1.9.4/plugins/b110_try_except_pass.html
   Location: src/sophyane/capability_gap.py:144:4
```

## Dead-Code Candidates

These require checking runtime patch installation, dynamic imports, CLI entry
points, decorators and provider/plugin registration before deletion.

```text
src/sophyane/capability_gap.py:265: unused variable 'exc_type' (100% confidence)
src/sophyane/cloud/portal.py:12: unused import 'parse_qs' (90% confidence)
src/sophyane/coding_runtime.py:11: unused import 'fnmatch' (90% confidence)
src/sophyane/incremental_browser_edit.py:9: unused import 'html_lib' (90% confidence)
src/sophyane/mesh/core.py:25: unused import 'remote_capabilities' (90% confidence)
src/sophyane/mesh/core.py:25: unused import 'remote_exec_safe' (90% confidence)
src/sophyane/mesh/discovery.py:8: unused import 'struct' (90% confidence)
src/sophyane/state_graph.py:18: unused import 'MutableMapping' (90% confidence)
tests/observability/test_lc_compat_unittest.py:34: unused variable 'inp' (100% confidence)
```

## Complexity Candidates

```text
src/sophyane/adaptive_execution.py
    F 585:0 run_adaptive_loop - F (53)
    F 128:0 _javascript_balance_problem - D (24)
    F 485:0 _execute - C (19)
    F 206:0 _one_shot_browser_artifact - C (17)
    F 295:0 _normalise_action - C (16)
    F 391:0 _command_problem - C (13)
    F 281:0 _file_bundle_action - C (11)
    F 187:0 _validate_html - B (10)
    F 352:0 _selected_action - B (10)
    F 446:0 _discovery_request_completed - B (9)
    F 28:0 _extract_html - B (8)
    F 92:0 _join_html_continuation - B (7)
    F 384:0 _command_text - B (6)
    F 47:0 _extract_partial_html - A (5)
    F 19:0 _files - A (3)
    F 435:0 _command_stdout - A (3)
    F 23:0 _browser_request - A (2)
    F 63:0 _raw_html_prompt - A (2)
    F 80:0 _html_continuation_prompt - A (2)
    F 119:0 _prepare_for_continuation - A (2)
    F 521:0 execution_prefix_for_repair - A (2)
    F 532:0 _compact_repair_prompt - A (2)
    F 581:0 _read_only_inspection - A (2)
    F 937:0 install - A (1)
src/sophyane/agent.py
    M 168:4 SophyaneAgent._execute_route - E (34)
    M 70:4 SophyaneAgent.ask - C (16)
    C 59:0 SophyaneAgent - C (14)
    M 334:4 SophyaneAgent._summarize_tool - A (2)
    C 54:0 AgentResponse - A (1)
    M 60:4 SophyaneAgent.__init__ - A (1)
src/sophyane/agent_runtime.py
    F 613:0 detect_natural_tool - C (17)
    F 746:0 route_local_request - C (12)
    F 718:0 execute_named_tool - B (10)
    F 266:0 run_command - B (8)
    F 480:0 directory_information - B (8)
    F 516:0 validate_shell_command - B (7)
    F 312:0 first_existing_command - A (4)
    F 549:0 safe_shell - A (4)
    F 212:0 format_memories - A (3)
    F 230:0 log_tool - A (3)
    F 858:0 memory_context - A (3)
    F 157:0 remember - A (2)
    F 181:0 recall_memories - A (2)
    F 198:0 forget_memory - A (2)
    F 320:0 system_information - A (2)
    F 121:0 utc_now - A (1)
    F 125:0 database - A (1)
    F 262:0 command_exists - A (1)
    F 381:0 cpu_information - A (1)
    F 393:0 memory_information - A (1)
    F 404:0 disk_information - A (1)
    F 420:0 network_information - A (1)
    F 447:0 process_information - A (1)
    F 462:0 git_information - A (1)
    F 574:0 tools_help - A (1)
    F 872:0 runtime_status - A (1)
    C 117:0 RuntimeErrorMessage - A (1)
src/sophyane/appliance.py
    F 104:0 detect_network_interfaces - E (33)
    F 218:0 bring_up_network - D (24)
    F 328:0 boot_appliance - C (15)
    F 69:0 _classify_iface - C (11)
    F 298:0 _start_service - B (6)
    F 55:0 _run - A (4)
    F 312:0 network_capability_report - A (3)
    F 466:0 write_systemd_unit - A (3)
    F 491:0 write_chip_install_script - A (2)
    C 36:0 BootReport - A (2)
    F 48:0 _log - A (1)
    M 44:4 BootReport.to_dict - A (1)
src/sophyane/artifact_extractor.py
    F 29:0 _walk - D (25)
    F 99:0 extract_artifact - C (12)
    F 69:0 _decode_partial_json_string - B (8)
    F 159:0 merge_continuation - B (7)
    F 24:0 _complete_html - A (2)
    F 149:0 continuation_prompt - A (1)
    C 17:0 Artifact - A (1)
src/sophyane/audit_cli.py
    M 48:4 Audit.run - C (11)
    M 34:4 Audit.check - A (4)
    M 134:4 Audit._cli - A (4)
    M 159:4 Audit._release_docs - A (4)
    F 181:0 main - A (3)
    C 29:0 Audit - A (3)
    M 67:4 Audit._imports - A (3)
    M 153:4 Audit._browser_artifact - A (3)
    M 146:4 Audit._provider_state - A (2)
    M 166:4 Audit._live - A (2)
    C 20:0 Check - A (1)
    M 30:4 Audit.__init__ - A (1)
    M 76:4 Audit._filesystem - A (1)
    M 82:4 Audit._repository - A (1)
    M 95:4 Audit._sandbox - A (1)
    M 110:4 Audit._evaluation_prompting - A (1)
    M 119:4 Audit._coi - A (1)
    M 128:4 Audit._mcp - A (1)
src/sophyane/autonomous_builder.py
    F 443:0 run_inventory_workflow - B (8)
    F 63:0 supports_request - A (5)
    F 363:0 _build - A (3)
    F 375:0 _test - A (3)
    F 403:0 _verify - A (3)
    C 43:0 BuildGraph - A (3)
    M 52:4 BuildGraph.run - A (3)
    C 25:0 BuildState - A (2)
    F 349:0 _plan - A (1)
    F 395:0 _repair - A (1)
    F 422:0 _report - A (1)
    M 39:4 BuildState.record - A (1)
    M 46:4 BuildGraph.__init__ - A (1)
    M 49:4 BuildGraph.add - A (1)
src/sophyane/autonomy.py
    M 87:4 AutonomyPolicy.decide - B (8)
    C 27:0 AutonomyPolicy - B (7)
    M 68:4 AutonomyPolicy.classify - B (7)
    M 57:4 AutonomyPolicy.__init__ - A (2)
    C 12:0 RiskLevel - A (1)
    C 19:0 ApprovalDecision - A (1)
src/sophyane/benchmark_cli.py
    M 162:4 ProductBenchmarks.run - C (11)
    M 57:4 ProductBenchmarks.frontend - B (7)
    C 31:0 ProductBenchmarks - A (5)
    M 68:4 ProductBenchmarks.languages - A (5)
    M 36:4 ProductBenchmarks.check - A (4)
    M 51:4 ProductBenchmarks.run_cmd - A (4)
    M 117:4 ProductBenchmarks.sli_switching - A (4)
    F 171:0 main - A (3)
    M 87:4 ProductBenchmarks.repository - A (3)
    M 105:4 ProductBenchmarks.orchestration - A (2)
    M 131:4 ProductBenchmarks.mcp_and_persistence - A (2)
    M 144:4 ProductBenchmarks.live_product - A (2)
    C 22:0 Result - A (1)
    M 32:4 ProductBenchmarks.__init__ - A (1)
src/sophyane/browser_failure_gate.py
    F 20:0 install_browser_failure_gate - A (2)
src/sophyane/browser_partial_recovery.py
    F 74:0 _extraction_diagnostic - B (8)
    F 26:0 _finish_reason - B (6)
    F 22:0 _response_text - A (2)
    F 44:0 _save_raw - A (2)
    F 90:0 _acceptable_rewrite - A (2)
    F 98:0 install_browser_partial_recovery - A (2)
    F 39:0 _new_run_id - A (1)
src/sophyane/browser_runtime_v2.py
    F 109:0 open_verified_browser - B (8)
    F 83:0 _desktop_new_tab - A (4)
    F 23:0 _localize_demo_photos - A (3)
    F 68:0 _server_for - A (3)
src/sophyane/budget.py
    F 76:0 status - B (6)
    F 21:0 _load - A (4)
    F 43:0 configure - A (4)
    F 60:0 record_usage - A (3)
    F 95:0 allow_request - A (3)
    F 37:0 _save - A (1)
    F 68:0 reset_usage - A (1)
src/sophyane/capabilities.py
    F 84:0 capability_matrix - B (8)
    F 105:0 format_capability_report - A (2)
    C 17:0 Capability - A (2)
    M 25:4 Capability.to_dict - A (1)
src/sophyane/capability_executors.py
    F 213:0 execute_deterministic_capability - C (15)
    F 101:0 _list_folders - B (9)
    F 54:0 _looks_like_folder_listing - A (5)
    F 66:0 _requested_root - A (5)
    F 50:0 _normalise - A (2)
    F 261:0 execute_deterministic_text - A (2)
    F 277:0 try_connector_fast_path - A (2)
    C 19:0 CapabilityExecution - A (1)
src/sophyane/capability_gap.py
    M 290:4 EditableVisualBuilder.build - C (13)
    C 275:0 EditableVisualBuilder - B (8)
    F 90:0 required_capabilities - B (7)
    F 122:0 available_capabilities - A (5)
    F 191:0 detect_capability_gap - A (4)
    F 597:0 improve_until_satisfied - A (4)
    F 160:0 acceptance_criteria_for - A (3)
    F 587:0 register_builder - A (3)
    C 52:0 CapabilityBuilder - A (2)
    C 225:0 Heartbeat - A (2)
    M 263:4 Heartbeat.__exit__ - A (2)
    C 23:0 CapabilityGap - A (1)
    C 34:0 StageResult - A (1)
    C 42:0 ImprovementResult - A (1)
    M 55:4 CapabilityBuilder.supports - A (1)
    M 58:4 CapabilityBuilder.build - A (1)
    M 228:4 Heartbeat.__init__ - A (1)
    M 241:4 Heartbeat.__enter__ - A (1)
    M 278:4 EditableVisualBuilder.supports - A (1)
src/sophyane/capability_gap_messages.py
    F 11:0 _email_connector_handles - A (4)
    F 20:0 is_email_access_request - A (2)
    F 25:0 is_unavailable_external_request - A (2)
    F 30:0 capability_gap_reply - A (2)
    F 50:0 email_gap_message - A (1)
src/sophyane/capability_manager.py
    M 164:4 CapabilityManager.matches - C (14)
    M 89:4 CapabilityManager.register - A (5)
    C 81:0 CapabilityManager - A (4)
    M 124:4 CapabilityManager.list - A (4)
    M 250:4 CapabilityManager.invoke - A (4)
    F 19:0 _normalize_tags - A (3)
    C 28:0 Capability - A (3)
    M 39:4 Capability.__post_init__ - A (3)
    M 298:4 CapabilityManager.load - A (3)
    F 15:0 _normalize - A (2)
    F 313:0 default_capability_manager - A (2)
    M 144:4 CapabilityManager.set_enabled - A (2)
    M 232:4 CapabilityManager.select - A (2)
    M 268:4 CapabilityManager.save - A (2)
    M 55:4 Capability.to_dict - A (1)
    M 61:4 Capability.from_dict - A (1)
    C 74:0 CapabilityMatch - A (1)
    M 84:4 CapabilityManager.__init__ - A (1)
    M 111:4 CapabilityManager.unregister - A (1)
    M 120:4 CapabilityManager.get - A (1)
    M 246:4 CapabilityManager.handler - A (1)
src/sophyane/capability_registry.py
    F 215:0 _match_email - C (15)
    F 257:0 _register_defaults - C (12)
    M 78:4 CapabilityRegistry.resolve - B (7)
    F 128:0 _tier_name - B (6)
    F 164:0 route_for_message - A (5)
    F 248:0 _match_fs - A (5)
    F 157:0 gap_or_direct_reply - A (4)
    F 175:0 is_execution_capability - A (4)
    C 65:0 CapabilityRegistry - A (4)
    M 69:4 CapabilityRegistry.register - A (3)
    F 61:0 _norm - A (2)
    F 145:0 get_registry - A (2)
    M 113:4 CapabilityRegistry.list_capabilities - A (2)
    F 153:0 resolve_capability - A (1)
    F 189:0 _re - A (1)
    F 415:0 reset_registry_for_tests - A (1)
    C 28:0 Priority - A (1)
    C 40:0 CapabilityMatch - A (1)
    C 50:0 CapabilitySpec - A (1)
    M 66:4 CapabilityRegistry.__init__ - A (1)
    M 74:4 CapabilityRegistry._sort - A (1)
src/sophyane/checkpoint.py
    F 40:0 list_checkpoints - A (4)
    F 29:0 load_checkpoint - A (3)
    F 14:0 save_checkpoint - A (2)
    F 58:0 delete_checkpoint - A (2)
src/sophyane/cli_entry.py
    F 10:0 _runtime_identity - B (7)
    F 51:0 _start_local_server_if_needed - B (6)
    F 67:0 main - B (6)
    F 47:0 _metadata_only_invocation - A (2)
    F 42:0 _user_start_tips - A (1)
src/sophyane/coding_runtime.py
    M 387:4 MechanicalVerifier.verify - E (36)
    C 375:0 MechanicalVerifier - C (14)
    M 163:4 RepositoryIndex.search - C (13)
    M 101:4 RepositoryIndex._python_metadata - B (9)
    M 181:4 RepositoryIndex.context - B (9)
    M 87:4 RepositoryIndex._iter_files - B (8)
    M 127:4 RepositoryIndex.build - B (8)
    C 66:0 RepositoryIndex - B (7)
    M 240:4 PatchEngine.replace_lines - B (6)
    M 294:4 TaskQueue.ready - B (6)
    M 282:4 TaskQueue.__init__ - A (5)
    C 279:0 TaskQueue - A (4)
    C 45:0 RepositorySnapshot - A (3)
    C 211:0 PatchEngine - A (3)
    M 217:4 PatchEngine._path - A (3)
    C 315:0 GitCheckpoint - A (3)
    M 341:4 GitCheckpoint.checkpoint - A (3)
    C 356:0 DependencyAdvisor - A (3)
    M 381:4 MechanicalVerifier._path - A (3)
    M 54:4 RepositorySnapshot.to_dict - A (2)
    M 84:4 RepositoryIndex._ignored - A (2)
    M 223:4 PatchEngine.replace_exact - A (2)
    M 311:4 TaskQueue.to_dict - A (2)
    M 326:4 GitCheckpoint.available - A (2)
    M 329:4 GitCheckpoint.status - A (2)
    M 362:4 DependencyAdvisor.diagnose - A (2)
    C 36:0 Symbol - A (1)
    M 75:4 RepositoryIndex.__init__ - A (1)
    M 80:4 RepositoryIndex._relative - A (1)
    C 207:0 PatchError - A (1)
    M 214:4 PatchEngine.__init__ - A (1)
    M 259:4 PatchEngine._evidence - A (1)
    C 270:0 QueueTask - A (1)
    M 301:4 TaskQueue.complete - A (1)
    M 306:4 TaskQueue.fail - A (1)
    M 318:4 GitCheckpoint.__init__ - A (1)
    M 321:4 GitCheckpoint._run - A (1)
    M 378:4 MechanicalVerifier.__init__ - A (1)
src/sophyane/coi.py
    M 107:4 COIOrchestrator.run - B (8)
    M 93:4 COIOrchestrator._dependency_state - A (5)
    C 68:0 COIOrchestrator - A (4)
    M 141:4 COIOrchestrator.queue - A (4)
    F 19:0 ensure_coi_filesystem - A (2)
    F 154:0 status - A (1)
    C 31:0 AgentManifest - A (1)
    C 43:0 TaskContract - A (1)
    C 60:0 COIEvent - A (1)
    M 71:4 COIOrchestrator.__init__ - A (1)
    M 75:4 COIOrchestrator.register - A (1)
    M 80:4 COIOrchestrator.emit - A (1)
    M 85:4 COIOrchestrator.submit - A (1)
src/sophyane/coi_cli.py
    F 11:0 main - A (5)
src/sophyane/collaborative_workers.py
    F 221:0 run_combined - D (21)
    F 281:0 try_combined_reply - B (10)
    F 93:0 plan_workers - B (9)
    F 147:0 ensure_nifdu - B (9)
    F 190:0 ensure_neuron - B (8)
    F 71:0 _run - A (4)
    F 125:0 ensure_source_checkout - A (4)
    F 121:0 _github_tarball_url - A (1)
    C 55:0 WorkerPlan - A (1)
    C 64:0 WorkerResult - A (1)
src/sophyane/config.py
    F 138:0 get_secret - B (10)
    F 122:0 delete_secret - A (5)
    F 30:0 load_json - A (4)
    F 96:0 load_config - A (4)
    F 21:0 ensure_directories - A (3)
    F 40:0 save_json - A (3)
    F 88:0 ensure_default_llm_files - A (3)
    F 159:0 prompt_secret - A (2)
    F 60:0 default_config - A (1)
    F 70:0 default_llm_config - A (1)
    F 108:0 save_config - A (1)
    F 112:0 load_secrets - A (1)
    F 116:0 save_secret - A (1)
src/sophyane/cursor_tab.py
    F 469:0 handle_tab_command - D (21)
    F 148:0 recent_messages - C (14)
    F 99:0 workspace_files - B (10)
    F 286:0 build_suggestions - B (10)
    F 30:0 load_settings - B (6)
    F 697:0 read_main_prompt - B (6)
    M 377:4 ProjectAutoSuggest.get_suggestion - A (5)
    F 85:0 safe_workspace - A (4)
    F 178:0 deduplicate - A (4)
    F 224:0 static_suggestions - A (4)
    F 424:0 accept_word - A (4)
    C 346:0 ProjectAutoSuggest - A (3)
    C 603:0 CursorTabSession - A (3)
    M 680:4 CursorTabSession.prompt - A (3)
```

## Maintainability Index

```text
src/sophyane/__init__.py - A (100.00)
src/sophyane/__main__.py - A (100.00)
src/sophyane/adaptive_execution.py - C (0.00)
src/sophyane/agent.py - A (37.95)
src/sophyane/agent_runtime.py - A (24.62)
src/sophyane/appliance.py - A (29.67)
src/sophyane/artifact_extractor.py - A (37.53)
src/sophyane/audit_cli.py - A (28.33)
src/sophyane/autonomous_builder.py - A (39.31)
src/sophyane/autonomy.py - A (53.26)
src/sophyane/benchmark_cli.py - A (31.38)
src/sophyane/browser_failure_gate.py - A (79.82)
src/sophyane/browser_partial_recovery.py - A (40.03)
src/sophyane/browser_runtime_v2.py - A (40.56)
src/sophyane/budget.py - A (40.34)
src/sophyane/capabilities.py - A (71.58)
src/sophyane/capability_executors.py - A (45.81)
src/sophyane/capability_gap.py - A (31.59)
src/sophyane/capability_gap_messages.py - A (55.75)
src/sophyane/capability_manager.py - A (25.08)
src/sophyane/capability_registry.py - A (36.05)
src/sophyane/checkpoint.py - A (46.47)
src/sophyane/cli_entry.py - A (57.31)
src/sophyane/coding_runtime.py - B (11.41)
src/sophyane/coi.py - A (42.43)
src/sophyane/coi_cli.py - A (47.83)
src/sophyane/collaborative_workers.py - A (34.46)
src/sophyane/config.py - A (33.82)
src/sophyane/cursor_tab.py - B (13.35)
src/sophyane/daemon_runtime.py - A (33.38)
src/sophyane/decision_visibility.py - A (75.77)
src/sophyane/deep_agent_runtime.py - A (46.90)
src/sophyane/diagnostics.py - A (39.01)
src/sophyane/doer.py - B (15.99)
src/sophyane/edge_agent.py - A (60.18)
src/sophyane/editable_canvas.py - A (20.93)
src/sophyane/engineering_program.py - A (49.17)
src/sophyane/environment_constraints.py - A (37.98)
src/sophyane/execution_evidence.py - A (35.77)
src/sophyane/execution_kernel.py - A (54.21)
src/sophyane/execution_runtime.py - B (13.24)
src/sophyane/failure_memory.py - A (32.06)
src/sophyane/feature_audit.py - A (41.47)
src/sophyane/game_validation.py - A (48.13)
src/sophyane/goal_execution.py - B (17.44)
src/sophyane/goal_runtime.py - A (36.66)
src/sophyane/goal_scheduler.py - A (48.34)
src/sophyane/graph_runtime.py - A (26.11)
src/sophyane/guarded_coding_doer.py - A (39.96)
src/sophyane/hardware_api.py - A (22.86)
src/sophyane/hardware_fit.py - A (35.63)
src/sophyane/hardware_registry.py - A (34.93)
src/sophyane/harness.py - A (30.51)
src/sophyane/hitl.py - A (45.17)
src/sophyane/html_repair_policy.py - A (68.61)
src/sophyane/improvement_kernel.py - A (44.52)
src/sophyane/incremental_browser_edit.py - A (44.28)
src/sophyane/integrations.py - A (42.53)
src/sophyane/interactive_coding_doer.py - A (25.24)
src/sophyane/interpreter.py - A (57.49)
src/sophyane/live_coding_doer.py - A (39.87)
src/sophyane/llm_catalog.py - A (36.43)
src/sophyane/local_inspection.py - A (41.26)
src/sophyane/local_runtime.py - C (0.00)
src/sophyane/local_server.py - A (21.90)
src/sophyane/logging_config.py - A (66.01)
src/sophyane/main.py - A (42.92)
src/sophyane/mcp.py - A (100.00)
src/sophyane/mcp_bridge.py - A (61.22)
src/sophyane/media_voice.py - A (43.39)
src/sophyane/memory.py - A (33.35)
src/sophyane/memory_architecture.py - C (2.36)
src/sophyane/mobile_capability_prompt.py - A (85.75)
src/sophyane/mobile_permission_center.py - A (63.59)
src/sophyane/mobile_sensor_routing.py - A (73.36)
src/sophyane/model_catalog.py - A (100.00)
src/sophyane/multiagent.py - A (20.75)
src/sophyane/multimodal.py - A (62.71)
src/sophyane/native_backends.py - A (47.26)
src/sophyane/native_capability.py - A (59.87)
src/sophyane/native_kernel.py - A (38.23)
src/sophyane/native_readonly_capabilities.py - C (0.00)
src/sophyane/native_worker_pool.py - A (35.81)
src/sophyane/notifications.py - A (63.64)
src/sophyane/observability.py - A (55.28)
src/sophyane/permissions.py - A (52.86)
src/sophyane/platform_cli.py - A (42.59)
src/sophyane/platform_kernel.py - A (24.90)
src/sophyane/platform_probe.py - A (36.90)
src/sophyane/plugin_loader.py - A (51.33)
src/sophyane/post_build_menu.py - A (20.46)
src/sophyane/provider_state.py - A (75.00)
src/sophyane/rag.py - A (38.71)
src/sophyane/recursive_visual_engine.py - A (19.17)
src/sophyane/release_cli.py - A (60.51)
src/sophyane/repository.py - A (38.14)
src/sophyane/request_classification.py - A (61.52)
src/sophyane/request_intercepts.py - A (39.27)
src/sophyane/router.py - A (57.09)
src/sophyane/runtime_artifact_patch.py - A (38.17)
src/sophyane/runtime_browser_patch.py - A (39.89)
src/sophyane/runtime_cancel.py - A (41.75)
src/sophyane/runtime_capability_acquisition_patch.py - A (47.69)
src/sophyane/runtime_cloud_timeout_patch.py - A (94.88)
src/sophyane/runtime_cursor_tab_patch.py - A (100.00)
src/sophyane/runtime_deep_agent_patch.py - A (66.88)
src/sophyane/runtime_filesystem_capabilities_v20.py - C (0.65)
src/sophyane/runtime_input_patch.py - A (61.51)
src/sophyane/runtime_intent_refinement_patch.py - A (35.75)
src/sophyane/runtime_interactive_patch.py - A (46.98)
src/sophyane/runtime_interrupt_patch.py - A (61.86)
src/sophyane/runtime_observability.py - A (29.42)
src/sophyane/runtime_orchestration_patch.py - A (45.91)
src/sophyane/runtime_premium_asset_pipeline.py - A (46.55)
src/sophyane/runtime_provider_context_patch.py - A (32.95)
src/sophyane/runtime_provider_error_patch.py - A (68.72)
src/sophyane/runtime_quality_escalation.py - A (44.76)
src/sophyane/runtime_safety.py - A (45.69)
src/sophyane/runtime_self_contained_html_patch.py - A (48.00)
src/sophyane/runtime_semantic_instruction.py - A (34.61)
src/sophyane/runtime_sli_brain.py - A (33.01)
src/sophyane/runtime_sli_builder.py - A (60.79)
src/sophyane/scheduler.py - A (41.01)
src/sophyane/runtime_sli_capability_planner.py - A (40.55)
src/sophyane/runtime_sli_intent_patch.py - A (82.27)
src/sophyane/runtime_sli_mission_os.py - A (43.91)
src/sophyane/runtime_sli_semantic.py - A (38.07)
src/sophyane/runtime_software_routing_guard.py - A (60.23)
src/sophyane/semantic_ontology.py - B (17.53)
src/sophyane/semantic_ontology_learner.py - C (6.50)
src/sophyane/sli.py - A (43.87)
src/sophyane/sli_learner.py - A (40.82)
src/sophyane/sli_provider_controller.py - A (35.70)
src/sophyane/startup_policy.py - A (27.04)
src/sophyane/state_graph.py - A (46.68)
src/sophyane/strict_protocol.py - A (37.73)
src/sophyane/tools.py - A (34.79)
src/sophyane/tui_v2.py - C (0.00)
src/sophyane/v12_cli.py - A (54.00)
src/sophyane/v13_cli.py - C (2.69)
src/sophyane/workspace_attachment.py - A (31.87)
src/sophyane/mission_engine.py - A (27.25)
src/sophyane/mcp_server.py - A (47.14)
src/sophyane/local_coding_capability.py - A (31.69)
src/sophyane/multifile_artifact_extractor.py - A (46.60)
src/sophyane/runtime_sli_onset_feedback.py - A (32.35)
src/sophyane/runtime_snake_semantic_repair.py - A (66.69)
src/sophyane/runtime_stagnation_patch.py - A (41.38)
src/sophyane/secret_vault.py - A (46.65)
src/sophyane/semantic_ontology_bridge.py - A (100.00)
src/sophyane/setup_wizard.py - B (13.63)
src/sophyane/skills.py - A (46.90)
src/sophyane/sli_cli.py - A (51.62)
src/sophyane/sli_intent_router.py - A (62.58)
src/sophyane/sli_schema.py - A (51.38)
src/sophyane/sli_training_loop.py - A (25.37)
src/sophyane/strict_interactive_doer.py - A (23.30)
src/sophyane/structured_output.py - A (54.79)
src/sophyane/task_execution.py - C (5.47)
src/sophyane/task_intelligence.py - A (33.17)
src/sophyane/task_runtime.py - A (25.71)
src/sophyane/tui.py - A (45.15)
src/sophyane/v16_doer.py - A (25.88)
src/sophyane/vela.py - A (36.00)
src/sophyane/version.py - A (100.00)
src/sophyane/web.py - A (48.04)
src/sophyane/web_intel.py - B (12.76)
src/sophyane/mission_cli.py - A (47.11)
src/sophyane/unified_execution_kernel.py - A (36.27)
src/sophyane/harness_task_policy.py - A (45.00)
src/sophyane/harness_workspace.py - A (58.15)
src/sophyane/harness_acceptance.py - A (60.21)
src/sophyane/browser/__init__.py - A (100.00)
src/sophyane/browser/launcher.py - A (51.40)
src/sophyane/cloud/__init__.py - A (100.00)
src/sophyane/cloud/auto_messaging_setup.py - A (53.98)
src/sophyane/cloud/crypto_billing.py - B (15.48)
src/sophyane/cloud/email_otp.py - A (51.48)
src/sophyane/cloud/messaging.py - B (16.78)
src/sophyane/cloud/namecheap.py - A (33.18)
src/sophyane/cloud/payments_rails.py - B (17.50)
src/sophyane/cloud/portal.py - C (0.00)
src/sophyane/cloud/pricing.py - A (82.26)
src/sophyane/cloud/product_knowledge.py - A (51.53)
src/sophyane/cloud/store.py - A (32.70)
src/sophyane/cloud/stripe_billing.py - A (43.30)
src/sophyane/cloud/telegram_bot.py - B (17.30)
src/sophyane/competitive/__init__.py - A (100.00)
src/sophyane/competitive/agent_session_api.py - A (23.66)
src/sophyane/competitive/auth.py - B (17.74)
src/sophyane/competitive/payments.py - A (30.83)
src/sophyane/connectors/__init__.py - A (100.00)
src/sophyane/connectors/runtime.py - A (28.51)
src/sophyane/connectors/email_imap/handler.py - A (27.94)
src/sophyane/continual/__init__.py - A (100.00)
src/sophyane/continual/engine.py - A (25.08)
src/sophyane/expert/__init__.py - A (100.00)
src/sophyane/expert/answer.py - A (52.43)
src/sophyane/expert/exam.py - A (44.35)
src/sophyane/expert/knowledge.py - A (64.32)
src/sophyane/kernel/__init__.py - A (100.00)
src/sophyane/kernel/app_factory.py - A (32.50)
src/sophyane/kernel/bus.py - A (59.18)
src/sophyane/kernel/core.py - A (38.21)
src/sophyane/kernel/erp.py - A (49.71)
src/sophyane/lc_compat/__init__.py - A (100.00)
src/sophyane/lc_compat/durable_graph.py - A (48.93)
src/sophyane/lc_compat/graph_viz.py - A (59.94)
src/sophyane/lc_compat/llm.py - A (61.78)
src/sophyane/lc_compat/memory.py - A (50.64)
src/sophyane/lc_compat/output_parsers.py - A (48.84)
src/sophyane/lc_compat/prompt_templates.py - A (50.72)
src/sophyane/lc_compat/streaming.py - A (53.23)
src/sophyane/lc_compat/tools.py - A (63.94)
src/sophyane/mesh/__init__.py - A (100.00)
src/sophyane/mesh/core.py - A (21.11)
src/sophyane/mesh/discovery.py - A (25.37)
src/sophyane/mesh/federation.py - A (41.19)
src/sophyane/mesh/install_peer.py - A (45.24)
src/sophyane/observability/__init__.py - A (54.89)
src/sophyane/observability/accounting.py - A (52.93)
src/sophyane/observability/datasets.py - A (34.79)
src/sophyane/observability/tracing.py - A (40.75)
src/sophyane/providers/__init__.py - A (100.00)
src/sophyane/providers/anthropic.py - A (63.21)
src/sophyane/providers/base.py - A (100.00)
src/sophyane/providers/deepseek.py - A (100.00)
src/sophyane/providers/fallback.py - A (30.25)
src/sophyane/providers/gemini.py - A (39.66)
src/sophyane/providers/groq.py - A (100.00)
src/sophyane/providers/http.py - A (63.83)
src/sophyane/providers/local_gguf.py - A (34.03)
src/sophyane/providers/ollama.py - A (63.14)
src/sophyane/providers/openai.py - A (58.28)
src/sophyane/providers/openai_compatible.py - A (61.24)
src/sophyane/providers/openrouter.py - A (100.00)
src/sophyane/providers/xai.py - A (100.00)
src/sophyane/self_improve/__init__.py - A (100.00)
src/sophyane/self_improve/ledger.py - A (31.66)
```

## Manual Verification Required

1. Trace provider-controlled data into every subprocess call.
2. Separate intentional command execution from unintended shell injection.
3. Inspect real calls to built-in `eval()` and `exec()`; ignore regex
   strings, comments and names containing those words.
4. Confirm Vulture findings against dynamic runtime patch installation.
5. Benchmark suspected bottlenecks before assigning performance severity.
6. Compare duplicate modules through imports, entry points and tests before
   proposing removal.
7. Record exact file and line evidence for each accepted finding.

## Prioritized Verified Findings

### P0 — Runtime correctness

#### Undefined `primary_snip`
- File: `src/sophyane/cloud/portal.py`
- Locations: lines reported by Pyflakes near 1193 and 1220
- Severity: Critical if those branches are reachable
- Evidence: Pyflakes reports an undefined local name.
- Required verification:
  - inspect the enclosing function and control flow;
  - determine whether `primary_snip` should be assigned before both uses;
  - add a regression test that executes both branches.
- Proposed patch:
  - initialize the variable on every path, or replace it with the correct existing variable;
  - do not suppress the warning.

#### Undefined `error`
- File: `src/sophyane/expert/exam.py`
- Location: near line 53
- Severity: High
- Evidence: Pyflakes reports `error` used outside the scope in which it is assigned.
- Proposed patch:
  - move the dependent statement inside the exception block, or initialize a result variable before the block;
  - add a test covering the exception path.

### P1 — Ambiguous duplicate definitions

#### `install_input_capture`
- File: `src/sophyane/request_intercepts.py`
- Severity: High
- Risk: the later definition silently replaces the earlier implementation.
- Proposed patch:
  - compare behavior and call sites;
  - preserve one canonical implementation;
  - rename genuinely distinct variants;
  - add import-level and behavior tests.

#### `list_traces`
- File: `src/sophyane/observability/__init__.py`
- Severity: High
- Risk: silent replacement of the earlier implementation and inconsistent tracing behavior.
- Proposed patch:
  - consolidate into one implementation;
  - explicitly delegate to the intended backend;
  - add tests for empty, populated and malformed trace stores.

### P2 — Low-risk cleanup

Remove imports and assignments only after confirming they are not retained for:
- runtime registration,
- monkey-patch installation,
- import side effects,
- optional dependency probing,
- public API compatibility.

The full test suite currently passes, so cleanup must be made incrementally with focused tests after each group.

### Verified repair — deferred exception closure

- File: `src/sophyane/expert/exam.py`
- Root cause: the nested fallback generator closed over an exception target
  variable that Python clears after leaving the `except` block.
- Impact: delayed invocation could raise `NameError` instead of the original
  provider initialization failure.
- Repair: captured a stable formatted error message before returning the
  deferred generator.
- Regression coverage:
  `tests/test_expert_exam_provider_failure.py`.

### Verified repair — undefined primary search evidence

- File: `src/sophyane/cloud/portal.py`
- Root cause: grounded-response comparison referenced `primary_snip` without
  assigning it anywhere in the enclosing execution path.
- Impact: factual queries reaching model-versus-search validation could raise
  `NameError` and fall into a generic fallback path.
- Repair: derive the primary textual extract from the first search result,
  accepting `snippet`, `content`, `text`, or `description`, with the complete
  grounded response as fallback.
- Verification:
  - `tests/test_portal_primary_search_evidence.py`
  - Pyflakes no longer reports `primary_snip` as undefined.
- Remaining Pyflakes findings in this file:
  - unused `os` import;
  - unused `urllib.parse.parse_qs` import.

### Verified repair — duplicate trace-listing implementations

- File: `src/sophyane/observability/__init__.py`
- Root cause: two public `list_traces()` definitions existed in the same
  module; the later definition silently replaced the earlier native-backend
  compatibility wrapper.
- Impact: trace results depended on definition order and could ignore one
  trace backend.
- Repair:
  - renamed the implementations to `_list_native_traces()` and
    `_list_compat_traces()`;
  - added one public `list_traces()` entry point;
  - merged and deduplicated trace records;
  - retained compatibility if either backend fails.
- Regression coverage:
  `tests/test_observability_list_traces_merge.py`.

### Verified repair — input-capture closure binding

- File: `src/sophyane/request_intercepts.py`
- Root cause: nested input wrappers captured repeatedly reassigned variables
  named `original` and `original_async`.
- Impact: wrappers could invoke another framework's input function, including
  recursive `builtins.input` and Rich input calls.
- Repair:
  - assigned a unique bound callable for every nested wrapper;
  - retained one canonical `install_input_capture()` implementation.
- Regression coverage:
  `tests/test_request_input_capture_single_definition.py`.

### Verified repair — dead adaptive execution contract calculation

- File: `src/sophyane/adaptive_execution.py`
- Root cause:
  - `run_adaptive_loop()` calculated `execution_contract` but never consumed
    it;
  - repair prompts already obtain the same policy through
    `execution_prefix_for_repair()`;
  - the initial provider response is supplied before this loop begins, so the
    local variable could not influence initial planning.
- Impact:
  - misleading code suggested an execution policy was being applied where it
    was not;
  - unnecessary import and exception handling added maintenance noise.
- Repair:
  - removed the unused `execution_contract` calculation;
  - retained contract injection in `_compact_repair_prompt()`;
  - removed the unused `json` import.
- Regression coverage:
  `tests/test_adaptive_execution_contract_cleanup.py`.

### Verified repair — dead latest-file machine-scope state

- File: `src/sophyane/tui_v2.py`
- Root cause:
  - `_is_latest_file_inspection_request()` calculated `has_machine`;
  - the result was never used in its routing decision;
  - the surrounding comment explicitly stated that machine terms were not
    mandatory.
- Impact:
  - misleading dead state implied that words such as `computer`, `home`, or
    `system` affected routing when they did not;
  - Pyflakes reported the unused local variable.
- Repair:
  - removed `machine_terms` and `has_machine`;
  - retained the existing semantic decision based on file and latest/amendment
    wording;
  - clarified that capability-level scope enforcement remains responsible for
    workspace or user-home boundaries.
- Regression coverage:
  `tests/test_latest_file_routing_cleanup.py`.

### Verified repair — unused TUI dataclass conversion import

- File: `src/sophyane/tui_v2.py`
- Root cause: a local `dataclasses.asdict` import remained after the related
  conversion logic was removed or refactored.
- Impact:
  - dead import reported by Pyflakes;
  - misleading dependency suggested dataclass serialization still occurred in
    that execution path.
- Repair:
  - confirmed through AST analysis that `asdict` had no runtime loads;
  - removed only the unused import.
- Regression coverage:
  `tests/test_tui_unused_asdict_cleanup.py`.

### Verified repair — placeholder-free platform probe f-string

- File: `src/sophyane/platform_probe.py`
- Root cause: a string literal used an `f` prefix despite containing no
  formatted expressions.
- Impact:
  - Pyflakes reported misleading formatting syntax;
  - the prefix suggested interpolation where none occurred.
- Repair:
  - confirmed through AST analysis that the string contained no
    `FormattedValue`;
  - removed only the unnecessary `f` prefix.
- Regression coverage:
  `tests/test_platform_probe_empty_fstring_cleanup.py`.

### Verified repair — dead local task-execution failure state

- File: `src/sophyane/task_execution.py`
- Root cause: the execution loop maintained plain local assignments to
  `failure`, but no runtime path read that local variable.
- Important distinction: the annotated `failure: str` field is part of a
  result/data structure and was preserved.
- Repair:
  - removed only plain local `failure = ""` and
    `failure = result.error` assignments;
  - preserved `failed_action`, `previous_failure`, accumulated results, and
    the annotated failure field.
- Regression coverage:
  `tests/test_task_execution_unused_failure_cleanup.py`.

### Verified repair — unused task-execution sys import

- File: `src/sophyane/task_execution.py`
- Root cause: `sys` remained imported after the code path using it was
  removed or refactored.
- Repair:
  - confirmed through AST analysis that the module had no runtime `sys`
    loads;
  - removed only the unused import.
- Regression coverage:
  `tests/test_task_execution_unused_sys_cleanup.py`.

### Verified repair — ambiguous CLI provider callback rebinding

- File: `src/sophyane/v13_cli.py`
- Root cause:
  - the `--ask` path first assigned `generate = None`;
  - it then declared a nested function with the same name;
  - Pyflakes reported the function as redefining the earlier unused binding.
- Impact:
  - the name served both as nullable state and a callable definition;
  - this obscured fallback behavior and produced a static-analysis warning.
- Repair:
  - introduced `generate_callback` as the nullable callback variable;
  - renamed the nested function to `provider_generate`;
  - used an explicit `Callable[[str, str], str] | None` annotation;
  - preserved expert-mode fallback when provider creation fails.
- Regression coverage:
  `tests/test_v13_cli_generate_callback.py`.

### Verified repair — unused cloud portal imports

- File: `src/sophyane/cloud/portal.py`
- Root cause:
  - `os` was imported but had no runtime loads;
  - `urllib.parse.parse_qs` was imported but had no runtime loads.
- Impact:
  - Pyflakes reported dead imports;
  - the imports misleadingly suggested operating-system and query-string
    parsing behavior in this module.
- Repair:
  - verified both names through AST analysis;
  - removed only the unused imports;
  - preserved all other imports from the same statements.
- Regression coverage:
  `tests/test_portal_unused_imports_cleanup.py`.

### Verified repair — unused harness-workspace regular-expression import

- File: `src/sophyane/harness_workspace.py`
- Root cause: `re` remained imported even though workspace classification and
  path selection no longer used regular-expression operations.
- Impact:
  - Pyflakes reported a dead import;
  - the dependency misleadingly suggested regex-based project routing.
- Repair:
  - confirmed through AST analysis that `re` had no runtime loads;
  - removed only the unused import;
  - preserved new-project detection and isolated-workspace selection.
- Regression coverage:
  `tests/test_harness_workspace_unused_re_cleanup.py`.

### Verified repair — dead local-runtime library-directory state

- File: `src/sophyane/local_runtime.py`
- Root cause: a function assigned a path or directory value to `lib_dir`, but
  no runtime branch subsequently read that local variable.
- Impact:
  - Pyflakes reported dead local state;
  - the assignment misleadingly suggested that the derived library directory
    affected runtime discovery or execution.
- Repair:
  - confirmed through AST analysis that `lib_dir` had one function-local
    assignment and no runtime loads;
  - removed only that assignment;
  - retained the surrounding runtime-discovery behavior.
- Regression coverage:
  `tests/test_local_runtime_unused_lib_dir_cleanup.py`.

### Verified repair — unused local-coding shlex import

- File: `src/sophyane/local_coding_capability.py`
- Root cause: `shlex` was imported even though the module had no runtime
  references to it.
- Impact:
  - Pyflakes reported a dead import;
  - the import misleadingly suggested that this capability performed shell
    tokenization or quoting.
- Repair:
  - confirmed through AST analysis that `shlex` had no runtime loads;
  - removed only the unused import;
  - preserved local coding capability behavior and entry points.
- Regression coverage:
  `tests/test_local_coding_unused_shlex_cleanup.py`.

### Verified repair — unused main-module imports

- File: `src/sophyane/main.py`
- Root cause:
  - `sys` was imported without runtime use;
  - `tools_description` was imported from `sophyane.tools` but never read.
- Impact:
  - Pyflakes reported dead imports;
  - `tools_description` misleadingly suggested that provider creation or the
    main entry point consumed tool metadata.
- Repair:
  - verified both names had no runtime loads through AST analysis;
  - removed only the unused imports;
  - preserved the provider factory and main entry points.
- Regression coverage:
  `tests/test_main_unused_imports_cleanup.py`.

### Verified repair — unused capabilities dataclass field import

- File: `src/sophyane/capabilities.py`
- Root cause: `field` was imported from `dataclasses` but had no runtime
  references in the module.
- Impact:
  - Pyflakes reported a dead import;
  - the import misleadingly suggested that capability dataclasses used
    custom factories, defaults, metadata, or comparison settings.
- Repair:
  - confirmed through AST analysis that `field` had no runtime loads;
  - removed only `field`;
  - preserved any other imports from `dataclasses`.
- Regression coverage:
  `tests/test_capabilities_unused_field_cleanup.py`.

### Verified repair — unused capability-executor asdict import

- File: `src/sophyane/capability_executors.py`
- Root cause: `asdict` was imported from `dataclasses` but had no runtime
  references in the module.
- Impact:
  - Pyflakes reported a dead import;
  - the import misleadingly suggested that executor results or capability
    records were serialized through dataclass conversion.
- Repair:
  - confirmed through AST analysis that `asdict` had no runtime loads;
  - removed only the unused import;
  - preserved any other `dataclasses` imports.
- Regression coverage:
  `tests/test_capability_executors_unused_asdict_cleanup.py`.

### Verified repair — feature-audit import consolidation

- File: `src/sophyane/feature_audit.py`
- Root cause:
  - `Path` was imported four times in different scopes;
  - local imports shadowed the canonical top-level binding;
  - `json`, `urllib.request`, and `dataclasses.field` had no runtime uses.
- Repair:
  - retained one canonical `pathlib.Path` import because `Path` is actively
    used;
  - removed three redundant shadowing `Path` imports;
  - removed unused `json`, `urllib.request`, and `field` imports.
- Verification:
  - Pyflakes reports no remaining findings for this module;
  - focused feature-audit and observability tests pass;
  - the complete repository test suite passes.
- Regression coverage:
  `tests/test_feature_audit_import_cleanup.py`.

### Verified repair — ineffective Telegram username-cache placeholder

- File: `src/sophyane/cloud/messaging.py`
- Function: `telegram_get_me()`
- Root cause:
  - the function loaded the messaging environment into `e`;
  - `e` was never read;
  - the following username/cache condition contained only `pass`.
- Impact:
  - Pyflakes reported dead local state;
  - comments implied that the Telegram username was cached although no write
    occurred;
  - the unnecessary environment-file read added minor I/O and maintenance
    noise.
- Repair:
  - removed the unused environment load and no-op cache condition;
  - preserved successful API, API-error, and exception return behavior.
- Regression coverage:
  `tests/test_cloud_messaging_telegram_get_me.py`.

### Verified repair — unused Namecheap DNS response binding

- File: `src/sophyane/cloud/namecheap.py`
- Function: `set_hosts()`
- Root cause:
  - the result of `namecheap.domains.dns.setHosts` was assigned to `root`;
  - no subsequent code read that XML result.
- Impact:
  - Pyflakes reported dead local state;
  - the binding implied that the API response influenced the returned summary,
    although only successful completion of `_call()` mattered.
- Repair:
  - preserved the required Namecheap API call and its exception behavior;
  - removed only the unused response binding;
  - retained the existing DNS summary response.
- Regression coverage:
  `tests/test_namecheap_set_hosts_result_cleanup.py`.

### Verified repair — dead federated aggregation peer state

- File: `src/sophyane/continual/engine.py`
- Function: `federated_aggregate()`
- Root cause:
  - the function read the configured peer ID into a local variable named
    `peer`;
  - the local adapter was always copied into the fixed `peer_deltas/self`
    directory;
  - no later branch read `peer`.
- Impact:
  - Pyflakes reported dead local state;
  - the assignment misleadingly suggested that the configured peer ID
    affected local-delta naming or aggregation.
- Repair:
  - removed only the unused peer-ID assignment;
  - preserved the `self` directory convention, adapter copies, C++ aggregate
    invocation, metadata parsing, and pooled-peer count.
- Regression coverage:
  `tests/test_continual_unused_peer_cleanup.py`.

### Verified repair — unused coding-runtime imports

- File: `src/sophyane/coding_runtime.py`
- Root cause:
  - `fnmatch` was imported but had no runtime references;
  - `os` was imported but had no runtime references.
- Impact:
  - Pyflakes reported two dead imports;
  - the dependencies misleadingly suggested filename-pattern matching and
    operating-system operations in this runtime module.
- Repair:
  - confirmed both names had no runtime loads through AST analysis;
  - removed only the unused imports;
  - preserved coding-runtime entry points and execution behavior.
- Regression coverage:
  `tests/test_coding_runtime_unused_imports_cleanup.py`.

### Verified repair — dead mobile-filesystem test state

- File: `tests/test_tui_mobile_filesystem.py`
- Root cause:
  - the test assigned a value to `original_home`;
  - no assertion, cleanup path, or runtime branch read that variable.
- Impact:
  - Pyflakes reported dead local state;
  - the assignment suggested that the original home directory was restored
    manually even though test isolation was handled elsewhere.
- Repair:
  - confirmed through AST analysis that `original_home` had one assignment
    and no runtime loads;
  - removed only the unused assignment;
  - preserved mobile filesystem routing and workspace-isolation tests.
- Regression coverage:
  `tests/test_tui_mobile_original_home_cleanup.py`.

### Verified repair — unused collaborative-worker imports

- File: `src/sophyane/collaborative_workers.py`
- Root cause:
  - `json` was imported without runtime use;
  - `urllib.request` was imported without runtime use.
- Repair:
  - verified both names had no runtime loads;
  - removed only the unused imports;
  - preserved `run_combined()` and combined-worker result handling.
- Regression coverage:
  `tests/test_collaborative_workers_unused_imports_cleanup.py`.

### Verified repair — unused failure-memory Iterable import

- File: `src/sophyane/failure_memory.py`
- Root cause: `Iterable` was imported from `typing` but had no runtime or
  annotation references in the module.
- Impact:
  - Pyflakes reported a dead import;
  - the import misleadingly suggested that failure-memory APIs accepted or
    returned generic iterable values.
- Repair:
  - confirmed through AST analysis that `Iterable` had no loads;
  - removed only the unused import;
  - preserved all other names imported from `typing`.
- Regression coverage:
  `tests/test_failure_memory_unused_iterable_cleanup.py`.

### Verified repair — unused goal-execution Mapping import

- File: `src/sophyane/goal_execution.py`
- Root cause: `Mapping` was imported from `collections.abc` but had no
  runtime or annotation references.
- Impact:
  - Pyflakes reported a dead import;
  - the import misleadingly suggested that goal-execution APIs consumed a
    generic mapping abstraction.
- Repair:
  - confirmed through AST analysis that `Mapping` had no loads;
  - removed only the unused import;
  - preserved all other `collections.abc` imports.
- Regression coverage:
  `tests/test_goal_execution_unused_mapping_cleanup.py`.

### Verified repair — unused goal-scheduler Iterable import

- File: `src/sophyane/goal_scheduler.py`
- Root cause: `Iterable` was imported from `typing` but had no runtime or
  annotation references.
- Impact:
  - Pyflakes reported a dead import;
  - the import misleadingly suggested that scheduler APIs consumed generic
    iterable inputs.
- Repair:
  - confirmed through AST analysis that `Iterable` had no loads;
  - removed only the unused import;
  - preserved all other names imported from `typing`.
- Regression coverage:
  `tests/test_goal_scheduler_unused_iterable_cleanup.py`.

### Verified repair — unused hardware API edge-system prompt import

- File: `src/sophyane/hardware_api.py`
- Root cause: `EDGE_SYSTEM_PROMPT` was imported from
  `sophyane.edge_agent` but had no runtime or annotation references.
- Impact:
  - Pyflakes reported a dead import;
  - the dependency misleadingly suggested that hardware API responses were
    conditioned by the edge-agent system prompt.
- Repair:
  - confirmed through AST analysis that `EDGE_SYSTEM_PROMPT` had no loads;
  - removed only the unused import;
  - preserved all other edge-agent imports.
- Regression coverage:
  `tests/test_hardware_api_unused_edge_prompt_cleanup.py`.

### Verified repair — unused hardware-fit save_config import

- File: `src/sophyane/hardware_fit.py`
- Root cause: `save_config` was imported from `sophyane.config` but had no
  runtime or annotation references.
- Impact:
  - Pyflakes reported a dead import;
  - the dependency misleadingly suggested that hardware-fit evaluation
    persisted configuration changes.
- Repair:
  - confirmed through AST analysis that `save_config` had no loads;
  - removed only the unused import;
  - preserved all other configuration imports.
- Regression coverage:
  `tests/test_hardware_fit_unused_save_config_cleanup.py`.

### Verified repair — unused hardware-registry imports

- File: `src/sophyane/hardware_registry.py`
- Root cause:
  - `json` was imported without runtime use;
  - `os` was imported without runtime use;
  - `re` was imported without runtime use.
- Impact:
  - Pyflakes reported three dead imports;
  - the imports misleadingly suggested JSON serialization, operating-system
    access, and regex-based registry matching.
- Repair:
  - confirmed all three names had no runtime loads through AST analysis;
  - removed only the unused imports;
  - preserved hardware registry behavior and entry points.
- Regression coverage:
  `tests/test_hardware_registry_unused_imports_cleanup.py`.

### Verified repair — unused incremental-browser HTML import

- File: `src/sophyane/incremental_browser_edit.py`
- Root cause: the standard-library `html` module was imported as `html_lib`
  but had no runtime or annotation references.
- Impact:
  - Pyflakes reported a dead import;
  - the alias misleadingly suggested that incremental browser edits performed
    HTML escaping or unescaping through the standard-library module.
- Repair:
  - confirmed through AST analysis that `html_lib` had no loads;
  - removed only the unused aliased import;
  - preserved browser-edit parsing and update behavior.
- Regression coverage:
  `tests/test_incremental_browser_unused_html_cleanup.py`.

### Verified repair — unused interactive-coding JSON import

- File: `src/sophyane/interactive_coding_doer.py`
- Root cause: `json` was imported but had no runtime or annotation
  references.
- Impact:
  - Pyflakes reported a dead import;
  - the dependency misleadingly suggested local JSON parsing or
    serialization in the interactive coding path.
- Repair:
  - confirmed through AST analysis that `json` had no loads;
  - removed only the unused import;
  - preserved interactive coding behavior and entry points.
- Regression coverage:
  `tests/test_interactive_coding_doer_unused_json_cleanup.py`.

### Verified repair — unused live-coding imports

- File: `src/sophyane/live_coding_doer.py`
- Root cause:
  - `asdict` was imported from `dataclasses` without runtime use;
  - `Callable` was imported from `typing` without runtime or annotation use.
- Impact:
  - Pyflakes reported two dead imports;
  - the dependencies misleadingly suggested dataclass serialization and
    callback type usage in the live-coding path.
- Repair:
  - confirmed both names had no loads through AST analysis;
  - removed only the unused imports;
  - preserved all other imports from `dataclasses` and `typing`.
- Regression coverage:
  `tests/test_live_coding_doer_unused_imports_cleanup.py`.

### Verified repair — unused memory-architecture time import

- File: `src/sophyane/memory_architecture.py`
- Root cause: `time` was imported but had no runtime or annotation
  references.
- Impact:
  - Pyflakes reported a dead import;
  - the dependency misleadingly suggested direct wall-clock or elapsed-time
    handling in the memory architecture module.
- Repair:
  - confirmed through AST analysis that `time` had no loads;
  - removed only the unused import;
  - preserved memory storage, retrieval, and database behavior.
- Regression coverage:
  `tests/test_memory_architecture_unused_time_cleanup.py`.

### Verified repair — unused multiagent Callable import

- File: `src/sophyane/multiagent.py`
- Root cause: `Callable` was imported from `typing` but had no runtime or
  annotation references.
- Impact:
  - Pyflakes reported a dead import;
  - the import misleadingly suggested that multi-agent APIs accepted typed
    callback functions.
- Repair:
  - confirmed through AST analysis that `Callable` had no loads;
  - removed only the unused import;
  - preserved all other names imported from `typing`.
- Regression coverage:
  `tests/test_multiagent_unused_callable_cleanup.py`.

### Verified repair — unused native-worker-pool Path import

- File: `src/sophyane/native_worker_pool.py`
- Root cause: `Path` was imported from `pathlib` but had no runtime or
  annotation references.
- Impact:
  - Pyflakes reported a dead import;
  - the dependency misleadingly suggested filesystem-path handling inside the
    native worker-pool module.
- Repair:
  - confirmed through AST analysis that `Path` had no loads;
  - removed only the unused import;
  - preserved native worker-pool behavior and entry points.
- Regression coverage:
  `tests/test_native_worker_pool_unused_path_cleanup.py`.

### Verified repair — unused platform-kernel imports

- File: `src/sophyane/platform_kernel.py`
- Root cause:
  - `os` was imported without runtime use;
  - `subprocess` was imported without runtime use.
- Impact:
  - Pyflakes reported two dead imports;
  - the dependencies misleadingly suggested direct operating-system and
    subprocess handling in this platform abstraction.
- Repair:
  - confirmed both names had no runtime loads through AST analysis;
  - removed only the unused imports;
  - preserved platform-kernel behavior and entry points.
- Regression coverage:
  `tests/test_platform_kernel_unused_imports_cleanup.py`.

### Verified repair — unused repository os import

- File: `src/sophyane/repository.py`
- Root cause: `os` was imported but had no runtime or annotation references.
- Impact:
  - Pyflakes reported a dead import;
  - the dependency misleadingly suggested direct operating-system access in
    the repository abstraction.
- Repair:
  - confirmed through AST analysis that `os` had no loads;
  - removed only the unused import;
  - preserved repository behavior and entry points.
- Regression coverage:
  `tests/test_repository_unused_os_cleanup.py`.

### Verified repair — unused runtime intent-refinement JSON import

- File: `src/sophyane/runtime_intent_refinement_patch.py`
- Root cause: `json` was imported but had no runtime or annotation
  references.
- Impact:
  - Pyflakes reported a dead import;
  - the dependency misleadingly suggested JSON parsing or serialization in
    the runtime intent-refinement patch.
- Repair:
  - confirmed through AST analysis that `json` had no loads;
  - removed only the unused import;
  - preserved intent-refinement installation and routing behavior.
- Regression coverage:
  `tests/test_runtime_intent_refinement_unused_json_cleanup.py`.

### Verified repair — unused runtime SLI mission regex import

- File: `src/sophyane/runtime_sli_mission_os.py`
- Root cause: `re` was imported but had no runtime or annotation references.
- Impact:
  - Pyflakes reported a dead import;
  - the dependency misleadingly suggested regex-based mission parsing in this
    runtime patch.
- Repair:
  - confirmed through AST analysis that `re` had no loads;
  - removed only the unused import;
  - preserved mission-runtime installation and execution behavior.
- Regression coverage:
  `tests/test_runtime_sli_mission_os_unused_re_cleanup.py`.

### Verified repair — unused SLI learner Path import

- File: `src/sophyane/sli_learner.py`
- Root cause: `Path` was imported from `pathlib` but had no runtime or
  annotation references.
- Impact:
  - Pyflakes reported a dead import;
  - the dependency misleadingly suggested direct filesystem-path handling in
    the SLI learner.
- Repair:
  - confirmed through AST analysis that `Path` had no loads;
  - removed only the unused import;
  - preserved SLI learning behavior and entry points.
- Regression coverage:
  `tests/test_sli_learner_unused_path_cleanup.py`.

### Verified repair — unused state-graph MutableMapping import

- File: `src/sophyane/state_graph.py`
- Root cause: `MutableMapping` was imported from `typing` but had no runtime
  or annotation references.
- Impact:
  - Pyflakes reported a dead import;
  - the import misleadingly suggested that graph state APIs required the
    mutable mapping abstraction.
- Repair:
  - confirmed through AST analysis that `MutableMapping` had no loads;
  - removed only the unused import;
  - preserved all other names imported from `typing`.
- Regression coverage:
  `tests/test_state_graph_unused_mutable_mapping_cleanup.py`.

### Verified repair — unused tools Callable import

- File: `src/sophyane/tools.py`
- Root cause: `Callable` was imported from `typing` but had no runtime or
  annotation references.
- Impact:
  - Pyflakes reported a dead import;
  - the import misleadingly suggested that tool APIs exposed typed callback
    interfaces.
- Repair:
  - confirmed through AST analysis that `Callable` had no loads;
  - removed only the unused import;
  - preserved all other names imported from `typing`.
- Regression coverage:
  `tests/test_tools_unused_callable_cleanup.py`.

### Verified repair — unused setup-wizard ModelChoice import

- File: `src/sophyane/setup_wizard.py`
- Root cause: `ModelChoice` was imported from `sophyane.model_catalog` but
  had no runtime or annotation references.
- Impact:
  - Pyflakes reported a dead import;
  - the dependency misleadingly suggested that setup-wizard logic used the
    model-choice type directly.
- Repair:
  - confirmed through AST analysis that `ModelChoice` had no loads;
  - removed only the unused import;
  - preserved all other model-catalog imports and setup-wizard behavior.
- Regression coverage:
  `tests/test_setup_wizard_unused_model_choice_cleanup.py`.

### Verified repair — unused V16 doer Path import

- File: `src/sophyane/v16_doer.py`
- Root cause: `Path` was imported from `pathlib` but had no runtime or
  annotation references.
- Impact:
  - Pyflakes reported a dead import;
  - the dependency misleadingly suggested direct filesystem-path handling in
    the V16 doer.
- Repair:
  - confirmed through AST analysis that `Path` had no loads;
  - removed only the unused import;
  - preserved V16 doer behavior and entry points.
- Regression coverage:
  `tests/test_v16_doer_unused_path_cleanup.py`.

### Verified repair — unused auto-messaging imports

- File: `src/sophyane/cloud/auto_messaging_setup.py`
- Root cause:
  - `MESSAGING_ENV` was imported without runtime use;
  - `send_email` was imported without runtime use;
  - `send_whatsapp` was imported without runtime use.
- Impact:
  - Pyflakes reported three dead imports;
  - the import list overstated which messaging channels and environment
    resources the automatic setup path directly used.
- Repair:
  - confirmed all three names had no runtime loads through AST analysis;
  - removed only the unused imports;
  - preserved Telegram setup and messaging-environment update behavior.
- Regression coverage:
  `tests/test_auto_messaging_setup_unused_imports_cleanup.py`.

### Verified repair — unused product-knowledge imports

- File: `src/sophyane/cloud/product_knowledge.py`
- Root cause:
  - `re` was imported without runtime use;
  - `Any` was imported from `typing` without runtime or annotation use.
- Repair:
  - confirmed both names had no loads through AST analysis;
  - removed only the unused imports;
  - preserved the module's actual top-level product-answer functions.
- Regression coverage:
  `tests/test_product_knowledge_unused_imports_cleanup.py`.

### Verified repair — unused Telegram-bot send_telegram import

- File: `src/sophyane/cloud/telegram_bot.py`
- Root cause: `send_telegram` was imported from the messaging module but had
  no runtime or annotation references.
- Impact:
  - Pyflakes reported a dead import;
  - the import misleadingly suggested that the bot sent messages through the
    generic Telegram messaging helper.
- Repair:
  - confirmed through AST analysis that `send_telegram` had no loads;
  - removed only the unused import;
  - preserved email, WhatsApp, and messaging-environment integrations.
- Regression coverage:
  `tests/test_telegram_bot_unused_send_telegram_cleanup.py`.

### Verified repair — unused competitive-auth imports

- File: `src/sophyane/competitive/auth.py`
- Root cause:
  - `Any` was imported from `typing` without runtime or annotation use;
  - `URLError` and `HTTPError` were imported from `urllib.error` without
    runtime use.
- Impact:
  - Pyflakes reported three dead imports;
  - the imports overstated the module's generic typing and explicit urllib
    exception handling.
- Repair:
  - confirmed all three names had no loads through AST analysis;
  - removed only the unused imports;
  - preserved competitive authentication behavior and entry points.
- Regression coverage:
  `tests/test_competitive_auth_unused_imports_cleanup.py`.

### Verified repair — unused competitive-payments hashlib import

- File: `src/sophyane/competitive/payments.py`
- Root cause: `hashlib` was imported but had no runtime or annotation
  references.
- Impact:
  - Pyflakes reported a dead import;
  - the dependency misleadingly suggested that payment records or requests
    were hashed directly in this module.
- Repair:
  - confirmed through AST analysis that `hashlib` had no loads;
  - removed only the unused import;
  - preserved competitive payment behavior and entry points.
- Regression coverage:
  `tests/test_competitive_payments_unused_hashlib_cleanup.py`.

### Verified repair — ineffective LC compatibility Gemini probe

- File: `src/sophyane/lc_compat/llm.py`
- Function: `from_sophyane_config()`
- Root cause:
  - the function imported `GeminiProvider` inside a `try` block;
  - the imported class was never instantiated or added to `chain`;
  - both successful and failed imports produced the same empty provider chain.
- Impact:
  - Pyflakes reported an unused import;
  - the function misleadingly appeared to integrate the configured Gemini
    provider when it did not;
  - import-time failures were silently swallowed without changing behavior.
- Repair:
  - removed the ineffective availability probe;
  - made the current empty-chain behavior explicit;
  - preserved `MultiProviderLLM` generation and fallback behavior.
- Regression coverage:
  `tests/test_lc_compat_llm_empty_provider_probe_cleanup.py`.

### Verified repair — unused LC compatibility memory Any import

- File: `src/sophyane/lc_compat/memory.py`
- Root cause: `Any` was imported from `typing` but had no runtime or
  annotation references.
- Impact:
  - Pyflakes reported a dead import;
  - the import overstated the module's reliance on unstructured typing.
- Repair:
  - confirmed through AST analysis that `Any` had no loads;
  - removed only the unused import;
  - preserved LC compatibility memory behavior and entry points.
- Regression coverage:
  `tests/test_lc_compat_memory_unused_any_cleanup.py`.

### Verified repair — unused LC compatibility streaming field import

- File: `src/sophyane/lc_compat/streaming.py`
- Root cause: `field` was imported from `dataclasses` but had no runtime or
  annotation references.
- Impact:
  - Pyflakes reported a dead import;
  - the import misleadingly suggested that streaming dataclasses used custom
    factories, defaults, or metadata.
- Repair:
  - confirmed through AST analysis that `field` had no loads;
  - removed only the unused import;
  - preserved all other dataclass imports and streaming behavior.
- Regression coverage:
  `tests/test_lc_compat_streaming_unused_field_cleanup.py`.

### Verified repair — unused mesh-core federation imports

- File: `src/sophyane/mesh/core.py`
- Root cause:
  - `remote_capabilities` was imported without runtime use;
  - `remote_exec_safe` was imported without runtime use.
- Inspection:
  - both imports were module-level;
  - neither symbol had runtime loads;
  - the federation module was already imported for several actively used
    helpers, so these names were not needed for side effects.
- Repair:
  - removed only the two unused helper imports;
  - preserved peer selection, remote chat, storage, and share-stat helpers.
- Regression coverage:
  `tests/test_mesh_core_unused_federation_imports_cleanup.py`.

### Verified batch repair — five remaining production imports

The following confirmed dead imports were removed in one transaction:

- `src/sophyane/mesh/discovery.py`
  - removed unused `struct`;
- `src/sophyane/mesh/install_peer.py`
  - removed unused `shlex`;
- `src/sophyane/providers/fallback.py`
  - removed unused `pathlib.Path`;
- `src/sophyane/providers/openai_compatible.py`
  - removed unused `ProviderMetadata`;
- `src/sophyane/self_improve/ledger.py`
  - removed unused `os`.

Verification:

- each target had exactly one matching import and no runtime loads;
- every edited module compiled successfully;
- consolidated related tests passed;
- Pyflakes passed across all five edited modules;
- the complete repository suite passed with 527 tests;
- no in-scope production Pyflakes findings remain.

Regression coverage:
`tests/test_batch_unused_imports_cleanup.py`.

### Verified batch repair — test-only unused imports

Seven confirmed dead imports were removed from six test modules:

- `test_browser_partial_recovery.py`: `pathlib.Path`;
- `test_future_agent.py`: `list_pending`;
- `test_mesh.py`: `json`;
- `test_new_tab_preview_and_gemini_tool_guard.py`:
  `SimpleNamespace`;
- `test_runtime_root_scan_guard.py`: `tempfile` and `pathlib.Path`;
- `test_state_graph_unittest.py`: `START`.

Verification:

- each target had exactly one import and no loads;
- all affected modules compiled;
- pytest-style functions and unittest-style test classes were preserved;
- all affected tests passed;
- Pyflakes passed across all six edited test modules;
- the complete repository suite passed;
- the repository-wide Pyflakes report was refreshed.

Regression coverage:
`tests/test_batch_test_unused_imports_cleanup.py`.

### Verified final repair — remaining runtime imports

The final two repository-wide Pyflakes findings were removed:

- `src/sophyane/runtime_snake_semantic_repair.py`
  - removed unused `typing.Any`;
- `src/sophyane/runtime_stagnation_patch.py`
  - removed unused `json`.

Verification:

- both imports had exactly one declaration and no loads;
- both modules compiled successfully;
- focused runtime-patch tests passed;
- the complete repository suite passed;
- repository-wide Pyflakes completed with zero findings.

Regression coverage:
`tests/test_final_runtime_unused_imports_cleanup.py`.

### Final repository integrity verification

Following completion of the Pyflakes cleanup:

- the extra blank line at the end of
  `src/sophyane/runtime_sli_brain.py` was removed;
- Git patch integrity passed with no whitespace errors;
- all source and test modules compiled successfully;
- repository-wide Pyflakes completed with zero findings;
- the complete repository test suite passed;
- final evidence was written under
  `reports/audit-evidence/manual/`.

Changed and untracked Python files at verification time:
260.

Total changed and untracked paths at verification time:
355.
