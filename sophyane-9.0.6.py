#!/usr/bin/env python3
from __future__ import annotations
import argparse,hashlib,json,os,shlex,signal,sqlite3,subprocess,sys,tempfile,time,urllib.request,uuid
from pathlib import Path
VERSION='9.0.6';ROOT=Path.home()/'.local/state/sophyane';DB=ROOT/'sophyane.sqlite3';LOG=ROOT/'events.jsonl';CPS=ROOT/'checkpoints';BASE=Path.home()/'.local/share/sophyane';CORE=BASE/'sophyane-core-9.0.5.py';CORE_URL='https://raw.githubusercontent.com/badrpk/sophyane/e55a45db92f8a719f514c21b2cae441db527ff4d/sophyane-9.0.5.py';CORE_BLOB='2cee1f67c69d85fed2f5d473be35a93e8ca5b0c2';TERM={'completed','failed','cancelled'}
for p in (ROOT,CPS,BASE):p.mkdir(parents=True,exist_ok=True)
def blobsha(d):return hashlib.sha1(f'blob {len(d)}\0'.encode()+d).hexdigest()
def core():
 if CORE.exists() and blobsha(CORE.read_bytes())==CORE_BLOB:return CORE
 d=urllib.request.urlopen(CORE_URL,timeout=20).read()
 if blobsha(d)!=CORE_BLOB:raise RuntimeError('core integrity mismatch')
 t=CORE.with_suffix('.tmp');t.write_bytes(d);os.chmod(t,0o755);os.replace(t,CORE);return CORE
def delegate(a):return subprocess.call([sys.executable,str(core()),*a])
def emit(e,**d):
 with LOG.open('a') as f:f.write(json.dumps({'ts':time.time(),'event':e,**d})+'\n')
def conn():
 c=sqlite3.connect(DB,timeout=30);c.row_factory=sqlite3.Row;c.execute('PRAGMA journal_mode=WAL');c.execute('PRAGMA busy_timeout=30000')
 names={r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}
 if 'tasks' in names:
  cols={r[1] for r in c.execute('PRAGMA table_info(tasks)')}
  if not {'attempts','max_attempts','deps','latency_ms'}.issubset(cols):
   stamp=int(time.time());c.execute(f'ALTER TABLE tasks RENAME TO tasks_legacy_{stamp}')
 if 'projects' in names:
  cols={r[1] for r in c.execute('PRAGMA table_info(projects)')}
  if not {'workspace','status','updated'}.issubset(cols):
   stamp=int(time.time());c.execute(f'ALTER TABLE projects RENAME TO projects_legacy_{stamp}')
 c.executescript('''CREATE TABLE IF NOT EXISTS projects(id TEXT PRIMARY KEY,name TEXT,workspace TEXT,status TEXT,created REAL,updated REAL);CREATE TABLE IF NOT EXISTS tasks(id TEXT PRIMARY KEY,project_id TEXT,title TEXT,command TEXT,deps TEXT,status TEXT,attempts INTEGER,max_attempts INTEGER,timeout INTEGER,verify TEXT,stdout TEXT,stderr TEXT,exit_code INTEGER,latency_ms REAL,created REAL,updated REAL);CREATE TABLE IF NOT EXISTS checkpoints(id TEXT PRIMARY KEY,project_id TEXT,path TEXT,sha256 TEXT,created REAL);''');c.commit();return c
def project(pid):
 with conn() as c:r=c.execute('SELECT * FROM projects WHERE id=?',(pid,)).fetchone()
 if not r:raise SystemExit(f'project not found: {pid}')
 return r
def rows(pid):
 with conn() as c:return c.execute('SELECT * FROM tasks WHERE project_id=? ORDER BY created',(pid,)).fetchall()
def new(name,workspace=None):
 pid='prj_'+uuid.uuid4().hex[:10];w=Path(workspace or ROOT/'workspaces'/pid).expanduser().resolve();w.mkdir(parents=True,exist_ok=True);n=time.time()
 with conn() as c:c.execute('INSERT INTO projects VALUES(?,?,?,?,?,?)',(pid,name,str(w),'ready',n,n));c.commit()
 emit('PROJECT_CREATED',project_id=pid);return pid
def cyclic(rs):
 g={r['id']:json.loads(r['deps']) for r in rs};vis=set();done=set()
 def v(n):
  if n in vis:return True
  if n in done:return False
  vis.add(n)
  for d in g.get(n,[]):
   if d in g and v(d):return True
  vis.remove(n);done.add(n);return False
 return any(v(n) for n in g)
def add(pid,title,command,deps,retries,timeout,verify):
 project(pid);tid='tsk_'+uuid.uuid4().hex[:10];n=time.time()
 with conn() as c:
  known={r[0] for r in c.execute('SELECT id FROM tasks WHERE project_id=?',(pid,))};missing=[d for d in deps if d not in known]
  if missing:raise SystemExit('missing dependencies: '+','.join(missing))
  c.execute('INSERT INTO tasks VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',(tid,pid,title,command,json.dumps(deps),'pending',0,retries,timeout,verify,'','',None,0.0,n,n));rs=c.execute('SELECT * FROM tasks WHERE project_id=?',(pid,)).fetchall()
  if cyclic(rs):c.execute('DELETE FROM tasks WHERE id=?',(tid,));raise SystemExit('circular dependency rejected')
  c.commit()
 emit('TASK_ADDED',project_id=pid,task_id=tid);return tid
def checkpoint(pid,reason):
 payload=json.dumps({'project':dict(project(pid)),'tasks':[dict(r) for r in rows(pid)],'reason':reason},indent=2).encode();sha=hashlib.sha256(payload).hexdigest();p=CPS/f'{pid}_{int(time.time())}_{sha[:8]}.json';p.write_bytes(payload)
 with conn() as c:c.execute('INSERT INTO checkpoints VALUES(?,?,?,?,?)',(uuid.uuid4().hex,pid,str(p),sha,time.time()));c.commit()
 emit('CHECKPOINT_CREATED',project_id=pid,path=str(p),reason=reason)
def deps_done(c,r):
 ds=json.loads(r['deps']);
 if not ds:return True
 q=','.join('?' for _ in ds);ss=c.execute(f'SELECT status FROM tasks WHERE id IN ({q})',ds).fetchall();return len(ss)==len(ds) and all(x[0]=='completed' for x in ss)
def run(pid):
 p=project(pid);cwd=Path(p['workspace']);stop=False
 def sig(*_):
  nonlocal stop;stop=True
 old1=signal.signal(signal.SIGINT,sig);old2=signal.signal(signal.SIGTERM,sig)
 with conn() as c:c.execute("UPDATE tasks SET status='retry' WHERE project_id=? AND status='running'",(pid,));c.execute("UPDATE projects SET status='running',updated=? WHERE id=?",(time.time(),pid));c.commit()
 checkpoint(pid,'before-run')
 try:
  while not stop:
   with conn() as c:
    rs=c.execute('SELECT * FROM tasks WHERE project_id=? ORDER BY created',(pid,)).fetchall();unfinished=[r for r in rs if r['status'] not in TERM];ready=[r for r in rs if r['status'] in ('pending','retry','running') and deps_done(c,r)]
    if not unfinished or not ready:break
    r=ready[0];c.execute("UPDATE tasks SET status='running',attempts=attempts+1,updated=? WHERE id=?",(time.time(),r['id']));c.commit()
   emit('TASK_STARTED',project_id=pid,task_id=r['id']);t=time.perf_counter()
   try:q=subprocess.run(['bash','-lc',r['command']],cwd=cwd,text=True,capture_output=True,timeout=r['timeout']);code,so,se=q.returncode,q.stdout,q.stderr
   except subprocess.TimeoutExpired as e:code,so,se=124,e.stdout or '',f'timeout after {r["timeout"]}s'
   ok=code==0
   if ok and r['verify']:
    v=subprocess.run(['bash','-lc',r['verify']],cwd=cwd,text=True,capture_output=True);ok=v.returncode==0
    if not ok:se+='\nverification failed\n'+v.stderr+v.stdout
   ms=(time.perf_counter()-t)*1000
   with conn() as c:
    a,m=c.execute('SELECT attempts,max_attempts FROM tasks WHERE id=?',(r['id'],)).fetchone();st='completed' if ok else ('retry' if a<m else 'failed');c.execute('UPDATE tasks SET status=?,stdout=?,stderr=?,exit_code=?,latency_ms=?,updated=? WHERE id=?',(st,so[-20000:],se[-20000:],code,ms,time.time(),r['id']));c.commit()
   emit('TASK_FINISHED',project_id=pid,task_id=r['id'],status=st,latency_ms=ms);print(f"{r['id']}: {st} ({ms:.1f} ms)")
   if st=='completed':checkpoint(pid,'after-'+r['id'])
   elif st=='retry':time.sleep(min(2**a,8))
  rs=rows(pid);final='completed' if rs and all(r['status']=='completed' for r in rs) else ('paused' if stop else 'needs_attention')
  with conn() as c:c.execute('UPDATE projects SET status=?,updated=? WHERE id=?',(final,time.time(),pid));c.commit()
  checkpoint(pid,'run-end');print('project:',final);return final
 finally:signal.signal(signal.SIGINT,old1);signal.signal(signal.SIGTERM,old2)
def status(pid):
 p=project(pid);print(f"{p['id']} {p['name']} status={p['status']} workspace={p['workspace']}")
 for r in rows(pid):print(f"{r['id']:14} {r['status']:14} attempts={r['attempts']}/{r['max_attempts']} deps={','.join(json.loads(r['deps'])) or '-'}  {r['title']}")
def selftest():
 w=Path(tempfile.mkdtemp(prefix='sophyane-graph-'));pid=new('self-test',str(w));a=add(pid,'write',"bash -lc 'echo ok > result.txt'",[],2,30,'test -s result.txt');add(pid,'read',"bash -lc 'grep -q ok result.txt'",[a],2,30,'');assert run(pid)=='completed';print('SELF-TEST PASSED')
def parser():
 p=argparse.ArgumentParser(prog='sophyane');p.add_argument('--version',action='version',version=VERSION);s=p.add_subparsers(dest='cmd');i=s.add_parser('init');i.add_argument('name');i.add_argument('--workspace');a=s.add_parser('add');a.add_argument('project');a.add_argument('title');a.add_argument('command');a.add_argument('--deps',default='');a.add_argument('--retries',type=int,default=3);a.add_argument('--timeout',type=int,default=300);a.add_argument('--verify',default='')
 for n in ('run','resume','status'):x=s.add_parser(n);x.add_argument('project')
 e=s.add_parser('events');e.add_argument('--tail',type=int,default=50);s.add_parser('self-test');return p
def main():
 graph={'init','add','run','resume','status','events','self-test'}
 if len(sys.argv)>1 and sys.argv[1] in graph:
  a=parser().parse_args()
  if a.cmd=='init':print(new(a.name,a.workspace))
  elif a.cmd=='add':print(add(a.project,a.title,a.command,[x for x in a.deps.split(',') if x],a.retries,a.timeout,a.verify))
  elif a.cmd in ('run','resume'):
   if a.cmd=='resume':
    with conn() as c:c.execute("UPDATE tasks SET status='retry' WHERE project_id=? AND status IN ('failed','running')",(a.project,));c.commit()
   run(a.project)
  elif a.cmd=='status':status(a.project)
  elif a.cmd=='events':print('\n'.join(LOG.read_text().splitlines()[-a.tail:]) if LOG.exists() else '')
  elif a.cmd=='self-test':selftest()
  return
 if len(sys.argv)>1 and sys.argv[1] in ('--version','-V'):print(VERSION);return
 raise SystemExit(delegate(sys.argv[1:]))
if __name__=='__main__':main()
