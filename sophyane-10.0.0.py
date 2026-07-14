#!/usr/bin/env python3
from __future__ import annotations
import argparse,ast,hashlib,json,os,shlex,signal,sqlite3,subprocess,sys,tempfile,time,urllib.request,uuid
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor,as_completed
VERSION='10.0.0'
ROOT=Path.home()/'.local/state/sophyane';DB=ROOT/'sophyane.sqlite3';ADV=ROOT/'advanced';WORKERS=ADV/'workers';HUMAN=ADV/'human';SUBS=ADV/'subgraphs.json'
BASE=Path.home()/'.local/share/sophyane';CORE=BASE/'sophyane-core-9.0.7.py'
CORE_URL='https://raw.githubusercontent.com/badrpk/sophyane/26a391f15c543bdf605d587e782d1b50925c95c0/sophyane-9.0.7.py';CORE_BLOB='8b44d1985cef534a5ec16faf7a035806fd1c4e02'
for p in (ROOT,ADV,WORKERS,HUMAN,BASE):p.mkdir(parents=True,exist_ok=True)
def blobsha(d:bytes)->str:return hashlib.sha1(f'blob {len(d)}\0'.encode()+d).hexdigest()
def ensure_core()->Path:
 if CORE.exists() and blobsha(CORE.read_bytes())==CORE_BLOB:return CORE
 d=urllib.request.urlopen(CORE_URL,timeout=30).read()
 if blobsha(d)!=CORE_BLOB:raise RuntimeError('v9.0.7 core integrity mismatch')
 t=CORE.with_suffix('.tmp');t.write_bytes(d);os.chmod(t,0o755);os.replace(t,CORE);return CORE
def delegate(args:list[str])->int:return subprocess.call([sys.executable,str(ensure_core()),*args])
def dbrow(sql,args=()):
 with sqlite3.connect(DB) as c:
  c.row_factory=sqlite3.Row;return c.execute(sql,args).fetchone()
def workspace(pid:str)->Path:
 r=dbrow('SELECT workspace FROM projects WHERE id=?',(pid,))
 if not r:raise SystemExit(f'project not found: {pid}')
 return Path(r['workspace'])
def safe_eval(expr:str,state:dict)->bool:
 tree=ast.parse(expr,mode='eval')
 allowed=(ast.Expression,ast.BoolOp,ast.UnaryOp,ast.Compare,ast.Name,ast.Load,ast.Constant,ast.And,ast.Or,ast.Not,ast.Eq,ast.NotEq,ast.Gt,ast.GtE,ast.Lt,ast.LtE)
 if any(not isinstance(n,allowed) for n in ast.walk(tree)):raise ValueError('unsupported expression')
 return bool(eval(compile(tree,'<condition>','eval'),{'__builtins__':{}},state))
def run_shell(cmd:str,cwd:Path)->int:return subprocess.call(['bash','-lc',cmd],cwd=cwd)
def cmd_branch(a):
 st=json.loads(Path(a.state).read_text());chosen=a.true_command if safe_eval(a.expression,st) else a.false_command;rc=run_shell(chosen,workspace(a.project));print('branch=true' if chosen==a.true_command else 'branch=false');return rc
def cmd_loop(a):
 w=Path(a.workspace).expanduser();w.mkdir(parents=True,exist_ok=True)
 for i in range(1,a.max_iterations+1):
  rc=run_shell(a.command,w);print(f'iteration:{i} command_rc:{rc}',flush=True)
  if rc!=0:return rc
  if run_shell(a.until,w)==0:print(f'loop completed after {i} iterations');return 0
 print('maximum iterations reached',file=sys.stderr);return 1
def cmd_parallel(a):
 w=Path(a.workspace).expanduser();w.mkdir(parents=True,exist_ok=True)
 def one(c):return c,subprocess.run(['bash','-lc',c],cwd=w,text=True,capture_output=True)
 rc=0
 with ThreadPoolExecutor(max_workers=len(a.commands)) as ex:
  for f in as_completed([ex.submit(one,c) for c in a.commands]):
   c,p=f.result();sys.stdout.write(p.stdout);sys.stderr.write(p.stderr);print(f'[{p.returncode}] {c}');rc=rc or p.returncode
 return rc
def submap():
 try:return json.loads(SUBS.read_text())
 except Exception:return {}
def cmd_subgraph(a):
 m=submap();m.setdefault(a.parent,[])
 if a.child not in m[a.parent]:m[a.parent].append(a.child)
 SUBS.write_text(json.dumps(m,indent=2));print(f'added child {a.child} to parent {a.parent}');return 0
def cmd_run_with_subgraphs(pid):
 rc=delegate(['run',pid]);
 if rc:return rc
 for child in submap().get(pid,[]):
  print(f'running subgraph {child}');rc=delegate(['run',child])
  if rc:return rc
 return 0
def cmd_reduce(a):
 data=json.loads(Path(a.state).read_text());vals=data.get(a.field)
 if not isinstance(vals,list):raise SystemExit('field must be a list')
 ops={'sum':sum,'min':min,'max':max,'count':len,'concat':lambda x:sum(x,[])}
 if a.operation not in ops:raise SystemExit('unsupported reducer')
 data[a.field]=ops[a.operation](vals);Path(a.output).write_text(json.dumps(data,indent=2));print(data[a.field]);return 0
def cmd_stream(a):
 p=subprocess.Popen(['bash','-lc',a.command],stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,bufsize=1)
 assert p.stdout
 for line in p.stdout:print(line,end='',flush=True)
 return p.wait()
def statefile(pid):return HUMAN/f'{pid}.json'
def cmd_interrupt(a):
 workspace(a.project);d={'project_id':a.project,'status':'interrupted','reason':a.reason,'state':json.loads(a.state),'updated':time.time()};statefile(a.project).write_text(json.dumps(d,indent=2));
 with sqlite3.connect(DB) as c:c.execute("UPDATE projects SET status='interrupted',updated=? WHERE id=?",(time.time(),a.project));c.commit()
 print('graph interrupted:',a.reason);return 0
def parseval(v):
 try:return json.loads(v)
 except Exception:return v
def cmd_edit(a):
 f=statefile(a.project)
 if not f.exists():raise SystemExit('no interrupted state')
 d=json.loads(f.read_text())
 for item in a.sets:
  k,v=item.split('=',1);d['state'][k]=parseval(v)
 d['updated']=time.time();f.write_text(json.dumps(d,indent=2));print('state updated:',json.dumps(d['state']));return 0
def cmd_resume_v10(pid):
 f=statefile(pid)
 if f.exists():
  d=json.loads(f.read_text());d['status']='resumed';d['updated']=time.time();f.write_text(json.dumps(d,indent=2));print('approved state:',json.dumps(d['state']))
 return delegate(['resume',pid])
def cmd_rewind(a):
 w=workspace(a.project)
 with sqlite3.connect(DB) as c:
  c.row_factory=sqlite3.Row;cp=c.execute('SELECT * FROM checkpoints WHERE id=? AND project_id=?',(a.checkpoint,a.project)).fetchone()
  if not cp:raise SystemExit('checkpoint not found')
  tasks=c.execute('SELECT command FROM tasks WHERE project_id=? ORDER BY created',(a.project,)).fetchall()
 for r in tasks:
  if run_shell(r['command'],w)!=0:raise SystemExit('replay failed')
 print('restored workspace and graph state from checkpoint',a.checkpoint);return 0
def workerfile(name):return WORKERS/f'{name}.json'
def cmd_worker_start(a):
 f=workerfile(a.name);stop=False
 def sig(*_):
  nonlocal stop;stop=True
 signal.signal(signal.SIGTERM,sig);signal.signal(signal.SIGINT,sig)
 while not stop:
  f.write_text(json.dumps({'name':a.name,'pid':os.getpid(),'concurrency':a.concurrency,'heartbeat':time.time()}));time.sleep(1)
 f.unlink(missing_ok=True);return 0
def cmd_worker_list(_):
 now=time.time()
 for f in WORKERS.glob('*.json'):
  try:
   d=json.loads(f.read_text())
   if now-d['heartbeat']<5:print(f"{d['name']} pid={d['pid']} concurrency={d['concurrency']} online")
  except Exception:pass
 return 0
def typeok(v,t):return {'integer':lambda:isinstance(v,int) and not isinstance(v,bool),'boolean':lambda:isinstance(v,bool),'string':lambda:isinstance(v,str),'number':lambda:isinstance(v,(int,float)) and not isinstance(v,bool),'array':lambda:isinstance(v,list),'object':lambda:isinstance(v,dict),'null':lambda:v is None}.get(t,lambda:True)()
def cmd_schema(a):
 s=json.loads(Path(a.schema).read_text());d=json.loads(Path(a.data).read_text());errs=[]
 if s.get('type')=='object' and not isinstance(d,dict):errs.append('root must be object')
 if isinstance(d,dict):
  for k in s.get('required',[]):
   if k not in d:errs.append(f'missing required field: {k}')
  for k,v in d.items():
   if k in s.get('properties',{}) and not typeok(v,s['properties'][k].get('type')):errs.append(f'{k}: wrong type')
   if s.get('additionalProperties') is False and k not in s.get('properties',{}):errs.append(f'unexpected field: {k}')
 if errs:
  print('\n'.join(errs),file=sys.stderr);return 1
 print('schema valid');return 0
def parser():
 p=argparse.ArgumentParser(prog='sophyane');p.add_argument('--version',action='version',version=VERSION);sp=p.add_subparsers(dest='cmd')
 b=sp.add_parser('branch');b.add_argument('project');b.add_argument('--state',required=True);b.add_argument('--expression',required=True);b.add_argument('--true-command',required=True);b.add_argument('--false-command',required=True)
 l=sp.add_parser('loop');l.add_argument('--workspace',required=True);l.add_argument('--command',required=True);l.add_argument('--until',required=True);l.add_argument('--max-iterations',type=int,default=10)
 q=sp.add_parser('parallel');q.add_argument('--workspace',required=True);q.add_argument('commands',nargs='+')
 sg=sp.add_parser('subgraph');ss=sg.add_subparsers(dest='sub');sa=ss.add_parser('add');sa.add_argument('parent');sa.add_argument('child')
 r=sp.add_parser('reduce');r.add_argument('--state',required=True);r.add_argument('--field',required=True);r.add_argument('--operation',required=True);r.add_argument('--output',required=True)
 st=sp.add_parser('stream');st.add_argument('--command',required=True)
 it=sp.add_parser('interrupt');it.add_argument('project');it.add_argument('--state',required=True);it.add_argument('--reason',default='Human review required')
 ed=sp.add_parser('edit-state');ed.add_argument('project');ed.add_argument('--set',dest='sets',action='append',required=True)
 rw=sp.add_parser('rewind');rw.add_argument('project');rw.add_argument('checkpoint')
 wk=sp.add_parser('worker');ws=wk.add_subparsers(dest='worker_cmd');wks=ws.add_parser('start');wks.add_argument('--name',required=True);wks.add_argument('--concurrency',type=int,default=1);ws.add_parser('list')
 sc=sp.add_parser('schema');scs=sc.add_subparsers(dest='schema_cmd');sv=scs.add_parser('validate');sv.add_argument('schema');sv.add_argument('data')
 return p
def main():
 advanced={'branch','condition','loop','parallel','subgraph','reduce','reducer','stream','interrupt','edit-state','rewind','restore','worker','schema'}
 if len(sys.argv)==1:return delegate([])
 if sys.argv[1] in ('--version','-V'):print(VERSION);return
 if sys.argv[1]=='run' and len(sys.argv)>2:return sys.exit(cmd_run_with_subgraphs(sys.argv[2]))
 if sys.argv[1]=='resume' and len(sys.argv)>2:return sys.exit(cmd_resume_v10(sys.argv[2]))
 if sys.argv[1] not in advanced:return sys.exit(delegate(sys.argv[1:]))
 if sys.argv[1]=='condition':sys.argv[1]='branch'
 if sys.argv[1]=='reducer':sys.argv[1]='reduce'
 if sys.argv[1]=='restore':sys.argv[1]='rewind'
 a=parser().parse_args();fn={'branch':cmd_branch,'loop':cmd_loop,'parallel':cmd_parallel,'subgraph':cmd_subgraph,'reduce':cmd_reduce,'stream':cmd_stream,'interrupt':cmd_interrupt,'edit-state':cmd_edit,'rewind':cmd_rewind,'worker':lambda x:cmd_worker_start(x) if x.worker_cmd=='start' else cmd_worker_list(x),'schema':cmd_schema}[a.cmd];sys.exit(fn(a))
if __name__=='__main__':main()
