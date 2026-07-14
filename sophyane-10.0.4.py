#!/usr/bin/env python3
from __future__ import annotations
import hashlib,os,re,shlex,subprocess,sys,urllib.request
from pathlib import Path
VERSION='10.0.4'
BASE=Path.home()/'.local/share/sophyane';CORE=BASE/'sophyane-core-10.0.3.py'
CORE_URL='https://raw.githubusercontent.com/badrpk/sophyane/2b747150ae27a30d1f256d2ea68e83e79bdea451/sophyane-10.0.3.py';CORE_BLOB='c15d03e47affd43c6f02d666579e9a41f88c23ae'
def blobsha(d):return hashlib.sha1(f'blob {len(d)}\0'.encode()+d).hexdigest()
def core():
 BASE.mkdir(parents=True,exist_ok=True)
 if CORE.exists() and blobsha(CORE.read_bytes())==CORE_BLOB:return CORE
 d=urllib.request.urlopen(CORE_URL,timeout=30).read()
 if blobsha(d)!=CORE_BLOB:raise RuntimeError('v10.0.3 core integrity mismatch')
 t=CORE.with_suffix('.tmp');t.write_bytes(d);os.chmod(t,0o755);os.replace(t,CORE);return CORE
def clean(s):
 s=s.strip()
 while True:
  n=re.sub(r'^\s*sophyane>\s*','',s,flags=re.I)
  if n==s:return s
  s=n
def delegate_text(s):
 s=clean(s)
 if not s:return 0
 return subprocess.call([sys.executable,str(core()),*shlex.split(s)])
def repl():
 print(f'\n🧠 Sophyane {VERSION}\nUnified graph engine + autonomous builder + device tools\nAccidental “sophyane>” prefixes are removed automatically.\nCommands: make/build/create, system, battery, storage, ls, init, run, self-test, exit\n')
 while True:
  try:s=input('sophyane> ')
  except (EOFError,KeyboardInterrupt):print();break
  s=clean(s)
  if not s:continue
  if s.lower() in {'exit','quit','/exit'}:break
  try:delegate_text(s)
  except KeyboardInterrupt:print('\nCancelled. Returning to Sophyane.')
  except Exception as e:print('Error:',e)
def main():
 if len(sys.argv)==1:return repl()
 if sys.argv[1] in ('--version','-V'):print(VERSION);return
 raise SystemExit(delegate_text(' '.join(sys.argv[1:])))
if __name__=='__main__':main()
