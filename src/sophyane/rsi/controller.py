"""One bounded automatic RSI iteration under trusted host verification policy."""
from dataclasses import asdict, dataclass
import json
from pathlib import Path
import time
import uuid

from .authority import Operation, require
from .baseline import assert_baseline, capture, git
from .benchmark import compare
from .candidate import Candidate
from .coding_provider import CodingCancelled
from .models import IterationResult, IterationState, VerificationResult
from .promotion import promote
from .rollback import recover_pending, transaction_lock
from .verification import confirm_red, gates, passed, run_command
from .weakness import detect


def protects_verification(editable_paths, commands):
    protected = set()
    for command in commands:
        for index, token in enumerate(command):
            protected.add(Path(token.split('::')[0]).as_posix())
            if index and command[index - 1] == '-m':
                protected.add(token.replace('.', '/') + '.py')
    for name in editable_paths:
        path = Path(name)
        normalized = path.as_posix()
        if (path.is_absolute() or '..' in path.parts or normalized in protected or
            any(part.casefold() in ('.git', 'tests', 'test', '.github') for part in path.parts) or
            path.name in ('conftest.py', 'pytest.ini', 'pyproject.toml', 'setup.cfg', 'tox.ini') or
            normalized.startswith(('src/sophyane/rsi/', 'src/sophyane/providers/')) or
            normalized == 'src/sophyane/intelligence_authority.py'):
            return False
    return True


@dataclass(frozen=True)
class Policy:
    targeted: tuple[tuple[str, ...], ...]
    subsystem: tuple[tuple[str, ...], ...]
    full_regression: tuple[tuple[str, ...], ...]
    smoke: tuple[tuple[str, ...], ...]
    benchmark_command: tuple[str, ...]
    expected_failure: str
    editable_paths: frozenset[str]
    max_repair_rounds: int = 2
    max_lifecycle_seconds: float = 1800
    command_timeout: float = 300

    def __post_init__(self):
        if self.max_repair_rounds < 1 or self.max_lifecycle_seconds <= 0 or self.command_timeout <= 0:
            raise ValueError('RSI requires positive bounded limits')
        if not all((self.targeted, self.subsystem, self.full_regression, self.smoke,
                    self.benchmark_command, self.expected_failure, self.editable_paths)):
            raise ValueError('Mandatory verification policy is incomplete')
        commands = (*self.targeted, *self.subsystem, *self.full_regression, *self.smoke, self.benchmark_command)
        if not protects_verification(self.editable_paths, commands):
            raise ValueError('Verification command files cannot be candidate-editable')


class Controller:
    """Host entry point. Providers return proposals, never policy or gate values.

    No background loop, live provider initialization, or repository mutation on
    construction. Every invocation creates at most one detached candidate.
    """
    def __init__(self, repository, candidate_root, router, journal, policy, *, cancelled=lambda: False):
        self.repository = Path(repository).resolve()
        self.candidate_root = Path(candidate_root).resolve()
        self.router, self.journal, self.policy, self.cancelled = router, journal, policy, cancelled
        router.store.assert_external(self.repository)
        router.store.assert_external(self.candidate_root)

    def run_once(self, weakness, *, parent_iteration=None):
        common = Path(git(self.repository, 'rev-parse', '--git-common-dir'))
        if not common.is_absolute():
            common = self.repository / common
        with transaction_lock(common.resolve(), name='sophyane-rsi-lifecycle.lock'):
            if not self.cancelled():
                recover_pending(self.journal, common.resolve())
            return self._run_once(weakness, parent_iteration=parent_iteration)

    def _run_once(self, weakness, *, parent_iteration=None):
        identifier = uuid.uuid4().hex
        started = time.monotonic()
        candidate = None
        evidence = {'parent_iteration': parent_iteration, 'weakness': weakness}
        # Journal authority is the host's coding policy, not a generated opinion.
        actor = 'codex_cli'

        def emit(state, **values):
            evidence.update(values)
            self.journal.append(actor, identifier, state, evidence)
            return IterationResult(identifier, IterationState(state), dict(evidence))

        def stopped():
            return self.cancelled() or time.monotonic() - started >= self.policy.max_lifecycle_seconds

        def check():
            if stopped():
                raise CodingCancelled('Iteration cancelled or lifecycle deadline reached')

        def run(command, path):
            check()
            remaining = self.policy.max_lifecycle_seconds - (time.monotonic() - started)
            return run_command(command, path, timeout=min(self.policy.command_timeout, remaining), cancelled=stopped)

        def measure(path):
            result = run(self.policy.benchmark_command, path)
            if result.exit_code != 0:
                raise ValueError('Benchmark command failed')
            values = json.loads(result.output)
            if not isinstance(values, dict):
                raise ValueError('Benchmark must emit a JSON metric object')
            return values

        try:
            if detect(weakness) is None:
                return emit('NO_ACTION')
            if not protects_verification(self.policy.editable_paths, weakness.verification_commands):
                raise ValueError('RED command files cannot be candidate-editable')
            check()
            assert_baseline(self.repository, weakness.baseline_commit)
            emit('DETECTED', baseline_commit=weakness.baseline_commit)
            baseline_tests = tuple(run(c, self.repository) for c in self.policy.full_regression)
            if not passed(baseline_tests):
                return emit('REJECTED', baseline_tests=baseline_tests, reason='Baseline regression failed')
            baseline_metrics = measure(self.repository)
            if baseline_metrics.get(weakness.target_metric) != weakness.baseline_value:
                return emit('REJECTED', reason='Recorded weakness baseline value is stale')
            baseline = capture(self.repository, weakness.baseline_commit, baseline_metrics,
                               {str(i): asdict(value) for i, value in enumerate(baseline_tests)})
            emit('BASELINED', baseline=baseline, baseline_metrics=baseline_metrics)
            check()
            candidate = Candidate.create(baseline, self.candidate_root)
            emit('CANDIDATE_CREATED', candidate=asdict(candidate.record))
            red = run(weakness.verification_commands[0], candidate.path)
            if not confirm_red(red, self.policy.expected_failure):
                return emit('REJECTED', red=red, reason='Intended RED was not demonstrated')
            emit('RED_CONFIRMED', red=red)
            failovers = []
            for repair_round in range(self.policy.max_repair_rounds):
                check()
                emit('MODIFYING', repair_round=repair_round + 1)
                context = {name: (candidate.path / name).read_text() for name in self.policy.editable_paths
                           if (candidate.path / name).is_file()}
                prompt = json.dumps({'weakness': asdict(weakness), 'red': asdict(red),
                                     'editable_files': context, 'previous_green': evidence.get('green', ())}, default=str)
                reply = self.router.request(prompt, candidate.path, cancelled=stopped,
                    timeout=min(self.policy.command_timeout, self.policy.max_lifecycle_seconds - (time.monotonic() - started)))
                failovers.extend(reply.failovers)
                evidence['failovers'] = failovers
                if reply.status == 'DEFERRED_NO_CODING_PROVIDER':
                    return emit(reply.status)
                require(reply.provider, Operation.SOPHYANE_SOURCE_MUTATION)
                actor = reply.provider
                candidate.apply(reply.provider, reply.files, self.policy.editable_paths)
                verified_tree = candidate.fingerprint()
                check()
                emit('VERIFYING', coding_provider=reply.provider)
                green = tuple(run(c, candidate.path) for c in weakness.verification_commands)
                evidence['green'] = green
                if passed(green):
                    break
            else:
                return emit('REJECTED', reason='Coding repair round limit exhausted')
            targeted = tuple(run(c, candidate.path) for c in self.policy.targeted)
            subsystem = tuple(run(c, candidate.path) for c in self.policy.subsystem)
            full = tuple(run(c, candidate.path) for c in self.policy.full_regression)
            static = (run(('git', 'diff', '--check'), candidate.path),)
            candidate.assert_isolated()
            metrics = measure(candidate.path)
            if candidate.fingerprint() != verified_tree:
                raise PermissionError('Candidate changed during verification or benchmark')
            decision = compare(weakness, baseline.metrics, metrics)
            verification = VerificationResult(red, green, self.policy.expected_failure,
                targeted, subsystem, full, static, True, True, decision.promote, decision.promote)
            evidence.update(verification=verification, candidate_metrics=metrics, promotion_decision=decision)
            if not all(gates(verification).values()):
                return emit('REJECTED', reason='Mandatory deterministic gate failed')
            check()
            commit = candidate.seal()
            emit('PROMOTION_READY', candidate_commit=commit)
            result = promote(baseline, candidate, weakness, verification, metrics, self.journal, identifier,
                smoke=self.policy.smoke, failovers=failovers, parent_iteration=parent_iteration,
                cancelled=stopped, timeout=min(self.policy.command_timeout,
                    self.policy.max_lifecycle_seconds - (time.monotonic() - started)))
            return emit(result.state, checkpoint=result.checkpoint, post_promotion_smoke=result.smoke)
        except CodingCancelled as error:
            return emit('CANCELLED', reason=str(error))
        except BaseException as error:
            emit('REJECTED', reason=f'{type(error).__name__}: {error}')
            raise
        finally:
            if candidate is not None:
                candidate.cleanup()
