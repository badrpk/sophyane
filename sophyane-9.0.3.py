#!/usr/bin/env python3
from __future__ import annotations
import hashlib, json, os, platform, shlex, shutil, subprocess, sys, tempfile, urllib.request
from pathlib import Path

VERSION='9.0.3'
CORE_VERSION='9.0.2'
CORE_URL='https://raw.githubusercontent.com/badrpk/sophyane/a70df37401ea57f74e3113e5ac94dca6a2dbed82/sophyane-9.0.2.py'
CORE_BLOB_SHA='21adc075ace447b5eec24de7ce115457987a9689'
BASE=Path.home()/'.local/share/sophyane'
APP_PATH=Path(__file__).resolve()
REPO_RAW='https://raw.githubusercontent.com/badrpk/sophyane/main'
CORE=BASE/f'sophyane-core-{CORE_VERSION}.py'
LEGACY_CANDIDATES=[Path.home()/'.local/bin/sophyane-legacy',Path.home()/'.local/bin/sophyane-6.1']
SAFE_COMMANDS={'ls','pwd','whoami','id','uname','df','free','du','cat','head','tail','find','which','whereis','python3','python','node','npm','git','termux-info','lscpu','uptime','date'}
BUILD_WORDS=('make ','build ','create ','develop ','generate ','design ')
BROWSER_WORDS=('browser','website','web app','game','html','dashboard','calculator')

def git_blob_sha(data:bytes)->str:
    return hashlib.sha1(f'blob {len(data)}\0'.encode()+data).hexdigest()

def ensure_core()->Path:
    BASE.mkdir(parents=True,exist_ok=True)
    if CORE.exists():
        data=CORE.read_bytes()
        if git_blob_sha(data)==CORE_BLOB_SHA:return CORE
        CORE.unlink(missing_ok=True)
    data=urllib.request.urlopen(CORE_URL,timeout=20).read()
    actual=git_blob_sha(data)
    if actual!=CORE_BLOB_SHA:raise RuntimeError(f'core integrity mismatch: expected {CORE_BLOB_SHA}, got {actual}')
    tmp=CORE.with_suffix('.tmp');tmp.write_bytes(data);os.chmod(tmp,0o755);os.replace(tmp,CORE)
    return CORE

def core_call(args:list[str])->int:
    return subprocess.call([sys.executable,str(ensure_core()),*args])

def system_config()->None:
    print('=== Sophyane system configuration ===')
    print('Sophyane:',VERSION)
    print('Python:',sys.version.split()[0])
    print('Platform:',platform.platform())
    print('Machine:',platform.machine())
    print('Processor:',platform.processor() or 'unknown')
    print('Home:',Path.home())
    print('Current directory:',Path.cwd())
    print('Shell:',os.environ.get('SHELL','unknown'))
    print('Termux:', 'yes' if 'com.termux' in os.environ.get('PREFIX','') else 'no')
    for cmd,label in [(['uname','-a'],'Kernel'),(['df','-h',str(Path.home())],'Storage'),(['free','-h'],'Memory'),(['termux-info'],'Termux details')]:
        if shutil.which(cmd[0]):
            p=subprocess.run(cmd,text=True,capture_output=True)
            out=(p.stdout or p.stderr).strip()
            if out:print(f'\n--- {label} ---\n{out}')

def safe_shell(text:str)->bool:
    try:parts=shlex.split(text)
    except ValueError as e:print('Parse error:',e);return True
    if not parts:return True
    first=Path(parts[0]).name
    if first not in SAFE_COMMANDS:return False
    if any(x in text for x in (';','&&','||','`','$(', '>', '<', '|')):
        print('Shell operators are disabled in the Sophyane REPL. Run complex commands in your normal terminal.')
        return True
    subprocess.run(parts,cwd=Path.cwd())
    return True

def update_self()->int:
    try:
        manifest=json.loads(urllib.request.urlopen(REPO_RAW+'/manifest.json?ts='+str(os.getpid()),timeout=10).read())
        remote=str(manifest['version'])
        if tuple(map(int,remote.split('.')))<=tuple(map(int,VERSION.split('.'))):
            print('Sophyane is already up to date:',VERSION);return 0
        data=urllib.request.urlopen(REPO_RAW+'/'+manifest['entrypoint']+'?ts='+str(os.getpid()),timeout=20).read()
        actual=hashlib.sha256(data).hexdigest();expected=manifest['sha256']
        if actual!=expected:raise RuntimeError(f'update checksum mismatch: expected {expected}, got {actual}')
        fd,tmp=tempfile.mkstemp(dir=APP_PATH.parent);os.write(fd,data);os.fsync(fd);os.close(fd);os.chmod(tmp,0o755);os.replace(tmp,APP_PATH)
        print(f'Updated Sophyane {VERSION} -> {remote}. Restart Sophyane.')
        return 0
    except Exception as e:
        print('Update check failed:',e,file=sys.stderr);return 1

def legacy_call(text:str)->int:
    for p in LEGACY_CANDIDATES:
        if p.exists() and os.access(p,os.X_OK):return subprocess.call([str(p),text])
    print('No configured LLM fallback was found. Browser projects work with “build …”; local commands such as ls/pwd work directly.')
    return 2

def route(text:str)->int:
    s=text.strip();low=s.lower()
    if not s:return 0
    if low in {'exit','quit','/exit'}:return 99
    if low in {'help','?'}:
        print('Commands: build <request> | web | update | self-test | system | ls/pwd/df/uname | exit\nGeneral questions use the configured legacy LLM when available.')
        return 0
    if low in {'system','system info','system configuration','my system configuration','my system configuration?','what is my system configuration','what is my system configuration?'} or ('system' in low and ('configuration' in low or 'config' in low)):
        system_config();return 0
    if low=='update':return update_self()
    if low.startswith('build '):return core_call(['build',s[6:].strip()])
    if low.startswith(BUILD_WORDS) and any(w in low for w in BROWSER_WORDS):return core_call(['build',s])
    if low.split(maxsplit=1)[0] in {'web','self-test','doctor','projects','events','status','run','resume','init','add'}:
        return core_call(shlex.split(s))
    if safe_shell(s):return 0
    return legacy_call(s)

def repl()->None:
    print(f'\n🧠 Sophyane {VERSION}\nAutonomous builder + safe local tools + LLM routing\nCommands: build <request>, web, system, ls, pwd, update, self-test, exit\n')
    while True:
        try:s=input('sophyane> ')
        except (EOFError,KeyboardInterrupt):print();break
        try:r=route(s)
        except Exception as e:print('Error:',e);continue
        if r==99:break

def main()->None:
    if len(sys.argv)==1:repl();return
    if sys.argv[1] in {'--version','-V'}:print(VERSION);return
    if sys.argv[1] in {'repl'}:repl();return
    if sys.argv[1]=='system':system_config();return
    raise SystemExit(route(' '.join(shlex.quote(x) for x in sys.argv[1:])))

if __name__=='__main__':main()
