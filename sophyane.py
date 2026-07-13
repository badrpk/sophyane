#!/usr/bin/env python3
from __future__ import annotations
import argparse, hashlib, json, os, shutil, signal, sqlite3, subprocess, sys, tempfile, threading, time, urllib.request, uuid, webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

VERSION = "8.0.0"
REPO_RAW = "https://raw.githubusercontent.com/badrpk/sophyane/main"
HOME = Path.home()
ROOT = HOME / ".local" / "state" / "sophyane"
DB = ROOT / "sophyane.sqlite3"
LOG = ROOT / "events.jsonl"
WORKSPACES = ROOT / "workspaces"
CHECKPOINTS = ROOT / "checkpoints"
CONFIG = HOME / ".config" / "sophyane" / "v8.json"
APP_PATH = HOME / ".local" / "share" / "sophyane-v8" / "sophyane.py"
LEGACY = HOME / ".local" / "bin" / "sophyane-6.1"
ALLOWED = {"python","python3","pytest","ruff","mypy","git","bash","sh","make","cmake","gcc","g++","clang","clang++","node","npm"}
TERMINAL = {"completed","failed","cancelled"}
for p in (ROOT, WORKSPACES, CHECKPOINTS, CONFIG.parent, APP_PATH.parent): p.mkdir(parents=True, exist_ok=True)

def now() -> float: return time.time()
def emit(event: str, **data: Any) -> None:
    rec={"ts":now(),"event":event,**data}
    with LOG.open("a",encoding="utf-8") as f: f.write(json.dumps(rec,ensure_ascii=False)+"\n")

def db() -> sqlite3.Connection:
    c=sqlite3.connect(DB,timeout=30); c.row_factory=sqlite3.Row
    c.execute("PRAGMA journal_mode=WAL"); c.execute("PRAGMA busy_timeout=30000")
    c.executescript('''
    CREATE TABLE IF NOT EXISTS projects(id TEXT PRIMARY KEY,name TEXT,workspace TEXT,status TEXT,created REAL,updated REAL);
    CREATE TABLE IF NOT EXISTS tasks(id TEXT PRIMARY KEY,project_id TEXT,title TEXT,command TEXT,deps TEXT,status TEXT,attempts INTEGER,max_attempts INTEGER,timeout INTEGER,verify TEXT,stdout TEXT,stderr TEXT,exit_code INTEGER,latency_ms REAL,created REAL,updated REAL);
    CREATE TABLE IF NOT EXISTS checkpoints(id TEXT PRIMARY KEY,project_id TEXT,path TEXT,sha256 TEXT,created REAL);
    CREATE TABLE IF NOT EXISTS provider_metrics(provider TEXT PRIMARY KEY,calls INTEGER DEFAULT 0,successes INTEGER DEFAULT 0,failures INTEGER DEFAULT 0,total_latency_ms REAL DEFAULT 0,updated REAL);
    ''')
    return c

def validate(command:str)->None:
    first=Path(command.strip().split()[0]).name if command.strip() else ""
    if first not in ALLOWED: raise ValueError(f"tool '{first}' not allowed")
    if any(x in command for x in ("sudo ","rm -rf /","mkfs",":(){","> /dev/sd","dd if=")): raise ValueError("dangerous command rejected")

def project(pid:str)->sqlite3.Row:
    with db() as c: r=c.execute("SELECT * FROM projects WHERE id=?",(pid,)).fetchone()
    if not r: raise SystemExit(f"project not found: {pid}")
    return r

def tasks(pid:str)->list[sqlite3.Row]:
    with db() as c: return c.execute("SELECT * FROM tasks WHERE project_id=? ORDER BY created",(pid,)).fetchall()

def cycle(rows:list[sqlite3.Row])->bool:
    g={r['id']:json.loads(r['deps']) for r in rows}; visiting=set(); done=set()
    def visit(n:str)->bool:
        if n in visiting:return True
        if n in done:return False
        visiting.add(n)
        for d in g.get(n,[]):
            if d in g and visit(d):return True
        visiting.remove(n);done.add(n);return False
    return any(visit(n) for n in g)

def new_project(name:str,workspace:str|None=None)->str:
    pid='prj_'+uuid.uuid4().hex[:10]; w=Path(workspace or WORKSPACES/pid).expanduser().resolve();w.mkdir(parents=True,exist_ok=True)
    with db() as c:c.execute("INSERT INTO projects VALUES(?,?,?,?,?,?)",(pid,name,str(w),'ready',now(),now()))
    emit('PROJECT_CREATED',project_id=pid,name=name,workspace=str(w));return pid

def add_task(pid:str,title:str,command:str,deps:list[str]|None=None,retries:int=3,timeout:int=300,verify:str='')->str:
    validate(command); project(pid); deps=deps or []; tid='tsk_'+uuid.uuid4().hex[:10]
    with db() as c:
        known={r[0] for r in c.execute("SELECT id FROM tasks WHERE project_id=?",(pid,))}
        missing=[d for d in deps if d not in known]
        if missing:raise SystemExit('missing dependencies: '+','.join(missing))
        c.execute("INSERT INTO tasks VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",(tid,pid,title,command,json.dumps(deps),'pending',0,retries,timeout,verify,'','',None,0.0,now(),now()))
        rows=c.execute("SELECT * FROM tasks WHERE project_id=?",(pid,)).fetchall()
        if cycle(rows):c.execute("DELETE FROM tasks WHERE id=?",(tid,));raise SystemExit('circular dependency rejected')
    emit('TASK_ADDED',project_id=pid,task_id=tid,title=title,deps=deps);return tid

def deps_done(c:sqlite3.Connection,r:sqlite3.Row)->bool:
    ds=json.loads(r['deps'])
    if not ds:return True
    marks=','.join('?' for _ in ds); ss=c.execute(f"SELECT status FROM tasks WHERE id IN ({marks})",ds).fetchall()
    return len(ss)==len(ds) and all(x[0]=='completed' for x in ss)

def run_cmd(command:str,cwd:Path,timeout:int)->tuple[int,str,str,float]:
    t=time.perf_counter(); p=subprocess.run(['bash','-lc',command],cwd=cwd,text=True,capture_output=True,timeout=timeout)
    return p.returncode,p.stdout,p.stderr,(time.perf_counter()-t)*1000

def verify(cwd:Path,custom:str)->tuple[bool,list[dict[str,Any]]]:
    checks=[]
    if custom:checks.append(custom)
    if any(cwd.rglob('*.py')):
        checks.append('python3 -m compileall -q .')
        py=cwd/'.venv/bin/python'
        if (cwd/'tests').exists():
            if py.exists():checks.append('.venv/bin/python -m pytest -q')
            elif shutil.which('pytest'):checks.append('pytest -q')
        if shutil.which('ruff'):checks.append('ruff check .')
    out=[]
    for cmd in checks:
        try:code,so,se,ms=run_cmd(cmd,cwd,300)
        except Exception as e:code,so,se,ms=1,'',str(e),0
        out.append({'command':cmd,'code':code,'stdout':so[-4000:],'stderr':se[-4000:],'latency_ms':round(ms,1)})
        if code:return False,out
    return True,out

def checkpoint(pid:str,reason:str)->Path:
    payload=json.dumps({'version':VERSION,'reason':reason,'project':dict(project(pid)),'tasks':[dict(x) for x in tasks(pid)]},indent=2).encode();sha=hashlib.sha256(payload).hexdigest();path=CHECKPOINTS/f'{pid}_{int(now())}_{sha[:8]}.json'
    fd,tmp=tempfile.mkstemp(dir=CHECKPOINTS);os.write(fd,payload);os.fsync(fd);os.close(fd);os.replace(tmp,path)
    with db() as c:c.execute("INSERT INTO checkpoints VALUES(?,?,?,?,?)",(uuid.uuid4().hex,pid,str(path),sha,now()))
    emit('CHECKPOINT_CREATED',project_id=pid,path=str(path),reason=reason);return path

def run_project(pid:str)->str:
    p=project(pid);cwd=Path(p['workspace']);stop=False
    def sig(*_:Any)->None:nonlocal stop;stop=True
    old1=signal.signal(signal.SIGINT,sig);old2=signal.signal(signal.SIGTERM,sig)
    with db() as c:c.execute("UPDATE projects SET status='running',updated=? WHERE id=?",(now(),pid))
    checkpoint(pid,'before-run')
    try:
        while not stop:
            with db() as c:
                rows=c.execute("SELECT * FROM tasks WHERE project_id=? ORDER BY created",(pid,)).fetchall();unfinished=[r for r in rows if r['status'] not in TERMINAL];ready=[r for r in rows if r['status'] in {'pending','retry','running'} and deps_done(c,r)]
                if not unfinished:break
                if not ready:break
                r=ready[0];c.execute("UPDATE tasks SET status='running',attempts=attempts+1,updated=? WHERE id=?",(now(),r['id']))
            emit('TASK_STARTED',project_id=pid,task_id=r['id'])
            try:code,so,se,ms=run_cmd(r['command'],cwd,r['timeout'])
            except subprocess.TimeoutExpired as e:code,so,se,ms=124,e.stdout or '',f'timeout after {r["timeout"]}s',r['timeout']*1000
            ok=code==0;checks=[]
            if ok:ok,checks=verify(cwd,r['verify'])
            with db() as c:
                cur=c.execute("SELECT attempts,max_attempts FROM tasks WHERE id=?",(r['id'],)).fetchone();status='completed' if ok else ('retry' if cur[0]<cur[1] else 'failed')
                if not ok and checks:se+='\nverification failed\n'+json.dumps(checks,indent=2)
                c.execute("UPDATE tasks SET status=?,stdout=?,stderr=?,exit_code=?,latency_ms=?,updated=? WHERE id=?",(status,so[-20000:],se[-20000:],code,ms,now(),r['id']))
            emit('TASK_FINISHED',project_id=pid,task_id=r['id'],status=status,latency_ms=round(ms,1),verification=checks);print(f"{r['id']}: {status} ({ms:.1f} ms)")
            if status=='completed':checkpoint(pid,'after-'+r['id'])
            elif status=='retry':time.sleep(min(2**cur[0],30))
        rows=tasks(pid);final='completed' if rows and all(r['status']=='completed' for r in rows) else ('paused' if stop else 'needs_attention')
        with db() as c:c.execute("UPDATE projects SET status=?,updated=? WHERE id=?",(final,now(),pid))
        checkpoint(pid,'run-end');print('project:',final);return final
    finally:signal.signal(signal.SIGINT,old1);signal.signal(signal.SIGTERM,old2)

def state()->dict[str,Any]:
    with db() as c:
        ps=[dict(x) for x in c.execute("SELECT * FROM projects ORDER BY updated DESC LIMIT 50")];ts=[dict(x) for x in c.execute("SELECT * FROM tasks ORDER BY updated DESC LIMIT 500")];pm=[dict(x) for x in c.execute("SELECT * FROM provider_metrics")]
    counts={k:sum(1 for x in ts if x['status']==k) for k in ('pending','running','retry','completed','failed')}
    return {'version':VERSION,'projects':ps,'tasks':ts,'task_counts':counts,'providers':pm,'updated':now()}

DASH='''<!doctype html><html><head><meta charset="utf-8"><title>Sophyane v8</title><style>body{font-family:system-ui;background:#0b1020;color:#e8edf7;margin:0}header{padding:22px;background:#111a33;display:flex;justify-content:space-between}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));gap:16px;padding:18px}.card{background:#141d36;border:1px solid #263253;border-radius:16px;padding:16px}table{width:100%;border-collapse:collapse}td,th{padding:8px;border-bottom:1px solid #263253;text-align:left}.ok{color:#66e3a4}.bad{color:#ff7d8d}svg{width:100%;height:220px}.bar{fill:#6ea8fe}.line{fill:none;stroke:#66e3a4;stroke-width:3}.muted{color:#9eabc8}button{background:#6ea8fe;border:0;border-radius:8px;padding:8px 12px}</style></head><body><header><div><b>Sophyane v8</b><div class="muted">Unified AI + durable graph runtime</div></div><button onclick="load()">Refresh</button></header><div class="grid"><div class="card"><h3>Task status</h3><svg id="bars"></svg></div><div class="card"><h3>Latency comparison</h3><svg id="line"></svg></div><div class="card" style="grid-column:1/-1"><h3>Projects</h3><table><thead><tr><th>Name</th><th>Status</th><th>Workspace</th><th>Updated</th></tr></thead><tbody id="projects"></tbody></table></div><div class="card" style="grid-column:1/-1"><h3>Recent tasks</h3><table><thead><tr><th>Task</th><th>Status</th><th>Attempts</th><th>Latency</th></tr></thead><tbody id="tasks"></tbody></table></div></div><script>
function esc(s){return String(s??'').replace(/[&<>]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;'}[c]))}function bars(c){let k=Object.keys(c),m=Math.max(1,...Object.values(c)),w=600,h=200;barsEl=document.getElementById('bars');barsEl.setAttribute('viewBox',`0 0 ${w} ${h}`);barsEl.innerHTML=k.map((x,i)=>{let bh=c[x]/m*140,xx=20+i*110;return `<rect class="bar" x="${xx}" y="${160-bh}" width="70" height="${bh}" rx="6"/><text fill="#e8edf7" x="${xx}" y="180">${x}</text><text fill="#e8edf7" x="${xx+25}" y="${150-bh}">${c[x]}</text>`}).join('')}
function line(ts){let a=ts.filter(x=>x.latency_ms>0).slice(0,30).reverse(),m=Math.max(1,...a.map(x=>x.latency_ms)),w=600,h=200,pts=a.map((x,i)=>`${20+i*(560/Math.max(1,a.length-1))},${170-x.latency_ms/m*140}`).join(' ');let e=document.getElementById('line');e.setAttribute('viewBox',`0 0 ${w} ${h}`);e.innerHTML=`<polyline class="line" points="${pts}"/><text x="20" y="195" fill="#9eabc8">Recent task latency (ms), max ${m.toFixed(0)}</text>`}
async function load(){let d=await fetch('/api/state').then(r=>r.json());bars(d.task_counts);line(d.tasks);projects.innerHTML=d.projects.map(x=>`<tr><td>${esc(x.name)}</td><td class="${x.status==='completed'?'ok':'bad'}">${esc(x.status)}</td><td>${esc(x.workspace)}</td><td>${new Date(x.updated*1000).toLocaleString()}</td></tr>`).join('');tasks.innerHTML=d.tasks.slice(0,40).map(x=>`<tr><td>${esc(x.title)}</td><td>${esc(x.status)}</td><td>${x.attempts}/${x.max_attempts}</td><td>${Number(x.latency_ms||0).toFixed(1)} ms</td></tr>`).join('')}load();setInterval(load,3000)</script></body></html>'''

class Handler(BaseHTTPRequestHandler):
    def log_message(self,*_:Any)->None:pass
    def send(self,code:int,body:bytes,ctype:str)->None:self.send_response(code);self.send_header('Content-Type',ctype);self.send_header('Cache-Control','no-store');self.end_headers();self.wfile.write(body)
    def do_GET(self)->None:
        if self.path=='/' or self.path.startswith('/?'):self.send(200,DASH.encode(),'text/html; charset=utf-8')
        elif self.path=='/api/state':self.send(200,json.dumps(state()).encode(),'application/json')
        elif self.path=='/api/events':self.send(200,(LOG.read_bytes() if LOG.exists() else b''),'application/x-ndjson')
        else:self.send(404,b'not found','text/plain')

def serve(host:str,port:int,open_browser:bool)->None:
    srv=ThreadingHTTPServer((host,port),Handler);url=f'http://{host}:{port}/';print('Sophyane dashboard:',url)
    if open_browser:threading.Timer(.7,lambda:webbrowser.open(url)).start()
    try:srv.serve_forever()
    except KeyboardInterrupt:pass
    finally:srv.server_close()

def config()->dict[str,Any]:
    try:return json.loads(CONFIG.read_text())
    except Exception:return {'auto_update':True,'last_update_check':0}

def save_config(c:dict[str,Any])->None:CONFIG.write_text(json.dumps(c,indent=2))
def ver_tuple(v:str)->tuple[int,...]:return tuple(int(x) for x in v.strip().split('.') if x.isdigit())

def update_check(force:bool=False)->bool:
    c=config();interval=3600
    if not force and (not c.get('auto_update',True) or now()-float(c.get('last_update_check',0))<interval):return False
    c['last_update_check']=now();save_config(c)
    try:
        manifest=json.loads(urllib.request.urlopen(REPO_RAW+'/manifest.json',timeout=4).read())
        remote=manifest['version']
        if ver_tuple(remote)<=ver_tuple(VERSION):return False
        data=urllib.request.urlopen(REPO_RAW+'/'+manifest['entrypoint'],timeout=10).read()
        if hashlib.sha256(data).hexdigest()!=manifest['sha256']:raise RuntimeError('update checksum mismatch')
        fd,tmp=tempfile.mkstemp(dir=APP_PATH.parent);os.write(fd,data);os.fsync(fd);os.close(fd);os.chmod(tmp,0o755);os.replace(tmp,APP_PATH)
        emit('AUTO_UPDATED',from_version=VERSION,to_version=remote);print(f'Updated Sophyane {VERSION} -> {remote}. Restarting...')
        os.execv(sys.executable,[sys.executable,str(APP_PATH),*sys.argv[1:]])
    except Exception as e:
        if force:print('Update check failed:',e,file=sys.stderr)
    return False

def legacy_prompt(text:str)->int:
    if LEGACY.exists():return subprocess.call([str(LEGACY),text])
    print('No LLM provider runtime configured. Use graph commands or install/configure a provider.');return 2

def repl()->None:
    print(f'\n🧠 Sophyane {VERSION}\nUnified REPL + durable graph + browser dashboard\nCommands: help, web, projects, status <id>, run <id>, update, exit\n')
    while True:
        try:s=input('sophyane> ').strip()
        except (EOFError,KeyboardInterrupt):print();break
        if not s:continue
        if s in {'exit','quit','/exit'}:break
        if s=='help':print('web | projects | status <project> | run <project> | update | doctor | any other text sends to configured LLM');continue
        if s=='web':threading.Thread(target=serve,args=('127.0.0.1',8765,True),daemon=True).start();continue
        if s=='projects':
            for p in state()['projects']:print(p['id'],p['status'],p['name']);continue
        if s.startswith('status '):show_status(s.split(maxsplit=1)[1]);continue
        if s.startswith('run '):run_project(s.split(maxsplit=1)[1]);continue
        if s=='update':update_check(True);continue
        if s=='doctor':doctor();continue
        legacy_prompt(s)

def show_status(pid:str)->None:
    p=project(pid);print(f"{p['id']} {p['name']} status={p['status']} workspace={p['workspace']}")
    for r in tasks(pid):print(f"{r['id']:14} {r['status']:14} {r['attempts']}/{r['max_attempts']} {r['title']}")

def doctor()->None:
    ok=True
    try:
        with db() as c:c.execute('SELECT 1').fetchone()
    except Exception as e:ok=False;print('DB FAIL',e)
    print('Python:',sys.version.split()[0]);print('Database:',DB);print('Graph engine:','OK' if ok else 'FAIL');print('Browser dashboard: http://127.0.0.1:8765');print('Version:',VERSION)

def selftest()->None:
    tmp=Path(tempfile.mkdtemp(prefix='sophyane-v8-'))
    try:
        pid=new_project('self-test',str(tmp));a=add_task(pid,'write',"bash -lc 'echo ok > result.txt'",verify='test -s result.txt');add_task(pid,'read','bash -lc \'grep -q ok result.txt\'',[a]);assert run_project(pid)=='completed';print('SELF-TEST PASSED')
    finally:shutil.rmtree(tmp,ignore_errors=True)

def parser()->argparse.ArgumentParser:
    p=argparse.ArgumentParser(prog='sophyane',description='Sophyane v8 unified AI and durable graph runtime');p.add_argument('--version',action='version',version=VERSION);s=p.add_subparsers(dest='cmd')
    s.add_parser('repl');w=s.add_parser('web');w.add_argument('--host',default='127.0.0.1');w.add_argument('--port',type=int,default=8765);w.add_argument('--no-open',action='store_true')
    i=s.add_parser('init');i.add_argument('name');i.add_argument('--workspace')
    a=s.add_parser('add');a.add_argument('project');a.add_argument('title');a.add_argument('command');a.add_argument('--deps',default='');a.add_argument('--retries',type=int,default=3);a.add_argument('--timeout',type=int,default=300);a.add_argument('--verify',default='')
    for n in ('run','resume','status'):
        x=s.add_parser(n);x.add_argument('project')
    s.add_parser('projects');s.add_parser('events').add_argument('--tail',type=int,default=50);s.add_parser('update');s.add_parser('doctor');s.add_parser('self-test')
    return p

def main()->None:
    update_check(False);args=parser().parse_args()
    if not args.cmd or args.cmd=='repl':repl()
    elif args.cmd=='web':serve(args.host,args.port,not args.no_open)
    elif args.cmd=='init':print(new_project(args.name,args.workspace))
    elif args.cmd=='add':print(add_task(args.project,args.title,args.command,[x for x in args.deps.split(',') if x],args.retries,args.timeout,args.verify))
    elif args.cmd in {'run','resume'}:
        if args.cmd=='resume':
            with db() as c:c.execute("UPDATE tasks SET status='retry' WHERE project_id=? AND status IN ('running','failed')",(args.project,))
        run_project(args.project)
    elif args.cmd=='status':show_status(args.project)
    elif args.cmd=='projects':
        for p in state()['projects']:print(p['id'],p['status'],p['name'])
    elif args.cmd=='events':
        lines=LOG.read_text().splitlines()[-args.tail:] if LOG.exists() else []
        print('\n'.join(lines))
    elif args.cmd=='update':update_check(True)
    elif args.cmd=='doctor':doctor()
    elif args.cmd=='self-test':selftest()

if __name__=='__main__':main()
