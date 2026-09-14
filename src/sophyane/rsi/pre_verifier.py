"""Independent deterministic candidate evidence, bound to exact bytes."""
from dataclasses import dataclass
from .campaign import RedStatus
from .controller import protects_verification
from .verification import confirm_red, passed
from .experiment import ExperimentPlan as VerificationManifest

@dataclass(frozen=True)
class VerificationEvidence:
    accepted: bool = False
    fingerprint: str = ''
    reasons: tuple[str, ...] = ()
    focused_green: bool = False
    holdout_green: bool = False
    regression_green: bool = False
    changed_files: tuple[str, ...] = ()
    production_files: tuple[str, ...] = ()
    red: str = 'RED_UNAVAILABLE'
    runs: tuple = ()

class DeterministicPreVerifier:
    def __init__(self, runner):
        self.runner = runner
    def verify(self, candidate, manifest, red):
        diff = candidate.diff()
        reasons = []
        commands = manifest.focused + manifest.holdout + manifest.regression
        production = tuple(name for name in diff.changed_files if name.endswith('.py')
                           and not name.startswith('tests/') and not name.split('/')[-1].startswith('test_'))
        if not diff.changed_files or not set(diff.changed_files) <= manifest.allowed_paths:
            reasons.append('scope')
        if not protects_verification(diff.changed_files, commands):
            reasons.append('protected_paths')
        if not production:
            reasons.append('test_only_gaming')
        if diff.growth > 16384:
            reasons.append('code_growth')
        genuine = (red.red_status is RedStatus.RED_CONFIRMED and len(red.runs) == 2
                   and all(confirm_red(r, manifest.expected_failure) and r.command == manifest.focused[0]
                           for r in red.runs))
        if not genuine:
            reasons.append('genuine_red')
        if reasons:
            return VerificationEvidence(False, diff.fingerprint, tuple(reasons),
                changed_files=diff.changed_files, production_files=production, red=red.red_status.value)
        focused = self.runner.checks(manifest.focused, candidate.path, manifest.timeout)
        holdout = self.runner.checks(manifest.holdout, candidate.path, manifest.timeout)
        regression = self.runner.checks(manifest.regression, candidate.path, manifest.timeout)
        for name, good in (('focused_green', passed(focused)), ('holdout', passed(holdout)),
                           ('regression', passed(regression)),
                           ('fingerprint_changed', candidate.diff().fingerprint == diff.fingerprint)):
            if not good:
                reasons.append(name)
        return VerificationEvidence(not reasons, diff.fingerprint, tuple(reasons),
            passed(focused), passed(holdout), passed(regression), diff.changed_files,
            production, red.red_status.value, focused + holdout + regression)
