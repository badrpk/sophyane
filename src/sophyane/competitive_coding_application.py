"""Replay-resistant, crash-recoverable competitive application boundary."""
from __future__ import annotations
import base64, binascii, fcntl, hashlib, json, os, stat, subprocess, tempfile
from dataclasses import asdict, dataclass
from pathlib import Path
import sophyane.competitive_coding_application_transaction as txmod
from sophyane.competitive_coding_application_preflight import prepare_competitive_application
from sophyane.competitive_coding_application_transaction import get_competitive_application_transaction, prepare_competitive_application_transaction
from sophyane.competitive_coding_consumption import get_competitive_approval_claim, claim_competitive_approval
from sophyane.competitive_coding_phase2 import CompetitiveEvaluationResult

__all__ = ["CompetitiveApplicationError", "CompetitiveApplicationResult", "apply_competitive_application", "recover_competitive_application", "get_competitive_application_result"]
_SCHEMA, _LEDGER, _LOCK = 1, "applications.json", "applications.lock"
_FIELDS = {"request_id", "state", "applied", "approval_digest", "approval_payload", "repository", "source_head", "candidate_id", "candidate_patch_sha256", "changed_paths", "reason"}
_PAYLOAD_FIELDS = {"objective", "repository", "target_name", "source_head", "baseline_patch_sha256", "candidate_id", "candidate_patch_sha256", "trusted_evidence_digest"}
_IMMUTABLE_FIELDS = ("request_id", "approval_digest", "approval_payload", "repository", "source_head", "candidate_id", "candidate_patch_sha256", "changed_paths")

class CompetitiveApplicationError(RuntimeError): pass

@dataclass(frozen=True)
class CompetitiveApplicationResult:
    request_id: str
    state: str
    applied: bool
    approval_digest: str
    approval_payload: str
    repository: str
    source_head: str
    candidate_id: str
    candidate_patch_sha256: str
    changed_paths: tuple[str, ...]
    reason: str

def _dir(value): return (Path.home()/".local/state/sophyane/competitive-applications" if value is None else Path(value)).expanduser()
def _canon(value): return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
def _sha(value): return hashlib.sha256(value).hexdigest()
def _b64(value): return base64.b64encode(value).decode("ascii")
def _decode(value):
    if not isinstance(value, str): raise CompetitiveApplicationError("invalid base64")
    try: raw = base64.b64decode(value.encode("ascii", errors="strict"), validate=True)
    except (UnicodeError, binascii.Error, ValueError) as exc: raise CompetitiveApplicationError("invalid base64") from exc
    if _b64(raw) != value: raise CompetitiveApplicationError("noncanonical base64")
    return raw
def _digest(value): return isinstance(value, str) and len(value)==64 and all(c in "0123456789abcdef" for c in value)
def _record(value):
    if not isinstance(value, dict) or set(value) != _FIELDS: raise CompetitiveApplicationError("malformed application record")
    if any(not isinstance(value[k], str) or not value[k] for k in _FIELDS-{"applied","changed_paths"}): raise CompetitiveApplicationError("invalid application bindings")
    if value["state"] not in {"applying","applied","rolled_back"} or not isinstance(value["applied"], bool) or value["applied"] != (value["state"]=="applied"): raise CompetitiveApplicationError("invalid application state")
    if not _digest(value["approval_digest"]) or not _digest(value["candidate_patch_sha256"]): raise CompetitiveApplicationError("invalid application digest")
    try: payload=json.loads(value["approval_payload"])
    except (TypeError,json.JSONDecodeError) as exc: raise CompetitiveApplicationError("invalid approval payload") from exc
    if not isinstance(payload,dict) or set(payload)!=_PAYLOAD_FIELDS or any(not isinstance(item,str) or not item for item in payload.values()) or _canon(payload)!=value["approval_payload"]: raise CompetitiveApplicationError("approval payload binding mismatch")
    if any(payload[key]!=value[key] for key in ("repository","source_head","candidate_id","candidate_patch_sha256")) or _sha(value["approval_payload"].encode())!=value["approval_digest"]: raise CompetitiveApplicationError("approval binding mismatch")
    paths=value["changed_paths"]
    if not isinstance(paths,list) or not paths or any(not isinstance(p,str) or not p or p.startswith("/") or "\\" in p or any(x in {"",".",".."} for x in p.split("/")) for p in paths): raise CompetitiveApplicationError("invalid paths")
    paths=tuple(paths)
    if paths!=tuple(sorted(paths)) or len(paths)!=len(set(paths)): raise CompetitiveApplicationError("inconsistent paths")
    if len(value["reason"].encode())>512: raise CompetitiveApplicationError("reason too long")
    return CompetitiveApplicationResult(**dict(value,changed_paths=paths))
def _load(path):
    try: value=json.loads(path.read_bytes().decode("utf-8",errors="strict"))
    except (OSError,UnicodeError,json.JSONDecodeError) as exc: raise CompetitiveApplicationError("malformed application ledger") from exc
    if not isinstance(value,dict) or set(value)!={"schema_version","applications"} or isinstance(value["schema_version"],bool) or value["schema_version"]!=_SCHEMA or not isinstance(value["applications"],list): raise CompetitiveApplicationError("invalid application ledger")
    values=[_record(x) for x in value["applications"]]; ids=[x.request_id for x in values]
    if ids!=sorted(ids) or len(ids)!=len(set(ids)): raise CompetitiveApplicationError("invalid application ordering")
    return values
def _publish(directory, values):
    raw=(_canon({"schema_version":_SCHEMA,"applications":[asdict(x) for x in values]})+"\n").encode(); fd=-1; name=None; done=False
    try:
        fd,name=tempfile.mkstemp(prefix=".applications-",suffix=".tmp",dir=directory)
        with os.fdopen(fd,"wb") as stream: fd=-1; stream.write(raw); stream.flush(); os.fsync(stream.fileno())
        os.replace(name,directory/_LEDGER); done=True
        try:
            d=os.open(directory,os.O_RDONLY); os.fsync(d); os.close(d)
        except OSError: pass
    finally:
        if fd>=0: os.close(fd)
        if name and not done:
            try: os.unlink(name)
            except FileNotFoundError: pass
def _get(directory,rid,exclusive=True):
    with (directory/_LOCK).open("a+b" if exclusive else "rb") as lock:
        fcntl.flock(lock.fileno(),fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH)
        values=_load(directory/_LEDGER) if (directory/_LEDGER).exists() else []
    return next((x for x in values if x.request_id==rid),None)
def _put(directory,result):
    with (directory/_LOCK).open("a+b") as lock:
        fcntl.flock(lock.fileno(),fcntl.LOCK_EX); values=_load(directory/_LEDGER) if (directory/_LEDGER).exists() else []
        old=next((x for x in values if x.request_id==result.request_id),None)
        if old==result:return
        if old is None:
            if result.state!="applying":raise CompetitiveApplicationError("application must begin in applying state")
            values.append(result)
        else:
            if any(getattr(old,key)!=getattr(result,key) for key in _IMMUTABLE_FIELDS):raise CompetitiveApplicationError("application transition changes immutable bindings")
            if old.state!="applying" or result.state not in {"applied","rolled_back"}:raise CompetitiveApplicationError("application transition is not monotonic")
            values[values.index(old)]=result
        values.sort(key=lambda x:x.request_id); _publish(directory,values)
def get_competitive_application_result(request_id: str, *, application_dir: Path|None=None):
    if not isinstance(request_id,str) or not request_id: raise CompetitiveApplicationError("invalid request_id")
    directory=_dir(application_dir)
    if not (directory/_LEDGER).exists() and not (directory/_LOCK).exists(): return None
    if not (directory/_LOCK).exists(): raise CompetitiveApplicationError("missing application lock")
    return _get(directory,request_id,False)
def _git(repo,*args):
    try: result=subprocess.run(("git","-C",str(repo),*args),check=False,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
    except OSError as exc: raise CompetitiveApplicationError("Git unavailable") from exc
    if result.returncode: raise CompetitiveApplicationError("Git failed: "+result.stderr.decode(errors="replace").strip())
    return result.stdout
def _files(repo):
    out=[]
    for root,dirs,names in os.walk(repo,followlinks=False):
        dirs[:]=sorted(x for x in dirs if x!=".git")
        for name in sorted(names):
            p=Path(root)/name; s=p.lstat()
            if stat.S_ISREG(s.st_mode): out.append((p.relative_to(repo).as_posix(),p.read_bytes(),stat.S_IMODE(s.st_mode)))
    return tuple(sorted(out))
def _integrity(files,excluded=frozenset()): return _sha(_canon({p:{"sha256":_sha(b),"filesystem_mode":m} for p,b,m in files if p not in excluded}).encode())
def _manifest(files): return _sha(_canon({p:_sha(b) for p,b,_ in files}).encode())
def _status(repo,paths): return _git(repo,"status","--porcelain=v1","-z","--",".",*(f":(top,exclude,literal){p}" for p in paths))
def _classify(repo,tx):
    states=[]
    for item in tx.files:
        p=repo/item.path
        try: s=p.lstat(); data=p.read_bytes()
        except OSError:return "foreign"
        if not stat.S_ISREG(s.st_mode) or p.is_symlink():return "foreign"
        mode=stat.S_IMODE(s.st_mode); pre=mode==item.filesystem_mode and _sha(data)==item.sha256; post=mode==item.expected_filesystem_mode and _sha(data)==item.expected_sha256
        if pre and not post:states.append("pre")
        elif post and not pre:states.append("post")
        elif pre:states.append("pre")
        else:return "foreign"
    return states[0] if len(set(states))==1 else "mixed"
def _unaffected(repo,tx):
    if _git(repo,"rev-parse","HEAD").decode().strip()!=tx.source_head: raise CompetitiveApplicationError("HEAD mismatch")
    files=_files(repo); excluded=frozenset(tx.changed_paths)
    if _integrity(files,excluded)!=tx.unaffected_repository_integrity_sha256 or _status(repo,tx.changed_paths)!=_decode(tx.unaffected_status_base64): raise CompetitiveApplicationError("unaffected repository mismatch")
def _pre(repo,tx):
    _unaffected(repo,tx); files=_files(repo)
    if _classify(repo,tx)!="pre" or _git(repo,"status","--porcelain=v1","-z")!=_decode(tx.repository_status_base64) or _manifest(files)!=tx.repository_manifest_sha256 or _integrity(files)!=tx.repository_integrity_sha256: raise CompetitiveApplicationError("pre-image mismatch")
def _post(repo,tx):
    # Exact post images bind affected paths; HEAD, integrity, and raw status bind the rest.
    _unaffected(repo,tx)
    if _classify(repo,tx)!="post": raise CompetitiveApplicationError("post-image mismatch")
def _result(tx,state,reason): return CompetitiveApplicationResult(tx.request_id,state,state=="applied",tx.approval_digest,tx.approval_payload,tx.repository,tx.source_head,tx.candidate_id,tx.candidate_patch_sha256,tuple(sorted(tx.changed_paths)),reason)
def _claim_ok(claim,tx):
    if claim is None or claim.state!="claimed" or any(getattr(claim,k)!=getattr(tx,k) for k in ("request_id","approval_digest","approval_payload","repository","source_head","baseline_patch_sha256","candidate_id","candidate_patch_sha256")): raise CompetitiveApplicationError("claim mismatch")
def _record_ok(record,tx):
    if record!=_result(tx,record.state,record.reason): raise CompetitiveApplicationError("application record mismatch")
def _apply(repo,tx,directory):
    fd,name=tempfile.mkstemp(prefix=".candidate-",suffix=".patch",dir=directory)
    try:
        with os.fdopen(fd,"wb") as stream: stream.write(tx.candidate_patch.encode()); stream.flush(); os.fsync(stream.fileno())
        _git(repo,"apply","--check","--",name); _git(repo,"apply","--",name)
        for item in tx.files:
            target=repo/item.path; target_stat=target.lstat()
            if not stat.S_ISREG(target_stat.st_mode) or target.is_symlink():raise CompetitiveApplicationError("applied path is not regular")
            target.chmod(item.expected_filesystem_mode)
    finally:
        try: os.unlink(name)
        except FileNotFoundError: pass
def _sync(repo,tx):
    parents=set()
    for item in tx.files:
        p=repo/item.path
        with p.open("rb") as stream: os.fsync(stream.fileno())
        parents.add(p.parent)
    for parent in sorted(parents,key=str):
        try:d=os.open(parent,os.O_RDONLY);os.fsync(d);os.close(d)
        except OSError:pass
def _rollback(repo,tx):
    for item in sorted(tx.files,key=lambda x:x.path):
        target=repo/item.path; parent=target.parent
        try: parent.resolve().relative_to(repo)
        except (ValueError,OSError) as exc: raise CompetitiveApplicationError("unsafe rollback parent") from exc
        fd,name=tempfile.mkstemp(prefix=".rollback-",suffix=".tmp",dir=parent); done=False
        try:
            with os.fdopen(fd,"wb") as stream:stream.write(_decode(item.content_base64));stream.flush();os.fsync(stream.fileno())
            os.chmod(name,item.filesystem_mode);os.replace(name,target);done=True
            try:d=os.open(parent,os.O_RDONLY);os.fsync(d);os.close(d)
            except OSError:pass
        finally:
            if not done:
                try:os.unlink(name)
                except FileNotFoundError:pass
    _pre(repo,tx)
def _finish(repo,tx,directory,state):
    if state=="pre":_apply(repo,tx,directory);_sync(repo,tx);_post(repo,tx)
    elif state=="post":_post(repo,tx)
    else:_rollback(repo,tx);rolled=_result(tx,"rolled_back",f"recovery found {state} state");_put(directory,rolled);raise CompetitiveApplicationError(rolled.reason)
    applied=_result(tx,"applied","approved candidate applied");_put(directory,applied);return applied
def _setup(tx,transaction_dir,application_dir):
    repo=Path(tx.repository).resolve(); directory=_dir(application_dir)
    try:directory.resolve().relative_to(repo)
    except ValueError:pass
    else:raise CompetitiveApplicationError("application state inside repository")
    directory.mkdir(parents=True,exist_ok=True); key=_sha(str(repo).encode()); lock=txmod._directory(transaction_dir)/"repository-locks"/f"{key}.lock";return repo,directory,lock
def apply_competitive_application(evaluation: CompetitiveEvaluationResult,request_id: str,*,transaction_dir: Path|None=None,claim_ledger_dir: Path|None=None,application_dir: Path|None=None)->CompetitiveApplicationResult:
    try:
        try:
            prepared=prepare_competitive_application_transaction(evaluation,request_id,transaction_dir=transaction_dir)
        except Exception as preparation_exc:
            prepared=get_competitive_application_transaction(request_id,transaction_dir=transaction_dir)
            if prepared is None:raise preparation_exc
            repo,directory,lock_path=_setup(prepared,transaction_dir,application_dir)
            with lock_path.open("a+b") as lock:
                fcntl.flock(lock.fileno(),fcntl.LOCK_EX);claim=get_competitive_approval_claim(request_id,ledger_dir=claim_ledger_dir);existing=_get(directory,request_id)
                _claim_ok(claim,prepared)
                if existing is None or existing.state!="applied":raise preparation_exc
                _record_ok(existing,prepared)
                candidate=next((item for item in evaluation.candidates if item.candidate_id==prepared.candidate_id),None)
                if str(evaluation.repository.resolve())!=prepared.repository or evaluation.source_head!=prepared.source_head or candidate is None or candidate.patch!=prepared.candidate_patch or candidate.patch_sha256!=prepared.candidate_patch_sha256:raise CompetitiveApplicationError("replay evaluation mismatch")
                _post(repo,prepared);return existing
        repo,directory,lock_path=_setup(prepared,transaction_dir,application_dir)
        with lock_path.open("a+b") as lock:
            fcntl.flock(lock.fileno(),fcntl.LOCK_EX);tx=get_competitive_application_transaction(request_id,transaction_dir=transaction_dir)
            if tx!=prepared:raise CompetitiveApplicationError("transaction mismatch")
            plan=prepare_competitive_application(evaluation,request_id)
            if any(getattr(plan,k)!=getattr(tx,k) for k in ("request_id","approval_digest","approval_payload","repository","source_head","baseline_patch_sha256","candidate_id","candidate_patch","candidate_patch_sha256","changed_paths")):raise CompetitiveApplicationError("plan mismatch")
            _pre(repo,tx)
            claim=get_competitive_approval_claim(request_id,ledger_dir=claim_ledger_dir)
            if claim is None:claim=claim_competitive_approval(evaluation,request_id,ledger_dir=claim_ledger_dir)
            _claim_ok(claim,tx);existing=_get(directory,request_id);state=_classify(repo,tx)
            if existing is not None:_record_ok(existing,tx)
            if existing:
                if existing.state=="applied":
                    if state!="post":raise CompetitiveApplicationError("applied state drift")
                    _post(repo,tx);return existing
                if existing.state=="rolled_back":
                    if state!="pre":raise CompetitiveApplicationError("rolled back state drift")
                    raise CompetitiveApplicationError("request terminally rolled back")
            else:existing=_result(tx,"applying","application in progress");_put(directory,existing)
            try:return _finish(repo,tx,directory,state)
            except Exception as exc:
                terminal=_get(directory,request_id)
                if terminal is not None and terminal.state=="rolled_back":raise CompetitiveApplicationError(str(exc)) from exc
                try:_rollback(repo,tx);_put(directory,_result(tx,"rolled_back",("application failed: "+str(exc))[:512]))
                except Exception as rollback_exc:raise CompetitiveApplicationError(f"CRITICAL: rollback could not be proven: {rollback_exc}") from exc
                raise CompetitiveApplicationError(str(exc)) from exc
    except CompetitiveApplicationError:raise
    except Exception as exc:raise CompetitiveApplicationError(str(exc)) from exc

def recover_competitive_application(request_id: str,*,transaction_dir: Path|None=None,claim_ledger_dir: Path|None=None,application_dir: Path|None=None)->CompetitiveApplicationResult:
    try:
        tx=get_competitive_application_transaction(request_id,transaction_dir=transaction_dir)
        if tx is None:raise CompetitiveApplicationError("transaction missing")
        repo,directory,lock_path=_setup(tx,transaction_dir,application_dir)
        with lock_path.open("a+b") as lock:
            fcntl.flock(lock.fileno(),fcntl.LOCK_EX);current=get_competitive_application_transaction(request_id,transaction_dir=transaction_dir)
            if current!=tx:raise CompetitiveApplicationError("transaction mismatch")
            claim=get_competitive_approval_claim(request_id,ledger_dir=claim_ledger_dir);_claim_ok(claim,tx);_unaffected(repo,tx)
            existing=_get(directory,request_id);state=_classify(repo,tx)
            if existing is None:
                if state!="pre":raise CompetitiveApplicationError("claim-only recovery not pre")
                _pre(repo,tx);existing=_result(tx,"applying","application in progress");_put(directory,existing)
            else:_record_ok(existing,tx)
            if existing.state=="applied":
                if state!="post":raise CompetitiveApplicationError("applied state drift")
                _post(repo,tx);return existing
            if existing.state=="rolled_back":
                if state!="pre":raise CompetitiveApplicationError("rolled back state drift")
                _pre(repo,tx);return existing
            try:return _finish(repo,tx,directory,state)
            except Exception as exc:
                terminal=_get(directory,request_id)
                if terminal is not None and terminal.state=="rolled_back":raise CompetitiveApplicationError(str(exc)) from exc
                try:_rollback(repo,tx);_put(directory,_result(tx,"rolled_back",("application failed: "+str(exc).encode("ascii",errors="replace").decode())[:512]))
                except Exception as rollback_exc:raise CompetitiveApplicationError(f"CRITICAL: rollback could not be proven: {rollback_exc}") from exc
                raise CompetitiveApplicationError(str(exc)) from exc
    except CompetitiveApplicationError:raise
    except Exception as exc:raise CompetitiveApplicationError(str(exc)) from exc
