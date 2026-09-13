import os
from pathlib import Path
import subprocess
import pytest


def git(path, *args):
    return subprocess.check_output(['git', '-C', str(path), *args], text=True).strip()


@pytest.fixture
def repo(tmp_path):
    path = tmp_path / 'baseline'; path.mkdir()
    git(path, 'init', '-q')
    git(path, 'config', 'user.name', 'RSI fixture')
    git(path, 'config', 'user.email', 'rsi@example.invalid')
    (path / 'value.py').write_text('VALUE = 1\n')
    (path / 'check.py').write_text('from value import VALUE\nassert VALUE == 2, "RSI_WEAKNESS_wrong_value"\n')
    (path / 'regression.py').write_text('from value import VALUE\nassert VALUE > 0\n')
    git(path, 'add', '.')
    git(path, 'commit', '-qm', 'verified fixture A')
    return path


@pytest.fixture(autouse=True)
def trusted_fixture_command_execution(request, monkeypatch):
    """Controller semantics use authored fixture scripts, never generated live code.

    OS enforcement is tested separately. Android cannot run Bubblewrap; this
    patch is confined to tests and never provides a production escape hatch.
    """
    if request.node.path.name != 'test_execution_sandbox.py':
        monkeypatch.setattr('sophyane.rsi.verification.sandbox_command',
                            lambda command, cwd, scratch: list(command))
