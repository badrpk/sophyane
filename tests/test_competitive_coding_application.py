from __future__ import annotations
import hashlib, json, subprocess
from dataclasses import FrozenInstanceError, asdict, replace
from pathlib import Path
import pytest
import sophyane.competitive_coding_application as application
import sophyane.competitive_coding_approval as approval
from sophyane.competitive_coding_phase2 import CompetitiveEvaluationCandidate, CompetitiveEvaluationResult
from sophyane.evolution.trusted_supplemental_executor import TrustedSupplementalEvidence
from sophyane.scoped_candidate_diff import candidate_diff_for_paths

def git(repo,*args):return subprocess.run(("git","-C",str(repo),*args),check=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE).stdout
def digest(data):return hashlib.sha256(data).hexdigest()
def setup(tmp_path,monkeypatch,decision=True):
    repo=tmp_path/"repo";repo.mkdir();git(repo,"init");git(repo,"config","user.email","x@y.invalid");git(repo,"config","user.name","T")
    (repo/"app.py").write_bytes(b"VALUE = 1\n");(repo/"other.txt").write_bytes(b"other\n");git(repo,"add",".");git(repo,"commit","-m","base")
    original=(repo/"app.py").read_bytes();(repo/"app.py").write_bytes(b"VALUE = 2\n");patch=git(repo,"diff","--binary","HEAD","--","app.py").decode()+"\n";(repo/"app.py").write_bytes(original)
    ev=TrustedSupplementalEvidence("targeted","c1","judge","tests/red_queen/test_targeted_supplemental.py",True,True,0,False,.1,"ok","",None)
    candidate=CompetitiveEvaluationCandidate("only",True,"","PASS","ok",("app.py",),("tests",),True,"PASS",True,(ev,),patch,digest(patch.encode()),git(repo,"rev-parse","HEAD").decode().strip())
    baseline=candidate_diff_for_paths(repo,("app.py",))
    value=CompetitiveEvaluationResult("repair",repo.resolve(),"sophyane",("app.py",),baseline,None,(candidate,),"fail_closed","trusted_candidate_ranking_and_approval",None,git(repo,"rev-parse","HEAD").decode().strip(),digest(baseline.encode()))
    hitl=tmp_path/"hitl";monkeypatch.setattr(approval.hitl,"HITL_DIR",hitl);monkeypatch.setattr(approval.hitl,"QUEUE",hitl/"queue.json")
    request=approval.request_competitive_approval(value)
    if decision is not None:approval.hitl.resolve(request.request_id,approve=decision)
    return repo,value,request,tmp_path/"transactions",tmp_path/"claims",tmp_path/"applications"

def test_apply_is_exact_and_idempotent(tmp_path,monkeypatch):
    repo,value,request,transactions,claims,applications=setup(tmp_path,monkeypatch);head=git(repo,"rev-parse","HEAD");other=(repo/"other.txt").read_bytes()
    result=application.apply_competitive_application(value,request.request_id,transaction_dir=transactions,claim_ledger_dir=claims,application_dir=applications)
    assert result.state=="applied" and result.applied and (repo/"app.py").read_bytes()==b"VALUE = 2\n"
    assert git(repo,"rev-parse","HEAD")==head and git(repo,"diff","--cached")==b"" and (repo/"other.txt").read_bytes()==other
    before=((claims/"claims.json").read_bytes(),(transactions/"transactions.json").read_bytes(),(applications/"applications.json").read_bytes())
    assert application.apply_competitive_application(value,request.request_id,transaction_dir=transactions,claim_ledger_dir=claims,application_dir=applications)==result
    assert before==((claims/"claims.json").read_bytes(),(transactions/"transactions.json").read_bytes(),(applications/"applications.json").read_bytes())
    assert application.get_competitive_application_result(request.request_id,application_dir=applications)==result
    assert not list(tmp_path.rglob(".candidate-*.patch"))

def test_check_failure_rolls_back(tmp_path,monkeypatch):
    repo,value,request,transactions,claims,applications=setup(tmp_path,monkeypatch);original=application._git
    def failing(repository,*args):
        if args[:2]==("apply","--check"):raise application.CompetitiveApplicationError("forced")
        return original(repository,*args)
    monkeypatch.setattr(application,"_git",failing)
    with pytest.raises(application.CompetitiveApplicationError):application.apply_competitive_application(value,request.request_id,transaction_dir=transactions,claim_ledger_dir=claims,application_dir=applications)
    assert (repo/"app.py").read_bytes()==b"VALUE = 1\n"
    assert application.get_competitive_application_result(request.request_id,application_dir=applications).state=="rolled_back"

def test_recovery_after_intent(tmp_path,monkeypatch):
    repo,value,request,transactions,claims,applications=setup(tmp_path,monkeypatch)
    class Crash(BaseException):pass
    original=application._apply
    monkeypatch.setattr(application,"_apply",lambda *args:(_ for _ in ()).throw(Crash()))
    with pytest.raises(Crash):application.apply_competitive_application(value,request.request_id,transaction_dir=transactions,claim_ledger_dir=claims,application_dir=applications)
    monkeypatch.setattr(application,"_apply",original)
    result=application.recover_competitive_application(request.request_id,transaction_dir=transactions,claim_ledger_dir=claims,application_dir=applications)
    assert result.state=="applied" and (repo/"app.py").read_bytes()==b"VALUE = 2\n"

def test_malformed_application_ledger_is_not_rewritten(tmp_path):
    directory=tmp_path/"applications";directory.mkdir();(directory/"applications.lock").touch();ledger=directory/"applications.json";ledger.write_bytes(b"bad")
    before=ledger.read_bytes()
    with pytest.raises(application.CompetitiveApplicationError):application.get_competitive_application_result("x",application_dir=directory)
    assert ledger.read_bytes()==before

def test_source_excludes_forbidden_git_mutations():
    source=Path(application.__file__).read_text()
    for word in ("checkout","reset","restore","clean","cherry-pick","merge","rebase","shell=True"):
        assert word not in source

@pytest.mark.parametrize("decision", [None, False])
def test_pending_and_denied_never_prepare_claim_or_apply(tmp_path, monkeypatch, decision):
    repo,value,request,transactions,claims,applications=setup(tmp_path,monkeypatch,decision)
    before=(repo/"app.py").read_bytes()
    with pytest.raises(application.CompetitiveApplicationError):
        application.apply_competitive_application(value,request.request_id,transaction_dir=transactions,claim_ledger_dir=claims,application_dir=applications)
    assert (repo/"app.py").read_bytes()==before
    assert not (transactions/"transactions.json").exists()
    assert not (claims/"claims.json").exists()
    assert not (applications/"applications.json").exists()

@pytest.mark.parametrize("terminal", ["applied", "rolled_back"])
def test_put_enforces_monotonic_transitions(tmp_path,monkeypatch,terminal):
    _,value,request,transactions,_,applications=setup(tmp_path,monkeypatch)
    tx=application.prepare_competitive_application_transaction(value,request.request_id,transaction_dir=transactions)
    applications.mkdir();applying=application._result(tx,"applying","application in progress")
    application._put(applications,applying);before=(applications/"applications.json").read_bytes()
    application._put(applications,applying);assert (applications/"applications.json").read_bytes()==before
    end=application._result(tx,terminal,"done");application._put(applications,end);terminal_bytes=(applications/"applications.json").read_bytes()
    for invalid in (applying,application._result(tx,"applied","other"),application._result(tx,"rolled_back","other")):
        if invalid==end:continue
        with pytest.raises(application.CompetitiveApplicationError):application._put(applications,invalid)
        assert (applications/"applications.json").read_bytes()==terminal_bytes
    with pytest.raises(application.CompetitiveApplicationError):application._put(applications,replace(end,candidate_id="changed"))
    assert (applications/"applications.json").read_bytes()==terminal_bytes

def test_put_rejects_terminal_without_intent(tmp_path,monkeypatch):
    _,value,request,transactions,_,applications=setup(tmp_path,monkeypatch)
    tx=application.prepare_competitive_application_transaction(value,request.request_id,transaction_dir=transactions);applications.mkdir()
    for state in ("applied","rolled_back"):
        with pytest.raises(application.CompetitiveApplicationError):application._put(applications,application._result(tx,state,"bad"))
    assert not (applications/"applications.json").exists()

@pytest.mark.parametrize("mutation", ["missing","extra","empty","binding","digest","noncanonical"])
def test_payload_tampering_fails_without_rewrite(tmp_path,monkeypatch,mutation):
    _,value,request,transactions,claims,applications=setup(tmp_path,monkeypatch)
    result=application.apply_competitive_application(value,request.request_id,transaction_dir=transactions,claim_ledger_dir=claims,application_dir=applications)
    ledger=applications/"applications.json";data=json.loads(ledger.read_text());record=data["applications"][0];payload=json.loads(record["approval_payload"])
    if mutation=="missing":payload.pop("objective")
    elif mutation=="extra":payload["extra"]="x"
    elif mutation=="empty":payload["objective"]=""
    elif mutation=="binding":payload["candidate_id"]="other"
    elif mutation=="digest":record["approval_digest"]="0"*64
    else:
        record["approval_payload"]=json.dumps(payload);payload=None
    if payload is not None:
        record["approval_payload"]=json.dumps(payload,sort_keys=True,separators=(",",":"),ensure_ascii=False)
        if mutation!="digest":record["approval_digest"]=hashlib.sha256(record["approval_payload"].encode()).hexdigest()
    ledger.write_text(json.dumps(data,sort_keys=True,separators=(",",":")))
    before=ledger.read_bytes()
    with pytest.raises(application.CompetitiveApplicationError):application.get_competitive_application_result(request.request_id,application_dir=applications)
    assert ledger.read_bytes()==before and result.state=="applied"

def test_retrieval_absent_is_noncreating_and_result_frozen(tmp_path,monkeypatch):
    directory=tmp_path/"absent";assert application.get_competitive_application_result("x",application_dir=directory) is None and not directory.exists()
    _,value,request,transactions,claims,applications=setup(tmp_path,monkeypatch)
    result=application.apply_competitive_application(value,request.request_id,transaction_dir=transactions,claim_ledger_dir=claims,application_dir=applications);before=(applications/"applications.json").read_bytes()
    with pytest.raises(FrozenInstanceError):result.state="other"
    assert application.get_competitive_application_result(request.request_id,application_dir=applications)==result
    assert (applications/"applications.json").read_bytes()==before

def test_applied_drift_fails_without_ledger_rewrite(tmp_path,monkeypatch):
    repo,value,request,transactions,claims,applications=setup(tmp_path,monkeypatch)
    application.apply_competitive_application(value,request.request_id,transaction_dir=transactions,claim_ledger_dir=claims,application_dir=applications);ledger=applications/"applications.json";before=ledger.read_bytes()
    (repo/"app.py").write_bytes(b"foreign\n")
    with pytest.raises(application.CompetitiveApplicationError):application.recover_competitive_application(request.request_id,transaction_dir=transactions,claim_ledger_dir=claims,application_dir=applications)
    assert ledger.read_bytes()==before
