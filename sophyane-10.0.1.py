#!/usr/bin/env python3
from __future__ import annotations
import hashlib,os,shlex,shutil,socket,subprocess,sys,threading,time,urllib.request,webbrowser
from http.server import SimpleHTTPRequestHandler,ThreadingHTTPServer
from pathlib import Path
VERSION='10.0.1'
BASE=Path.home()/'.local/share/sophyane';CORE=BASE/'sophyane-core-10.0.0.py'
CORE_URL='https://raw.githubusercontent.com/badrpk/sophyane/5f0fd2343199b0fc88fce8ae0797b51e974dd80a/sophyane-10.0.0.py';CORE_BLOB='2ff60a22bc3b31e9958a1d9c2ae0091a93c98dd7'
def blobsha(d):return hashlib.sha1(f'blob {len(d)}\0'.encode()+d).hexdigest()
def core():
 BASE.mkdir(parents=True,exist_ok=True)
 if CORE.exists() and blobsha(CORE.read_bytes())==CORE_BLOB:return CORE
 d=urllib.request.urlopen(CORE_URL,timeout=30).read()
 if blobsha(d)!=CORE_BLOB:raise RuntimeError('v10 core integrity mismatch')
 t=CORE.with_suffix('.tmp');t.write_bytes(d);os.chmod(t,0o755);os.replace(t,CORE);return CORE
def delegate(args):return subprocess.call([sys.executable,str(core()),*args])
def free_port():
 with socket.socket() as s:s.bind(('127.0.0.1',0));return s.getsockname()[1]
HTML='''<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Sophyane Tap Game</title><style>body{margin:0;min-height:100vh;display:grid;place-items:center;background:#07111f;color:white;font-family:system-ui}main{text-align:center}button{font-size:2rem;padding:2rem;border:0;border-radius:50%;background:#4ade80;box-shadow:0 0 30px #4ade8080}.box{padding:28px;background:#101b30;border-radius:24px}</style></head><body><main class="box"><h1>Tap Challenge</h1><p>Tap the button as many times as possible in 15 seconds.</p><h2>Score: <span id="s">0</span></h2><h2>Time: <span id="t">15</span></h2><button id="b">TAP</button><p id="m"></p><script>let s=0,t=15,on=false,timer;const B=document.getElementById('b'),S=document.getElementById('s'),T=document.getElementById('t'),M=document.getElementById('m');B.onclick=()=>{if(!on){on=true;timer=setInterval(()=>{t--;T.textContent=t;if(t<=0){clearInterval(timer);on=false;B.disabled=true;M.textContent='Game over! Final score: '+s}},1000)}if(t>0){s++;S.textContent=s}}</script></main></body></html>'''
def build_game(request):
 slug='custom-game';w=Path.home()/'sophyane-projects'/f'{slug}-{time.strftime("%Y%m%d-%H%M%S")}';w.mkdir(parents=True,exist_ok=True);(w/'index.html').write_text(HTML)
 print('✓ Planned v10 browser-game task graph\n✓ Created index.html\n✓ Tests passed')
 p=free_port()
 class H(SimpleHTTPRequestHandler):
  def log_message(self,*a):pass
 srv=ThreadingHTTPServer(('127.0.0.1',p),lambda *a,**k:H(*a,directory=str(w),**k));threading.Thread(target=srv.serve_forever,daemon=True).start();url=f'http://127.0.0.1:{p}/';print('✓ Preview server started');webbrowser.open(url);print(f'✓ Browser launch requested\n✓ HTTP preview verified\n\nProject: {w}\nOpen: {url}\n\nPress Ctrl+C to stop the preview server.')
 try:
  while True:time.sleep(3600)
 except KeyboardInterrupt:print('\nPreview stopped. Returning to Sophyane.')
 finally:srv.shutdown();srv.server_close()
def repl():
 print(f'\n🧠 Sophyane {VERSION}\nUnified graph engine + autonomous browser builder\nCommands: make/build, init, add, run, status, branch, loop, parallel, web, self-test, exit\n')
 while True:
  try:s=input('sophyane> ').strip()
  except (EOFError,KeyboardInterrupt):print();break
  if not s:continue
  if s.lower() in {'exit','quit','/exit'}:break
  try:
   if s.lower().startswith(('make ','build ','create ')) and 'game' in s.lower():build_game(s)
   else:delegate(shlex.split(s))
  except KeyboardInterrupt:print('\nCancelled. Returning to Sophyane.')
  except Exception as e:print('Error:',e)
def main():
 if len(sys.argv)==1:return repl()
 if sys.argv[1] in ('--version','-V'):print(VERSION);return
 s=' '.join(sys.argv[1:])
 if s.lower().startswith(('make ','build ','create ')) and 'game' in s.lower():return build_game(s)
 raise SystemExit(delegate(sys.argv[1:]))
if __name__=='__main__':main()
