"""Record only reproducible clean Git baselines; never snapshot arbitrary dirt."""
import os
from pathlib import Path
import subprocess
from .authority import CODING_PROVIDER_ORDER
from .models import BaselineRecord


def git(path, *args, input=None):
    env = {k: v for k, v in os.environ.items() if not k.startswith('GIT_')}
    env.update(GIT_TERMINAL_PROMPT='0', GIT_CONFIG_NOSYSTEM='1',
               GIT_AUTHOR_NAME='Sophyane RSI', GIT_AUTHOR_EMAIL='rsi@localhost',
               GIT_COMMITTER_NAME='Sophyane RSI', GIT_COMMITTER_EMAIL='rsi@localhost')
    result = subprocess.run(['git', '-c', 'core.hooksPath=/dev/null', '-C', str(path), *args],
                            input=input, text=True, capture_output=True, env=env, timeout=30)
    if result.returncode:
        raise RuntimeError(f'Git {args[0]} failed: {result.stderr.strip()}')
    return result.stdout.strip()


def assert_baseline(path, commit):
    path = Path(path).resolve()
    if Path(git(path, 'rev-parse', '--show-toplevel')).resolve() != path:
        raise ValueError('Baseline must be the repository root')
    if git(path, 'rev-parse', 'HEAD') != commit:
        raise ValueError('Baseline HEAD differs from requested commit')
    if git(path, 'status', '--porcelain', '--untracked-files=all'):
        raise ValueError('Dirty repository cannot be a verified baseline')


def capture(path, commit, metrics, tests):
    path = Path(path).resolve()
    assert_baseline(path, commit)
    if not tests or any(item.get('exit_code') != 0 for item in tests.values()):
        raise ValueError('Baseline needs passing regression evidence')
    common = Path(git(path, 'rev-parse', '--git-common-dir'))
    if not common.is_absolute():
        common = path / common
    return BaselineRecord(commit, str(path), str(common.resolve()), True, 'clean',
                          dict(metrics), tests, CODING_PROVIDER_ORDER)
