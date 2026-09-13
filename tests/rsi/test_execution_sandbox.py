import sys
import pytest


def test_execution_fails_closed_without_os_sandbox(tmp_path,monkeypatch):
    from sophyane.rsi import verification
    from sophyane.rsi.sandbox import SandboxUnavailable
    monkeypatch.setattr('sophyane.rsi.sandbox.shutil.which',lambda name: None)
    with pytest.raises(SandboxUnavailable):
        verification.run_command((sys.executable,'-c','print("must not run")'),tmp_path)


def test_sandbox_command_mounts_host_readonly(tmp_path,monkeypatch):
    from sophyane.rsi.sandbox import sandbox_command
    monkeypatch.setattr('sophyane.rsi.sandbox.shutil.which',lambda name: '/usr/bin/bwrap')
    command = sandbox_command(('python','check.py'),tmp_path,tmp_path/'scratch')
    assert command[:5] == ['/usr/bin/bwrap','--die-with-parent','--unshare-all','--ro-bind','/']
    assert '--bind' not in command  # no writable host filesystem mount
    assert command[-2:] == ['python','check.py']


def test_real_sandbox_prevents_outside_write_if_available(tmp_path):
    import shutil
    if not shutil.which('bwrap'):
        pytest.skip('No Bubblewrap executable on host')
    from sophyane.rsi.verification import run_command
    outside=tmp_path/'baseline'; outside.write_text('A')
    result=run_command((sys.executable,'-c',f'from pathlib import Path; Path({str(outside)!r}).write_text("attack")'),tmp_path)
    assert result.exit_code != 0
    assert outside.read_text() == 'A'
