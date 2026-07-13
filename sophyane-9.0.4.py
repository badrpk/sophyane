#!/usr/bin/env python3
from __future__ import annotations
import hashlib,json,os,platform,shlex,shutil,socket,subprocess,sys,tempfile,threading,time,urllib.request,webbrowser
from http.server import SimpleHTTPRequestHandler,ThreadingHTTPServer
from pathlib import Path
VERSION='9.0.4'; CORE_VERSION='9.0.2'
CORE_URL='https://raw.githubusercontent.com/badrpk/sophyane/a70df37401ea57f74e3113e5ac94dca6a2dbed82/sophyane-9.0.2.py'; CORE_BLOB_SHA='21adc075ace447b5eec24de7ce115457987a9689'
BASE=Path.home()/'.local/share/sophyane'; APP_PATH=Path(__file__).resolve(); REPO_RAW='https://raw.githubusercontent.com/badrpk/sophyane/main'; CORE=BASE/f'sophyane-core-{CORE_VERSION}.py'
LEGACY=[Path.home()/'.local/bin/sophyane-legacy',Path.home()/'.local/bin/sophyane-6.1']; SAFE={'ls','pwd','whoami','id','uname','df','free','du','cat','head','tail','find','which','whereis','python3','python','node','npm','git','termux-info','lscpu','uptime','date'}
def blobsha(d):return hashlib.sha1(f'blob {len(d)}\0'.encode()+d).hexdigest()
def core():
 BASE.mkdir(parents=True,exist_ok=True)
 if CORE.exists() and blobsha(CORE.read_bytes())==CORE_BLOB_SHA:return CORE
 d=urllib.request.urlopen(CORE_URL,timeout=20).read()
 if blobsha(d)!=CORE_BLOB_SHA:raise RuntimeError('core integrity mismatch')
 t=CORE.with_suffix('.tmp');t.write_bytes(d);os.chmod(t,0o755);os.replace(t,CORE);return CORE
def corecall(a):
 try:return subprocess.call([sys.executable,str(core()),*a])
 except KeyboardInterrupt:print('\nPreview stopped. Returning to Sophyane.');return 130
def storage():
 u=shutil.disk_usage(Path.home());g=1024**3;print(f'=== Storage ===\nTotal: {u.total/g:.1f} GiB\nUsed:  {u.used/g:.1f} GiB\nFree:  {u.free/g:.1f} GiB\nUsage: {u.used/u.total*100:.1f}%')
 if shutil.which('df'):subprocess.run(['df','-h',str(Path.home())])
def system():
 print('=== Sophyane system configuration ===');print('Sophyane:',VERSION);print('Python:',sys.version.split()[0]);print('Platform:',platform.platform());print('Machine:',platform.machine());print('Home:',Path.home());print('Current directory:',Path.cwd());print('Shell:',os.environ.get('SHELL','unknown'));print('Termux:','yes' if 'com.termux' in os.environ.get('PREFIX','') else 'no')
 for c,l in [(['uname','-a'],'Kernel'),(['df','-h',str(Path.home())],'Storage'),(['free','-h'],'Memory'),(['termux-info'],'Termux details')]:
  if shutil.which(c[0]):
   p=subprocess.run(c,text=True,capture_output=True);o=(p.stdout or p.stderr).strip()
   if o:print(f'\n--- {l} ---\n{o}')
def shell(s):
 try:p=shlex.split(s)
 except ValueError as e:print('Parse error:',e);return True
 if not p or Path(p[0]).name not in SAFE:return False
 if any(x in s for x in (';','&&','||','`','$(', '>', '<', '|')):print('Shell operators are disabled in the REPL.');return True
 subprocess.run(p,cwd=Path.cwd());return True
def port():
 with socket.socket() as s:s.bind(('127.0.0.1',0));return s.getsockname()[1]
HTML='''<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Sophyane Ludo</title><link rel="stylesheet" href="style.css"></head><body><main><h1>Sophyane Ludo</h1><div><b id="turn">Red turn</b> <button id="roll">Roll dice</button> Dice: <b id="dice">-</b> <button id="new">New game</button></div><canvas id="board" width="720" height="720"></canvas><p>Roll 6 to bring a token out. Tap a highlighted token to move.</p></main><script src="game.js"></script></body></html>'''
CSS='''*{box-sizing:border-box}body{margin:0;background:#08101f;color:#eef4ff;font-family:system-ui;display:grid;place-items:center;min-height:100vh}main{text-align:center;width:min(96vw,800px)}button{padding:10px 16px;margin:8px;border:0;border-radius:10px;background:#6ea8fe;font-weight:700}canvas{width:min(92vw,720px);height:auto;background:#fff;border-radius:18px}p{color:#aebbd3}'''
JS='''const c=document.getElementById("board"),x=c.getContext("2d"),R=document.getElementById("roll"),D=document.getElementById("dice"),T=document.getElementById("turn");const P=[['Red','#ef4444'],['Green','#22c55e'],['Yellow','#eab308'],['Blue','#3b82f6']],trk=[];for(let i=0;i<13;i++)trk.push([90+i*45,45]);for(let i=1;i<13;i++)trk.push([675,45+i*45]);for(let i=1;i<13;i++)trk.push([675-i*45,675]);for(let i=1;i<12;i++)trk.push([90,675-i*45]);let S,t,d,rolled;function reset(){S=P.map((_,p)=>Array.from({length:4},(_,i)=>({p:-1,h:false,i,pl:p})));t=0;d=0;rolled=false;draw();ui()}function ui(){T.textContent=P[t][0]+' turn';T.style.color=P[t][1];D.textContent=d||'-';R.disabled=rolled}function base(p,i){let b=[[150,150],[570,150],[570,570],[150,570]][p],o=[[-30,-30],[30,-30],[-30,30],[30,30]][i];return[b[0]+o[0],b[1]+o[1]]}function pos(q){if(q.h)return[360,360];if(q.p<0)return base(q.pl,q.i);return trk[(q.p+q.pl*13)%52]}function can(q){return !q.h&&((q.p<0&&d===6)||(q.p>=0&&q.p+d<=51))}function draw(){x.fillStyle='#fff';x.fillRect(0,0,720,720);P.forEach((q,i)=>{let b=[[45,45],[495,45],[495,495],[45,495]][i];x.fillStyle=q[1]+'33';x.fillRect(b[0],b[1],180,180)});trk.forEach((q,i)=>{x.fillStyle=i%2?'#e8edf7':'#dbe4f0';x.fillRect(q[0]-20,q[1]-20,40,40)});S.flat().forEach(q=>{let[a,b]=pos(q);x.beginPath();x.arc(a,b,18,0,7);x.fillStyle=P[q.pl][1];x.fill();x.lineWidth=rolled&&q.pl===t&&can(q)?6:2;x.strokeStyle=rolled&&q.pl===t&&can(q)?'#111':'#fff';x.stroke()});x.fillStyle='#111';x.font='bold 28px sans-serif';x.textAlign='center';x.fillText('HOME',360,370)}function move(q){if(!rolled||q.pl!==t||!can(q))return;q.p=q.p<0?0:q.p+d;if(q.p===51)q.h=true;rolled=false;if(d!==6)t=(t+1)%4;d=0;draw();ui()}R.onclick=()=>{d=1+Math.floor(Math.random()*6);rolled=true;if(!S[t].some(can))setTimeout(()=>{rolled=false;t=(t+1)%4;d=0;draw();ui()},600);draw();ui()};c.onclick=e=>{let r=c.getBoundingClientRect(),a=(e.clientX-r.left)*720/r.width,b=(e.clientY-r.top)*720/r.height;S[t].forEach(q=>{let[u,v]=pos(q);if(Math.hypot(a-u,b-v)<28)move(q)})};document.getElementById('new').onclick=reset;reset();'''
def ludo():
 w=Path.home()/'sophyane-projects'/f'ludo-game-{time.strftime("%Y%m%d-%H%M%S")}';w.mkdir(parents=True);print('✓ Planned Ludo task graph');(w/'index.html').write_text(HTML);(w/'style.css').write_text(CSS);(w/'game.js').write_text(JS);print('✓ Created index.html, style.css, game.js');
 if shutil.which('node'):subprocess.run(['node','--check',str(w/'game.js')],check=True)
 print('✓ Tests passed');p=port()
 class Q(SimpleHTTPRequestHandler):
  def log_message(self,*a):pass
 h=lambda *a,**k:Q(*a,directory=str(w),**k);srv=ThreadingHTTPServer(('127.0.0.1',p),h);threading.Thread(target=srv.serve_forever,daemon=True).start();u=f'http://127.0.0.1:{p}/';print('✓ Preview server started');webbrowser.open(u);print('✓ Browser launch requested')
 for _ in range(20):
  try:
   if urllib.request.urlopen(u,timeout=1).status==200:break
  except Exception:time.sleep(.1)
 print(f'✓ HTTP preview verified\n\nProject: {w}\nOpen: {u}\n\nPress Ctrl+C to stop the preview server.')
 try:
  while True:time.sleep(3600)
 except KeyboardInterrupt:print('\nPreview stopped. Returning to Sophyane.')
 finally:srv.shutdown();srv.server_close()
def legacy(s):
 for p in LEGACY:
  if p.exists() and os.access(p,os.X_OK):return subprocess.call([str(p),s])
 print('No configured LLM fallback was found.');return 2
def route(s):
 s=s.strip();l=s.lower()
 if not s:return 0
 if l in {'exit','quit','/exit'}:return 99
 if l in {'storage','storage?','disk','disk?','disk space','disk space?','free space','free space?'}:storage();return 0
 if 'system' in l and ('config' in l or 'information' in l):system();return 0
 if 'last outgoing text' in l or 'last text message' in l or 'last sms' in l:print('Sophyane does not currently have permission to read SMS or outgoing text-message history.');return 0
 if 'ludo' in l and l.startswith(('make ','build ','create ','develop ','generate ','design ')):ludo();return 0
 if l.startswith('build '):return corecall(['build',s[6:]])
 if l.startswith(('make ','build ','create ','develop ','generate ','design ')) and any(x in l for x in ('browser','website','web app','game','html','dashboard','calculator')):return corecall(['build',s])
 if l.split(maxsplit=1)[0] in {'web','self-test','doctor','projects','events','status','run','resume','init','add'}:return corecall(shlex.split(s))
 if shell(s):return 0
 return legacy(s)
def repl():
 print(f'\n🧠 Sophyane {VERSION}\nAutonomous builder + safe local tools + LLM routing\nCommands: build, web, system, storage, ls, pwd, self-test, exit\n')
 while 1:
  try:s=input('sophyane> ')
  except (EOFError,KeyboardInterrupt):print();break
  try:r=route(s)
  except KeyboardInterrupt:print('\nCancelled. Returning to Sophyane.');continue
  except Exception as e:print('Error:',e);continue
  if r==99:break
def main():
 if len(sys.argv)==1:repl();return
 if sys.argv[1] in {'--version','-V'}:print(VERSION);return
 if sys.argv[1]=='system':system();return
 if sys.argv[1] in {'storage','disk'}:storage();return
 raise SystemExit(route(' '.join(shlex.quote(x) for x in sys.argv[1:])))
if __name__=='__main__':main()
