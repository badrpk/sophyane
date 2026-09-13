from dataclasses import replace
import sys
import pytest


def passing_verification():
    from sophyane.rsi.models import CommandResult, VerificationResult
    command = ('python', 'check.py')
    red = CommandResult(command, 1, 'AssertionError: RSI_WEAKNESS_wrong_value')
    green = CommandResult(command, 0, '')
    return VerificationResult(red=red, green=(green,), expected_failure='RSI_WEAKNESS_wrong_value',
        targeted=(green,), subsystem=(green,), full_regression=(green,), static_checks=(green,),
        authority=True, isolation=True, benchmark=True, protected_metrics=True)


@pytest.mark.parametrize('gate', ['red','green','targeted','subsystem','full_regression',
                                 'static_checks','authority','isolation','benchmark','protected_metrics'])
def test_every_missing_mandatory_gate_vetoes(gate):
    from sophyane.rsi.verification import gates
    verification = passing_verification()
    assert all(gates(verification).values())
    assert not all(gates(replace(verification, **{gate: None})).values())


def test_green_must_match_red_command():
    from sophyane.rsi.models import CommandResult
    from sophyane.rsi.verification import gates
    result = replace(passing_verification(), green=(CommandResult(('true',),0,'LLM says approved'),))
    assert not gates(result)['red_to_green_gate']


def test_candidate_src_import_and_bounded_process(tmp_path):
    from sophyane.rsi.verification import run_command
    (tmp_path / 'src').mkdir()
    (tmp_path / 'src' / 'unique_rsi.py').write_text('VALUE = 73')
    result = run_command((sys.executable, '-c', 'import unique_rsi; print(unique_rsi.VALUE)'), tmp_path, timeout=5)
    assert result.exit_code == 0 and result.output.strip() == '73'
    result = run_command((sys.executable, '-c', 'import time; time.sleep(60)'), tmp_path, timeout=.1)
    assert result.exit_code == 124
    from sophyane.rsi.coding_provider import CodingCancelled
    with pytest.raises(CodingCancelled):
        run_command((sys.executable, '-c', 'raise Exception()'), tmp_path, cancelled=lambda: True)
