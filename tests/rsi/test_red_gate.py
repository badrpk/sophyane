import sys
import pytest


@pytest.mark.parametrize('exit_code, output, expected', [
    (1, 'AssertionError: RSI_WEAKNESS_wrong_value', True),
    (0, 'RSI_WEAKNESS_wrong_value', False),
    (1, 'SyntaxError RSI_WEAKNESS_wrong_value', False),
    (1, 'ModuleNotFoundError RSI_WEAKNESS_wrong_value', False),
    (1, 'ImportError RSI_WEAKNESS_wrong_value', False),
    (1, 'FAILED unrelated_test', False),
    (2, 'AssertionError: RSI_WEAKNESS_wrong_value', False),
])
def test_red_requires_intended_failure(exit_code, output, expected):
    from sophyane.rsi.models import CommandResult
    from sophyane.rsi.verification import confirm_red
    result = CommandResult(('python', 'check.py'), exit_code, output)
    assert confirm_red(result, 'RSI_WEAKNESS_wrong_value') is expected


def test_real_red_to_green_uses_same_fresh_command(repo):
    from sophyane.rsi.verification import run_command, confirm_red
    command = (sys.executable, 'check.py')
    red = run_command(command, repo, timeout=5)
    assert confirm_red(red, 'RSI_WEAKNESS_wrong_value')
    assert red.digest
    (repo / 'value.py').write_text('VALUE = 2\n')
    green = run_command(command, repo, timeout=5)
    assert green.exit_code == 0
    assert not (repo / '__pycache__').exists()


@pytest.mark.parametrize('output', [
    'AssertionError: RSI_WEAKNESS_wrong_value\n2 failed, 1 passed',
    'assert x, "RSI_WEAKNESS_wrong_value"\nAssertionError: unrelated failure',
])
def test_unrelated_suite_noise_or_source_text_is_not_red(output):
    from sophyane.rsi.models import CommandResult
    from sophyane.rsi.verification import confirm_red
    assert not confirm_red(CommandResult(('python','check.py'),1,output),'RSI_WEAKNESS_wrong_value')
