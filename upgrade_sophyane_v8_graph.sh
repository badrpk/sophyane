#!/usr/bin/env bash
set -Eeuo pipefail

BASE="$HOME/.local/share/sophyane-v8"
BIN="$HOME/.local/bin"
STATE="$HOME/.local/state/sophyane-v8"
APP="$BASE/sophyane_graph.py"
LAUNCHER="$BIN/sophyane-graph"
CURRENT="$BIN/sophyane"
LEGACY="$BIN/sophyane-legacy"
STAMP="$(date +%Y%m%d_%H%M%S)"

mkdir -p "$BASE" "$BIN" "$STATE/checkpoints" "$STATE/logs" "$STATE/workspaces"

if [ -e "$CURRENT" ] && [ ! -e "$LEGACY" ]; then
  cp -a "$CURRENT" "$LEGACY"
fi
if [ -e "$CURRENT" ]; then
  cp -a "$CURRENT" "$STATE/sophyane.$STAMP.bak"
fi

cat > "$APP" <<'PY'
#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import signal
import sqlite3
import subprocess
import sys
import tempfile
import time
import traceback
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

VERSION = "8.0.0"
HOME = Path.home()
ROOT = HOME / ".local" / "state" / "sophyane-v8"
DB = ROOT / "graph.sqlite3"
LOG = ROOT / "logs" / "events.jsonl"
CP = ROOT / "checkpoints"
WS = ROOT / "workspaces"
ROOT.mkdir(parents=True, exist_ok=True)
CP.mkdir(parents=True, exist_ok=True)
WS.mkdir(parents=True, exist_ok=True)
LOG.parent.mkdir(parents=True, exist_ok=True)

TERMINAL = {"completed", "failed", "cancelled"}
ALLOWED_TOOLS = {
    "python", "python3", "pytest", "ruff", "mypy", "git", "bash", "sh",
    "make", "cmake", "gcc", "g++", "clang", "clang++", "node", "npm"
}


def now() -> float:
    return time.time()


def emit(event: str, **data: Any) -> None:
    record = {"ts": now(), "event": event, **data}
    with LOG.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def connect() -> sqlite3.Connection:
    db = sqlite3.connect(DB, timeout=30)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("PRAGMA busy_timeout=30000")
    db.executescript("""
    CREATE TABLE IF NOT EXISTS projects(
      id TEXT PRIMARY KEY, name TEXT NOT NULL, workspace TEXT NOT NULL,
      status TEXT NOT NULL, created REAL NOT NULL, updated REAL NOT NULL
    );
    CREATE TABLE IF NOT EXISTS tasks(
      id TEXT PRIMARY KEY, project_id TEXT NOT NULL, title TEXT NOT NULL,
      command TEXT NOT NULL, deps TEXT NOT NULL, status TEXT NOT NULL,
      attempts INTEGER NOT NULL DEFAULT 0, max_attempts INTEGER NOT NULL DEFAULT 3,
      timeout INTEGER NOT NULL DEFAULT 300, verify TEXT NOT NULL DEFAULT '',
      stdout TEXT NOT NULL DEFAULT '', stderr TEXT NOT NULL DEFAULT '',
      exit_code INTEGER, created REAL NOT NULL, updated REAL NOT NULL,
      FOREIGN KEY(project_id) REFERENCES projects(id)
    );
    CREATE TABLE IF NOT EXISTS checkpoints(
      id TEXT PRIMARY KEY, project_id TEXT NOT NULL, path TEXT NOT NULL,
      sha256 TEXT NOT NULL, created REAL NOT NULL
    );
    """)
    return db


def atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=path.name + ".")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data); f.flush(); os.fsync(f.fileno())
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp): os.unlink(tmp)


def validate_command(command: str) -> None:
    first = command.strip().split()[0] if command.strip() else ""
    first = Path(first).name
    if first not in ALLOWED_TOOLS:
        raise ValueError(f"tool '{first}' is not allowed; allowed: {', '.join(sorted(ALLOWED_TOOLS))}")
    forbidden = ["sudo ", "rm -rf /", "mkfs", ":(){", "> /dev/sd", "dd if="]
    if any(x in command for x in forbidden):
        raise ValueError("dangerous command rejected")


def project_row(db: sqlite3.Connection, project_id: str) -> sqlite3.Row:
    row = db.execute("SELECT * FROM projects WHERE id=?", (project_id,)).fetchone()
    if not row: raise SystemExit(f"project not found: {project_id}")
    return row


def task_rows(db: sqlite3.Connection, project_id: str) -> list[sqlite3.Row]:
    return db.execute("SELECT * FROM tasks WHERE project_id=? ORDER BY created", (project_id,)).fetchall()


def detect_cycle(tasks: list[sqlite3.Row]) -> bool:
    graph = {r["id"]: json.loads(r["deps"]) for r in tasks}
    visiting, done = set(), set()
    def visit(n: str) -> bool:
        if n in visiting: return True
        if n in done: return False
        visiting.add(n)
        for d in graph.get(n, []):
            if d in graph and visit(d): return True
        visiting.remove(n); done.add(n); return False
    return any(visit(n) for n in graph)


def cmd_init(args: argparse.Namespace) -> None:
    pid = args.id or "prj_" + uuid.uuid4().hex[:10]
    workspace = Path(args.workspace or (WS / pid)).expanduser().resolve()
    workspace.mkdir(parents=True, exist_ok=True)
    with connect() as db:
        db.execute("INSERT INTO projects VALUES(?,?,?,?,?,?)", (pid,args.name,str(workspace),"ready",now(),now()))
    emit("PROJECT_CREATED", project_id=pid, workspace=str(workspace))
    print(pid)


def cmd_add(args: argparse.Namespace) -> None:
    validate_command(args.command)
    tid = args.id or "tsk_" + uuid.uuid4().hex[:10]
    deps = [x for x in (args.deps or "").split(",") if x]
    with connect() as db:
        project_row(db, args.project)
        known = {r[0] for r in db.execute("SELECT id FROM tasks WHERE project_id=?", (args.project,))}
        missing = [d for d in deps if d not in known]
        if missing: raise SystemExit("missing dependencies: " + ", ".join(missing))
        db.execute("INSERT INTO tasks VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                   (tid,args.project,args.title,args.command,json.dumps(deps),"pending",0,args.retries,args.timeout,
                    args.verify or "","","",None,now(),now()))
        rows = task_rows(db, args.project)
        if detect_cycle(rows):
            db.execute("DELETE FROM tasks WHERE id=?", (tid,))
            raise SystemExit("circular dependency rejected")
    emit("TASK_ADDED", project_id=args.project, task_id=tid, deps=deps)
    print(tid)


def deps_complete(db: sqlite3.Connection, row: sqlite3.Row) -> bool:
    deps = json.loads(row["deps"])
    if not deps: return True
    marks = ",".join("?" for _ in deps)
    statuses = db.execute(f"SELECT status FROM tasks WHERE id IN ({marks})", deps).fetchall()
    return len(statuses) == len(deps) and all(x[0] == "completed" for x in statuses)


def run_command(command: str, cwd: Path, timeout: int) -> tuple[int,str,str,float]:
    started = time.perf_counter()
    proc = subprocess.run(["bash","-lc",command], cwd=cwd, text=True, capture_output=True, timeout=timeout)
    return proc.returncode, proc.stdout, proc.stderr, (time.perf_counter()-started)*1000


def verify_workspace(cwd: Path, custom: str) -> tuple[bool,list[dict[str,Any]]]:
    checks: list[str] = []
    if custom: checks.append(custom)
    if any(cwd.rglob("*.py")):
        checks.append("python3 -m compileall -q .")
        if (cwd/"tests").exists() and shutil.which("pytest"): checks.append("pytest -q")
        if shutil.which("ruff"): checks.append("ruff check .")
        if shutil.which("mypy") and ((cwd/"pyproject.toml").exists() or (cwd/"mypy.ini").exists()): checks.append("mypy .")
    results=[]
    for c in checks:
        try:
            code,out,err,ms=run_command(c,cwd,300)
        except Exception as exc:
            code,out,err,ms=1,"",str(exc),0
        results.append({"command":c,"code":code,"stdout":out[-4000:],"stderr":err[-4000:],"latency_ms":round(ms,1)})
        if code != 0: return False, results
    return True, results


def checkpoint(project_id: str, reason: str) -> Path:
    with connect() as db:
        project = dict(project_row(db, project_id))
        tasks = [dict(r) for r in task_rows(db, project_id)]
    payload = json.dumps({"version":VERSION,"reason":reason,"project":project,"tasks":tasks}, indent=2).encode()
    digest = hashlib.sha256(payload).hexdigest()
    path = CP / f"{project_id}_{int(now())}_{digest[:8]}.json"
    atomic_write(path,payload)
    with connect() as db:
        db.execute("INSERT INTO checkpoints VALUES(?,?,?,?,?)", (uuid.uuid4().hex,project_id,str(path),digest,now()))
    emit("CHECKPOINT_CREATED", project_id=project_id, path=str(path), sha256=digest)
    return path


def cmd_run(args: argparse.Namespace) -> None:
    stop = False
    def sig(*_: Any) -> None:
        nonlocal stop; stop = True
    signal.signal(signal.SIGINT, sig); signal.signal(signal.SIGTERM, sig)
    with connect() as db:
        p = project_row(db,args.project); cwd=Path(p["workspace"])
        db.execute("UPDATE projects SET status='running',updated=? WHERE id=?",(now(),args.project))
    checkpoint(args.project,"before-run")
    while not stop:
        with connect() as db:
            rows=task_rows(db,args.project)
            pending=[r for r in rows if r["status"] in {"pending","retry"} and deps_complete(db,r)]
            unfinished=[r for r in rows if r["status"] not in TERMINAL]
            if not unfinished: break
            if not pending:
                blocked=[r["id"] for r in unfinished]
                print("blocked:",", ".join(blocked)); break
            row=pending[0]
            db.execute("UPDATE tasks SET status='running',attempts=attempts+1,updated=? WHERE id=?",(now(),row["id"]))
        emit("TASK_STARTED",project_id=args.project,task_id=row["id"],attempt=row["attempts"]+1)
        try:
            code,out,err,ms=run_command(row["command"],cwd,row["timeout"])
        except subprocess.TimeoutExpired as exc:
            code,out,err,ms=124,exc.stdout or "",f"timeout after {row['timeout']}s",row["timeout"]*1000
        ok = code == 0
        verification=[]
        if ok:
            ok,verification=verify_workspace(cwd,row["verify"])
            if not ok: err += "\nverification failed\n" + json.dumps(verification,indent=2)
        with connect() as db:
            current=db.execute("SELECT attempts,max_attempts FROM tasks WHERE id=?",(row["id"],)).fetchone()
            status="completed" if ok else ("retry" if current[0] < current[1] else "failed")
            db.execute("UPDATE tasks SET status=?,stdout=?,stderr=?,exit_code=?,updated=? WHERE id=?",
                       (status,out[-20000:],err[-20000:],code,now(),row["id"]))
        emit("TASK_FINISHED",project_id=args.project,task_id=row["id"],status=status,exit_code=code,latency_ms=round(ms,1),verification=verification)
        print(f"{row['id']}: {status} ({ms:.1f} ms)")
        if status=="completed": checkpoint(args.project,f"after-{row['id']}")
        elif status=="retry": time.sleep(min(2 ** current[0],30))
    with connect() as db:
        rows=task_rows(db,args.project)
        final="completed" if rows and all(r["status"]=="completed" for r in rows) else ("paused" if stop else "needs_attention")
        db.execute("UPDATE projects SET status=?,updated=? WHERE id=?",(final,now(),args.project))
    checkpoint(args.project,"run-end")
    print("project:",final)


def cmd_status(args: argparse.Namespace) -> None:
    with connect() as db:
        p=project_row(db,args.project); rows=task_rows(db,args.project)
    print(f"{p['id']}  {p['name']}  status={p['status']}  workspace={p['workspace']}")
    for r in rows:
        deps=','.join(json.loads(r['deps'])) or '-'
        print(f"{r['id']:14} {r['status']:15} attempts={r['attempts']}/{r['max_attempts']} deps={deps}  {r['title']}")


def cmd_resume(args: argparse.Namespace) -> None:
    with connect() as db:
        db.execute("UPDATE tasks SET status='retry',updated=? WHERE project_id=? AND status='running'",(now(),args.project))
        db.execute("UPDATE projects SET status='ready',updated=? WHERE id=?",(now(),args.project))
    emit("PROJECT_RESUMED",project_id=args.project)
    cmd_run(args)


def cmd_restore(args: argparse.Namespace) -> None:
    path=Path(args.file)
    raw=path.read_bytes(); data=json.loads(raw)
    digest=hashlib.sha256(raw).hexdigest()
    with connect() as db:
        known=db.execute("SELECT sha256 FROM checkpoints WHERE path=?",(str(path),)).fetchone()
        if known and known[0]!=digest: raise SystemExit("checkpoint checksum mismatch")
        p=data["project"]
        db.execute("INSERT OR REPLACE INTO projects VALUES(?,?,?,?,?,?)",tuple(p[k] for k in ["id","name","workspace","status","created","updated"]))
        db.execute("DELETE FROM tasks WHERE project_id=?",(p["id"],))
        for t in data["tasks"]:
            cols=["id","project_id","title","command","deps","status","attempts","max_attempts","timeout","verify","stdout","stderr","exit_code","created","updated"]
            db.execute("INSERT INTO tasks VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",tuple(t[c] for c in cols))
    emit("CHECKPOINT_RESTORED",project_id=data["project"]["id"],path=str(path))
    print(data["project"]["id"])


def cmd_events(args: argparse.Namespace) -> None:
    if not LOG.exists(): return
    lines=LOG.read_text(encoding="utf-8").splitlines()[-args.tail:]
    for line in lines: print(line)


def cmd_selftest(_: argparse.Namespace) -> None:
    tmp=Path(tempfile.mkdtemp(prefix="sophyane-v8-test-"))
    try:
        pid="prj_test_"+uuid.uuid4().hex[:6]
        cmd_init(argparse.Namespace(id=pid,name="selftest",workspace=str(tmp)))
        a="tsk_a_"+uuid.uuid4().hex[:5]; b="tsk_b_"+uuid.uuid4().hex[:5]
        cmd_add(argparse.Namespace(project=pid,id=a,title="write",command="bash -lc 'echo ok > result.txt'",deps="",retries=2,timeout=30,verify="test -s result.txt"))
        cmd_add(argparse.Namespace(project=pid,id=b,title="check",command="bash -lc 'grep -q ok result.txt'",deps=a,retries=2,timeout=30,verify=""))
        cmd_run(argparse.Namespace(project=pid))
        with connect() as db:
            rows=task_rows(db,pid)
            assert all(r["status"]=="completed" for r in rows)
        print("SELF-TEST PASSED")
    finally:
        shutil.rmtree(tmp,ignore_errors=True)


def parser() -> argparse.ArgumentParser:
    p=argparse.ArgumentParser(prog="sophyane-graph",description="Sophyane v8 durable graph executor")
    p.add_argument("--version",action="version",version=VERSION)
    s=p.add_subparsers(dest="cmd",required=True)
    x=s.add_parser("init"); x.add_argument("name"); x.add_argument("--id"); x.add_argument("--workspace"); x.set_defaults(func=cmd_init)
    x=s.add_parser("add"); x.add_argument("project"); x.add_argument("title"); x.add_argument("command"); x.add_argument("--id"); x.add_argument("--deps",default=""); x.add_argument("--retries",type=int,default=3); x.add_argument("--timeout",type=int,default=300); x.add_argument("--verify",default=""); x.set_defaults(func=cmd_add)
    for name,func in [("run",cmd_run),("resume",cmd_resume),("status",cmd_status)]:
        x=s.add_parser(name); x.add_argument("project"); x.set_defaults(func=func)
    x=s.add_parser("restore"); x.add_argument("file"); x.set_defaults(func=cmd_restore)
    x=s.add_parser("events"); x.add_argument("--tail",type=int,default=50); x.set_defaults(func=cmd_events)
    x=s.add_parser("self-test"); x.set_defaults(func=cmd_selftest)
    return p


def main() -> None:
    args=parser().parse_args(); args.func(args)

if __name__ == "__main__": main()
PY

chmod +x "$APP"
cat > "$LAUNCHER" <<EOF
#!/usr/bin/env bash
exec python3 "$APP" "\$@"
EOF
chmod +x "$LAUNCHER"

# Add a non-destructive dispatcher: normal Sophyane stays legacy; graph commands use v8.
cat > "$CURRENT.new" <<'EOF'
#!/usr/bin/env bash
set -e
if [ "${1:-}" = "graph" ]; then
  shift
  exec "$HOME/.local/bin/sophyane-graph" "$@"
fi
if [ -x "$HOME/.local/bin/sophyane-legacy" ]; then
  exec "$HOME/.local/bin/sophyane-legacy" "$@"
fi
echo "Sophyane legacy launcher not found. Use: sophyane graph --help" >&2
exit 1
EOF
chmod +x "$CURRENT.new"

python3 -m py_compile "$APP"
"$LAUNCHER" self-test
mv "$CURRENT.new" "$CURRENT"

case ":$PATH:" in
  *":$BIN:"*) ;;
  *) echo 'export PATH="$HOME/.local/bin:$PATH"' >> "$HOME/.bashrc" ;;
esac

cat <<'TXT'

✅ Sophyane v8 graph layer installed.

Normal Sophyane:
  sophyane

Durable graph engine:
  sophyane graph --help
  sophyane graph self-test

Example:
  P=$(sophyane graph init demo --workspace "$HOME/sophyane-demo")
  A=$(sophyane graph add "$P" "Create app" "bash -lc 'printf \"print(42)\\n\" > app.py'" --verify "python3 app.py")
  sophyane graph add "$P" "Compile" "python3 -m py_compile app.py" --deps "$A"
  sophyane graph run "$P"
  sophyane graph status "$P"

This adds capabilities that bare LangGraph does not provide automatically:
- SQLite-persisted DAG state
- interruption-safe resume
- automatic checkpoints with checksums
- dependency enforcement and cycle rejection
- command sandbox/allowlist
- retries and exponential backoff
- compile/test/lint verification loop
- auditable JSONL event history

Note: this is an engineering upgrade, not a guarantee of outperforming every LangGraph application.
TXT
