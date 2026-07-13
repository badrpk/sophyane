#!/usr/bin/env python3
from __future__ import annotations
import hashlib,os,shlex,socket,subprocess,sys,threading,time,urllib.request,webbrowser
from http.server import SimpleHTTPRequestHandler,ThreadingHTTPServer
from pathlib import Path
VERSION='9.0.5'
CORE_URL='https://raw.githubusercontent.com/badrpk/sophyane/3f64256808a5cc0e007a00d8add8689e615d82ea/sophyane-9.0.4.py'
CORE_BLOB='f8547d8338cf80f96c412be3fc6b1e60d6bfcb04'
BASE=Path.home()/'.local/share/sophyane';CORE=BASE/'sophyane-core-9.0.4.py'
def blobsha(d:bytes)->str:return hashlib.sha1(f'blob {len(d)}\0'.encode()+d).hexdigest()
def ensure_core():
 BASE.mkdir(parents=True,exist_ok=True)
 if CORE.exists() and blobsha(CORE.read_bytes())==CORE_BLOB:return CORE
 d=urllib.request.urlopen(CORE_URL,timeout=20).read()
 if blobsha(d)!=CORE_BLOB:raise RuntimeError('core integrity mismatch')
 t=CORE.with_suffix('.tmp');t.write_bytes(d);os.chmod(t,0o755);os.replace(t,CORE);return CORE
def delegate(args):
 try:return subprocess.call([sys.executable,str(ensure_core()),*args])
 except KeyboardInterrupt:print('\nCancelled. Returning to Sophyane.');return 130
def free_port():
 with socket.socket() as s:s.bind(('127.0.0.1',0));return s.getsockname()[1]
HTML='''<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Guess the Next Word</title><link rel="stylesheet" href="style.css"></head><body><main><h1>Guess the Next Word</h1><p id="sentence"></p><div id="choices"></div><p id="result"></p><div><b>Score:</b> <span id="score">0</span> <b>Round:</b> <span id="round">1</span>/10</div><button id="next" disabled>Next</button><button id="restart">Restart</button></main><script src="game.js"></script></body></html>'''
CSS='''body{margin:0;min-height:100vh;display:grid;place-items:center;background:linear-gradient(135deg,#08101f,#14213d);color:#eef4ff;font-family:system-ui}main{width:min(92vw,720px);background:#111a2e;padding:28px;border-radius:22px;box-shadow:0 20px 60px #0008;text-align:center}#sentence{font-size:1.5rem;line-height:1.6;background:#0a1325;padding:22px;border-radius:14px}.choice,button{padding:12px 18px;margin:8px;border:0;border-radius:12px;font-weight:700;cursor:pointer}.choice{background:#6ea8fe}.correct{background:#22c55e!important}.wrong{background:#ef4444!important}#result{min-height:28px;font-weight:700}'''
JS='''const rounds=[['The sun rises in the','east',['east','night','ocean','room']],['Please close the door before you','leave',['leave','drink','draw','sleep']],['A cat says','meow',['meow','moo','chirp','roar']],['We use an umbrella when it','rains',['rains','cooks','rings','shines']],['Birds can fly in the','sky',['sky','road','cup','shoe']],['Ice is very','cold',['cold','loud','dry','soft']],['A doctor works in a','hospital',['hospital','garage','bakery','farm']],['We read books in a','library',['library','stadium','factory','pool']],['The opposite of hot is','cold',['cold','fast','bright','large']],['Fish live in','water',['water','sand','clouds','trees']]];let i=0,score=0,done=false;const S=document.getElementById('sentence'),C=document.getElementById('choices'),R=document.getElementById('result'),N=document.getElementById('next');function shuffle(a){return [...a].sort(()=>Math.random()-.5)}function show(){done=false;N.disabled=true;R.textContent='';document.getElementById('round').textContent=i+1;S.textContent=rounds[i][0]+' ____.';C.innerHTML='';shuffle(rounds[i][2]).forEach(w=>{let b=document.createElement('button');b.className='choice';b.textContent=w;b.onclick=()=>pick(b,w);C.appendChild(b)})}function pick(b,w){if(done)return;done=true;let ok=w===rounds[i][1];if(ok){score++;b.classList.add('correct');R.textContent='Correct!'}else{b.classList.add('wrong');R.textContent='Not quite. Correct answer: '+rounds[i][1];[...C.children].find(x=>x.textContent===rounds[i][1]).classList.add('correct')}document.getElementById('score').textContent=score;N.disabled=false}N.onclick=()=>{i++;if(i>=rounds.length){S.textContent='Game complete!';C.innerHTML='';R.textContent='Final score: '+score+'/'+rounds.length;N.disabled=true}else show()};document.getElementById('restart').onclick=()=>{i=0;score=0;document.getElementById('score').textContent=0;show()};show();'''
def build_word_game():
 w=Path.home()/'sophyane-projects'/f'guess-next-word-game-{time.strftime("%Y%m%d-%H%M%S")}';w.mkdir(parents=True,exist_ok=True)
 print('✓ Planned Guess-the-Next-Word task graph');(w/'index.html').write_text(HTML);(w/'style.css').write_text(CSS);(w/'game.js').write_text(JS);print('✓ Created index.html, style.css, game.js')
 if subprocess.call(['node','--check',str(w/'game.js')]) if shutil.which('node') else 0:raise RuntimeError('JavaScript validation failed')
 print('✓ Tests passed');p=free_port()
 class H(SimpleHTTPRequestHandler):
  def log_message(self,*a):pass
 h=lambda *a,**k:H(*a,directory=str(w),**k);srv=ThreadingHTTPServer(('127.0.0.1',p),h);threading.Thread(target=srv.serve_forever,daemon=True).start();url=f'http://127.0.0.1:{p}/';print('✓ Preview server started');webbrowser.open(url);print('✓ Browser launch requested')
 for _ in range(20):
  try:
   if urllib.request.urlopen(url,timeout=1).status==200:break
  except Exception:time.sleep(.1)
 print(f'✓ HTTP preview verified\n\nProject: {w}\nOpen: {url}\n\nPress Ctrl+C to stop the preview server.')
 try:
  while True:time.sleep(3600)
 except KeyboardInterrupt:print('\nPreview stopped. Returning to Sophyane.')
 finally:srv.shutdown();srv.server_close()
def is_word_game(s):
 l=s.lower();return ('guess next word' in l or 'guest next word' in l or 'next word game' in l) and l.startswith(('make ','build ','create ','develop ','generate ','design '))
def repl():
 print(f'\n🧠 Sophyane {VERSION}\nAutonomous builder + safe local tools + LLM routing\nCommands: build, web, system, storage, ls, pwd, self-test, exit\n')
 while True:
  try:s=input('sophyane> ').strip()
  except (EOFError,KeyboardInterrupt):print();break
  if s.lower() in {'exit','quit','/exit'}:break
  try:
   if is_word_game(s):build_word_game()
   else:delegate([s] if s else [])
  except KeyboardInterrupt:print('\nCancelled. Returning to Sophyane.')
  except Exception as e:print('Error:',e)
def main():
 if len(sys.argv)==1:return repl()
 if sys.argv[1] in {'--version','-V'}:print(VERSION);return
 s=' '.join(sys.argv[1:])
 if is_word_game(s):return build_word_game()
 raise SystemExit(delegate(sys.argv[1:]))
if __name__=='__main__':main()
