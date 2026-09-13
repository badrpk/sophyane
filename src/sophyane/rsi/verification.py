"""Host-selected fresh-process verification and fail-closed mandatory gates."""
import os
import re
from pathlib import Path
import signal
import subprocess
import time
import tempfile
from .sandbox import sandbox_command
from .coding_provider import CodingCancelled
from .models import CommandResult


def run_command(command, cwd, *, timeout=300, cancelled=lambda: False):
    if not command or isinstance(command, str) or timeout <= 0:
        raise ValueError('Verification requires argv and a positive timeout')
    if cancelled():
        raise CodingCancelled('Verification cancelled')
    cwd = Path(cwd).resolve()
    env = dict({key: value for key, value in os.environ.items()
                if key in ('PATH', 'LANG', 'LC_ALL', 'LD_LIBRARY_PATH', 'PREFIX', 'SYSTEMROOT')},
               PYTHONPATH=str(cwd / 'src'), PYTHONDONTWRITEBYTECODE='1',
               PYTEST_ADDOPTS='-p no:cacheprovider', PYTEST_DISABLE_PLUGIN_AUTOLOAD='1')
    start = time.monotonic()
    with tempfile.TemporaryDirectory(prefix='sophyane-rsi-command-') as scratch:
        env.update(HOME=scratch, TMPDIR=scratch, XDG_CACHE_HOME=scratch)
        return _execute(command, cwd, env, timeout, cancelled, start, scratch)


def _execute(command, cwd, env, timeout, cancelled, start, scratch):
    argv = sandbox_command(command, cwd, scratch)
    with subprocess.Popen(argv, cwd=cwd, env=env, text=True, stdout=subprocess.PIPE,
                          stderr=subprocess.STDOUT, start_new_session=True) as process:
        try:
            while True:
                if cancelled():
                    raise CodingCancelled('Verification cancelled')
                remaining = timeout - (time.monotonic() - start)
                if remaining <= 0:
                    os.killpg(process.pid, signal.SIGKILL)
                    output, _ = process.communicate()
                    return CommandResult(tuple(command), 124, output + '\nVerification timeout', str(cwd))
                try:
                    output, _ = process.communicate(timeout=min(.1, remaining))
                    return CommandResult(tuple(command), process.returncode, output, str(cwd))
                except subprocess.TimeoutExpired:
                    continue
        except BaseException:
            if process.poll() is None:
                os.killpg(process.pid, signal.SIGKILL)
            process.communicate()
            raise


def confirm_red(result, expected_failure):
    return bool(result and result.exit_code == 1 and expected_failure and
                re.search(r'(?m)^(?:E\s+)?AssertionError:\s*' + re.escape(expected_failure) + r'(?:\s|$)', result.output) and
                not any(int(count) > 1 for count in re.findall(r'(\d+) failed', result.output)) and
                not any(marker in result.output for marker in
                        ('SyntaxError', 'ImportError', 'ModuleNotFoundError', 'IndentationError',
                         'ERROR collecting', 'INTERNALERROR')))


def passed(results):
    return bool(results) and all(result.exit_code == 0 for result in results)


def gates(result):
    return {
        'red_to_green_gate': bool(confirm_red(result.red, result.expected_failure) and
            passed(result.green) and any(x.command == result.red.command for x in result.green)),
        'targeted_tests_gate': passed(result.targeted),
        'subsystem_regression_gate': passed(result.subsystem),
        'full_regression_gate': passed(result.full_regression),
        'git_diff_check_gate': passed(result.static_checks),
        'authority_gate': result.authority is True,
        'isolation_gate': result.isolation is True,
        'benchmark_gate': result.benchmark is True,
        'protected_metrics_gate': result.protected_metrics is True,
    }
