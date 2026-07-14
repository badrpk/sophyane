#!/usr/bin/env python3
from __future__ import annotations
import hashlib,json,os,platform,shlex,shutil,subprocess,sys,urllib.request
from pathlib import Path
VERSION='10.0.3'
BASE=Path.home()/'.local/share/sophyane';CORE=BASE/'sophyane-core-10.0.2.py'
CORE_URL='https://raw.githubusercontent.com/badrpk/sophyane/84a908c66a69744a7953d491c50200094bf14265/sophyane-10.0.2.py';CORE_BLOB='7e173b411d45c21e336150611ed03e3be10a071c'
def blobsha(d):return hashlib.sha1(f'blob {len(d)}\0'.encode()+d).hexdigest()
def core():
 BASE.mkdir(parents=True,exist_ok=True)
 if CORE.exists() and blobsha(CORE.read_bytes())==CORE_BLOB:return CORE
 d=urllib.request.urlopen(CORE_URL,timeout=30).read()
 if blobsha(d)!=CORE_BLOB:raise RuntimeError('v10.0.2 core integrity mismatch')
 t=CORE.with_suffix('.tmp');t.write_bytes(d);os.chmod(t,0o755);os.replace(t,CORE);return CORE
def delegate(args):return subprocess.call([sys.executable,str(core()),*args])
def run(cmd):
 p=subprocess.run(cmd,text=True,capture_output=True);return (p.stdout or p.stderr).strip(),p.returncode
def system_info():
 print('=== Sophyane system configuration ===');print('Sophyane:',VERSION);print('Python:',sys.version.split()[0]);print('Platform:',platform.platform());print('Machine:',platform.machine());print('Home:',Path.home());print('Current directory:',Path.cwd());print('Shell:',os.environ.get('SHELL','unknown'));print('Termux:','yes' if 'com.termux' in os.environ.get('PREFIX','') else 'no')
 for cmd,label in [(['uname','-a'],'Kernel'),(['df','-h',str(Path.home())],'Storage'),(['free','-h'],'Memory'),(['termux-info'],'Termux details')]:
  if shutil.which(cmd[0]):
   out,_=run(cmd)
   if out:print(f'\n--- {label} ---\n{out}')
def storage_info():
 u=shutil.disk_usage(Path.home());g=1024**3;print(f'=== Storage ===\nTotal: {u.total/g:.1f} GiB\nUsed:  {u.used/g:.1f} GiB\nFree:  {u.free/g:.1f} GiB\nUsage: {u.used/u.total*100:.1f}%')
 if shutil.which('df'):subprocess.run(['df','-h',str(Path.home())])
def battery_info():
 print('=== Battery status ===')
 if shutil.which('termux-battery-status'):
  out,rc=run(['termux-battery-status'])
  if rc==0 and out:
   try:
    d=json.loads(out)
    labels=[('percentage','Charge'),('status','Status'),('plugged','Power source'),('health','Health'),('temperature','Temperature °C'),('current','Current')]
    for k,l in labels:
     if k in d:print(f'{l}: {d[k]}')
   except Exception:print(out)
   return
 candidates=[Path('/sys/class/power_supply/battery'),Path('/sys/class/power_supply/BAT0')]
 for p in candidates:
  if p.exists():
   for name,label in [('capacity','Charge'),('status','Status'),('health','Health'),('temp','Temperature')]:
    f=p/name
    if f.exists():print(f'{label}: {f.read_text().strip()}')
   return
 print('Battery data is unavailable. On Termux, install Termux:API and run: pkg install termux-api')
def is_system(s):
 l=s.lower().strip(' ?');return l in {'system','system info','system information','system configuration','device info','device information'} or ('system' in l and ('config' in l or 'info' in l))
def is_storage(s):
 l=s.lower().strip(' ?');return l in {'storage','disk','disk space','free space','storage status'}
def is_battery(s):return 'battery' in s.lower()
def route(s):
 l=s.lower().strip()
 if is_system(s):system_info();return 0
 if is_storage(s):storage_info();return 0
 if is_battery(s):battery_info();return 0
 if l in {'ls','pwd','whoami','date','uname','df','free'}:
  return subprocess.call(shlex.split(l))
 return delegate(shlex.split(s))
def repl():
 print(f'\n🧠 Sophyane {VERSION}\nUnified graph engine + autonomous builder + device tools\nCommands: make/build/create, system, battery, storage, ls, init, run, self-test, exit\n')
 while True:
  try:s=input('sophyane> ').strip()
  except (EOFError,KeyboardInterrupt):print();break
  if not s:continue
  if s.lower() in {'exit','quit','/exit'}:break
  try:route(s)
  except KeyboardInterrupt:print('\nCancelled. Returning to Sophyane.')
  except Exception as e:print('Error:',e)
def main():
 if len(sys.argv)==1:return repl()
 if sys.argv[1] in ('--version','-V'):print(VERSION);return
 s=' '.join(sys.argv[1:])
 if is_system(s):return system_info()
 if is_storage(s):return storage_info()
 if is_battery(s):return battery_info()
 raise SystemExit(delegate(sys.argv[1:]))
if __name__=='__main__':main()
