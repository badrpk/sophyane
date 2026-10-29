"""Bounded autonomous RSI stages under host-owned policy and evidence."""
from dataclasses import dataclass, field, asdict
import time
from .resource_governor import ResourceDecision
from .opportunity_scheduler import OpportunityScheduler
from .local_intelligence import LocalIntelligenceRouter, LocalRole
from .experiment import DeterministicExperimentRunner
from .experiment import ExperimentPlan
from .pre_verifier import DeterministicPreVerifier
from .cloud_review import CloudReviewer, EvidencePackage
from .campaign import RedStatus
from .authority import Operation, require
import hashlib
import inspect
import json
import math
from .metrics import RSIMetrics
from .observation_bus import ImprovementObservation, ImprovementSource


@dataclass(frozen=True)
class AutonomousRSIConfig:
    observation_batch: int = 16
    interval_seconds: float = 30
    metric_noise_tolerance: float = 0.05

@dataclass
class AutonomousRSIState:
    stage: str = 'OBSERVE'
    cycles: int = 0
    records: list = field(default_factory=list)

class AutonomousRSIController:
    def __init__(self, bus, ledger, governor, **services):
        self.bus, self.ledger, self.governor = bus, ledger, governor
        self.state = AutonomousRSIState()
        self.config = services.get("config", AutonomousRSIConfig())
        self.local = services.get('local', LocalIntelligenceRouter())
        self.frontier = services.get('frontier')
        self.plans = services.get('plans', {})
        self.workspace_factory = services.get('workspace_factory')
        self.prepare = services.get('prepare')
        self.runner = services.get('runner', DeterministicExperimentRunner())
        self.verifier = DeterministicPreVerifier(self.runner)
        self.cloud = services.get('cloud', CloudReviewer())
        self.execution_backend = services.get('execution_backend', 'native')
        self.scheduler = OpportunityScheduler(ledger, governor)
        self.current = None
        self.candidate = None
        self.seen = set()
        self.hypotheses = ()
        self.accepted_baseline = None
        self.research = services.get("research")
        self.claims = ()
        self.metrics = services.get('metrics', RSIMetrics())
        self.measure = services.get('measure')
        self.meta_measure = services.get('meta_measure')
        self.context = services.get("context", asdict)
        self.evidence_sink = services.get('evidence_sink')
        self.repository = services.get('repository')
        self.metric_noise_tolerance = services.get(
            'metric_noise_tolerance', self.config.metric_noise_tolerance
        )
        if (isinstance(self.metric_noise_tolerance, bool)
                or not isinstance(self.metric_noise_tolerance, (int, float))
                or not math.isfinite(self.metric_noise_tolerance)
                or self.metric_noise_tolerance < 0
                or self.metric_noise_tolerance >= 1):
            raise ValueError('metric noise tolerance must be finite and in [0, 1)')

    @staticmethod
    def _metric_direction(name):
        normalized = str(name).casefold().replace('-', '_').replace(' ', '_')
        if 'throughput' in normalized or normalized in {
            'benchmark_success', 'benchmark_success_rate', 'success_rate',
        }:
            return 'higher'
        if 'latency' in normalized or 'memory' in normalized:
            return 'lower'
        return None

    @staticmethod
    def _valid_metric(value):
        return (not isinstance(value, bool) and isinstance(value, (int, float))
                and math.isfinite(value))

    def _observe_metric_regressions(self):
        baseline = self.metrics.accepted_baseline
        if not baseline or self.repository is None or not callable(self.measure):
            return ()
        try:
            current = self.measure(self.repository)
            if not isinstance(current, dict):
                return ()
            current_values = dict(current)
            if callable(self.meta_measure):
                meta = self._meta(self.repository)
                if not isinstance(meta, dict):
                    return ()
                current_values.update(meta)
        except Exception:
            return ()

        baseline_values = {}
        for section in ('capability', 'meta'):
            values = baseline.get(section, {})
            if not isinstance(values, dict):
                return ()
            baseline_values.update(values)

        submitted = []
        for name, before in baseline_values.items():
            direction = self._metric_direction(name)
            after = current_values.get(name)
            if (direction is None or not self._valid_metric(before)
                    or not self._valid_metric(after)):
                continue
            scale = max(abs(float(before)), 1.0)
            change = ((float(before) - float(after)) / scale
                      if direction == 'higher'
                      else (float(after) - float(before)) / scale)
            if change <= self.metric_noise_tolerance:
                continue
            component = next(iter(sorted(self.plans)), 'benchmark')
            observation = ImprovementObservation(
                ImprovementSource.BENCHMARK,
                f"Metric regression detected: {name}",
                component,
                (f"baseline={before}", f"current={after}",
                 f"relative_regression={change:.6f}",
                 f"noise_tolerance={self.metric_noise_tolerance:.6f}"),
                f"Restore {name} without weakening the frozen verification policy",
            )
            if self.bus.submit(observation):
                submitted.append(observation)
        return tuple(submitted)

    def observe_benchmarks(self):
        """Submit only independently verified frozen-RED benchmark failures."""
        if self.repository is None:
            return ()
        submitted = list(self._observe_metric_regressions())
        for component, plan in sorted(self.plans.items()):
            try:
                result = self.runner.red(plan, self.repository)
            except Exception:
                continue
            if result.red_status is not RedStatus.RED_CONFIRMED:
                continue
            evidence = tuple(
                str(getattr(run, 'output', ''))[-2000:]
                for run in result.runs
            )
            observation = ImprovementObservation(
                ImprovementSource.BENCHMARK,
                f"Frozen benchmark RED confirmed for {component}: {plan.expected_failure}",
                component,
                evidence or (plan.expected_failure,),
            )
            if self.bus.submit(observation):
                submitted.append(observation)
        return tuple(submitted)

    def _meta(self, path):
        if inspect.signature(self.meta_measure).parameters:
            return self.meta_measure(path)
        return self.meta_measure()

    def _active_experiment_plan(self, base_plan, task):
        """Derive a bounded task plan from a preverified curriculum contract.

        The task may select its own RED/GREEN contract only after the
        repository-bound curriculum preverification has accepted it.  The
        host-owned holdout, regression, allowed-path, and timeout policy stays
        in force; a task cannot replace those gates.
        """
        red_command = tuple(getattr(task, "red_command", ()) or ()) if task else ()
        green_commands = tuple(
            tuple(command) for command in (getattr(task, "green_commands", ()) or ())
        ) if task else ()
        marker = str(getattr(task, "red_failure_marker", "") or "").strip() if task else ""
        if not (red_command and green_commands and marker):
            return base_plan
        task_paths = frozenset(getattr(task, "editable_paths", ()) or ())
        if not task_paths.issubset(base_plan.allowed_paths):
            raise ValueError("curriculum task paths exceed frozen experiment policy")
        return ExperimentPlan(
            identifier=f"{base_plan.identifier}:curriculum:{task.task_id}",
            focused=(red_command,),
            holdout=green_commands + base_plan.holdout,
            regression=base_plan.regression,
            expected_failure=marker,
            allowed_paths=base_plan.allowed_paths,
            version=base_plan.version,
            timeout=min(base_plan.timeout, 300),
        )

    @staticmethod
    def _degraded(before, after):
        lower_is_better = {'regression_rate', 'attempts_per_accepted_improvement',
            'cloud_escalations_per_accepted_improvement', 'cloud_token_cost_per_accepted_improvement',
            'time_to_confirmed_weakness', 'time_to_accepted_improvement'}
        if not before or set(before) != set(after):
            return True
        for key, value in before.items():
            new = after[key]
            if (not isinstance(new, (float, int)) or not isinstance(value, (float, int))
                or not math.isfinite(new) or not math.isfinite(value)):
                return True
            direction = AutonomousRSIController._metric_direction(key)
            if direction == 'lower':
                degraded = new > value
            elif direction == 'higher':
                degraded = new < value
            else:
                degraded = new > value if key in lower_is_better else new < value
            if degraded:
                return True
        return False

    def _emit(self, stage, **evidence):
        record = {'stage': stage, 'cycle': self.state.cycles, **evidence}
        self.state.records = (self.state.records + [record])[-256:]
        if self.evidence_sink:
            self.evidence_sink(record)
        return record

    def _reject(self, reason):
        if self.current:
            self.ledger.reject(self.current.fingerprint, reason, time.time())
        self.metrics.increment('locally_rejected_candidates')
        if 'holdout' in reason or 'regression' in reason:
            self.metrics.increment('regressions_prevented')
        self._emit('RECORD', verdict='REJECTED', reason=reason)
        if self.candidate:
            self.candidate.close()
        self.current, self.candidate = None, None
        self.state.stage = 'OBSERVE'

    def tick(self):
        now = time.time()
        for observation, count in self.bus.drain(self.config.observation_batch):
            before = len(self.ledger.records)
            self.ledger.ingest(observation, count, now)
            self.metrics.increment('observations', count)
            self.metrics.increment('deduplicated_weaknesses', int(len(self.ledger.records) > before))
        resources = self.governor.sample()
        decision = self.governor.decide(resources)
        self.state.cycles += 1
        if decision is ResourceDecision.OBSERVE_ONLY:
            return self._emit('OBSERVE', decision=decision.value)
        stage = self.state.stage
        active_task = getattr(self, 'active_curriculum_task', None)
        try:
            if stage == 'OBSERVE':
                self.state.stage = 'PRIORITIZE'
            elif stage == 'PRIORITIZE':
                selected = self.scheduler.select(resources, now)
                if selected:
                    self.current = self.ledger.records[selected[0].fingerprint]
                    self.state.stage = 'LOCAL_ANALYSIS'
                else:
                    self.state.stage = 'OBSERVE'
            elif stage == 'LOCAL_ANALYSIS':
                if getattr(active_task, 'proposal_files', {}):
                    self.hypotheses = ()
                    self.state.stage = 'EXPERIMENT'
                else:
                    route = ('qwen_then_spark' if decision is ResourceDecision.LOCAL_DEEP and resources.qwen_available
                             else 'spark' if decision is ResourceDecision.LOCAL_DEEP
                             else 'qwen' if resources.qwen_available else 'skip_local')
                    self.hypotheses = ()
                    if callable(self.frontier):
                        frontier_router = LocalIntelligenceRouter({'frontier': self.frontier})
                        self.hypotheses = frontier_router.analyze(
                            self.context(self.current), route='frontier', role=LocalRole.HYPOTHESIS
                        )
                        self.metrics.increment('frontier_calls', frontier_router.calls['frontier'])
                    if not self.hypotheses:
                        counts = dict(self.local.calls)
                        self.hypotheses = self.local.analyze(self.context(self.current), route=route)
                        for name in ('qwen', 'spark'):
                            self.metrics.increment(name + '_calls', self.local.calls[name] - counts[name])
                    if not self.hypotheses:
                        self._reject('frontier and local analysis unavailable or uncertain')
                    else:
                        self.state.stage = 'EXPERIMENT'
            elif stage == 'EXPERIMENT':
                if (not (active_task and getattr(active_task, 'proposal_files', {}))
                        and self.research
                        and self.governor.decide(resources, research=True) is ResourceDecision.INTERNET_RESEARCH):
                    self.claims = self.research.discover(self.current, resources)
                    self.metrics.increment('sli_calls')
                    self._emit('RESEARCH', claims=tuple(asdict(c) for c in self.claims))
                    if self.claims:
                        counts = dict(self.local.calls)
                        try:
                            researched = self.local.analyze({'weakness': self.context(self.current),
                                'untrusted_research_claims': [asdict(c) for c in self.claims]},
                                route='qwen' if resources.qwen_available else 'spark',
                                role=LocalRole.EXPERIMENT_DESIGN)
                            self.hypotheses = self.hypotheses + researched
                        except RuntimeError as error:
                            # Research enrichment is advisory. A provider
                            # timeout must not discard an already bounded
                            # frontier hypothesis or candidate proposal.
                            self._emit('RESEARCH_ANALYSIS_SKIPPED', reason=type(error).__name__)
                        for name in ('qwen', 'spark'):
                            self.metrics.increment(name + '_calls', self.local.calls[name] - counts[name])
                base_plan = self.plans.get(self.current.component)
                active_task = getattr(self, 'active_curriculum_task', None)
                try:
                    self.plan = self._active_experiment_plan(base_plan, active_task) if base_plan else None
                except ValueError as error:
                    self._reject(str(error))
                    self.plan = None
                if self.plan is None or not self.workspace_factory or not self.prepare:
                    if self.current is not None:
                        self._reject('host experiment unavailable')
                else:
                    self.candidate = self.workspace_factory()
                    self.baseline_metrics = self.measure(self.candidate.path) if self.measure else None
                    self.baseline_meta = self._meta(self.candidate.path) if self.meta_measure else None
                    frozen = {k: hashlib.sha256(v).hexdigest() for k, v in self.candidate.baseline.files.items()
                              if k not in self.plan.allowed_paths}
                    self.benchmark_version = self.plan.identifier + ':' + self.plan.version + ':' + hashlib.sha256(
                        json.dumps(frozen, sort_keys=True).encode()).hexdigest()
                    self.metrics.increment('experiments')
                    self.state.stage = 'RED'
            elif stage == 'RED':
                self.red = self.runner.red(self.plan, self.candidate.path)
                if self.red.red_status is not RedStatus.RED_CONFIRMED:
                    self._reject('genuine RED unavailable')
                else:
                    self.metrics.increment('confirmed_reds')
                    self.state.stage = 'CANDIDATE'
            elif stage == 'CANDIDATE':
                # Trusted deterministic experiment adapter; no local model write capability.
                self.prepare(self.candidate, self.plan, self.hypotheses)
                fingerprint = self.candidate.diff().fingerprint
                if fingerprint in self.seen:
                    self._reject('duplicate candidate fingerprint')
                else:
                    self.seen.add(fingerprint)
                    if len(self.seen) > 2048:
                        self._reject('candidate fingerprint budget exhausted')
                    else:
                        self.state.stage = 'PREVERIFY'
            elif stage == 'PREVERIFY':
                self.verified = self.verifier.verify(self.candidate, self.plan, self.red)
                for hypothesis in self.hypotheses:
                    self.local.record_result(hypothesis.model, LocalRole(hypothesis.role), success=self.verified.accepted)
                if not self.verified.accepted:
                    self._reject('preverification: ' + ', '.join(self.verified.reasons))
                else:
                    self.state.stage = 'CLOUD_REVIEW'
            elif stage == 'CLOUD_REVIEW':
                package = EvidencePackage(asdict(self.current), self.verified,
                    self.candidate.diff().text, tuple(asdict(h) for h in self.hypotheses), self.current.expected_gain,
                    {'execution_backend': self.execution_backend,
                     'qemu_isolation': self.execution_backend == 'qemu'})
                counts = dict(self.cloud.calls)
                self.review = self.cloud.review(package, resources)
                for name, metric in (('codex_cli', 'codex_reviews'), ('nifdu_browser', 'nifdu_reviews')):
                    self.metrics.increment(metric, self.cloud.calls[name] - counts[name])
                if self.review.provider == 'local_artifact':
                    self.metrics.increment('local_reviews')
                else:
                    self.metrics.increment('cloud_reviews', sum(self.cloud.calls.values()) - sum(counts.values()))
                if self.review.action not in ('approve', 'improve'):
                    self._reject('cloud: ' + self.review.reason)
                else:
                    self.state.stage = 'AUTHORIZED_IMPLEMENTATION'
            elif stage == 'AUTHORIZED_IMPLEMENTATION':
                if self.candidate.diff().fingerprint != self.verified.fingerprint:
                    raise PermissionError('Candidate changed after cloud review')
                require(self.review.provider, Operation.SOPHYANE_SOURCE_MUTATION)
                if self.review.files:
                    self.candidate.apply(self.review.provider, self.review.files, self.plan.allowed_paths)
                self.authorized_fingerprint = self.candidate.diff().fingerprint
                self.state.stage = 'REVERIFY'
            elif stage == 'REVERIFY':
                if self.candidate.diff().fingerprint != self.authorized_fingerprint:
                    raise PermissionError('Candidate changed after authorized implementation')
                self.verified = self.verifier.verify(self.candidate, self.plan, self.red)
                if not self.verified.accepted:
                    self._reject('reverification: ' + ', '.join(self.verified.reasons))
                else:
                    if not self.measure or not self.meta_measure:
                        self._reject('independent measurements unavailable')
                    else:
                        self.candidate_metrics = self.measure(self.candidate.path)
                        before = self.baseline_metrics.get('benchmark_success')
                        after = self.candidate_metrics.get('benchmark_success')
                        if (not isinstance(before, (float, int)) or not isinstance(after, (float, int))
                            or not math.isfinite(before) or not math.isfinite(after) or after <= before):
                            self._reject('no measured capability gain')
                        elif (self.metrics.accepted_baseline is not None
                              and after <= self.metrics.accepted_baseline['capability'].get('benchmark_success', float('-inf'))):
                            self._reject('no gain over accepted capability frontier')
                        elif self._degraded(self.baseline_metrics, self.candidate_metrics):
                            self._reject('protected capability metric degradation')
                        elif self._degraded(self.baseline_meta, self._meta(self.candidate.path)):
                            self._reject('meta degradation')
                        elif self.candidate.diff().fingerprint != self.verified.fingerprint:
                            self._reject('candidate changed during measurement')
                        else:
                            self.state.stage = 'PROMOTE'
            elif stage == 'PROMOTE':
                self.promoted_fingerprint = self.candidate.promote(self.review.provider, self.verified, self.plan.allowed_paths)
                self.state.stage = 'MEASURE'
            elif stage == 'MEASURE':
                self.promoted_metrics = self.measure(self.candidate.repository)
                if self.promoted_metrics != self.candidate_metrics:
                    self._reject('post-promotion measurement changed')
                else:
                    self.state.stage = 'META_MEASURE'
            elif stage == 'META_MEASURE':
                self.meta_metrics = self._meta(self.candidate.repository)
                if self._degraded(self.baseline_meta, self.meta_metrics):
                    self._reject('post-promotion meta degradation')
                else:
                    self.state.stage = 'RECORD'
            elif stage == 'RECORD':
                self.metrics.record(self.benchmark_version,
                                    self.promoted_metrics, self.meta_metrics, True)
                self.metrics.increment('accepted_candidates')
                self.accepted_baseline = self.promoted_fingerprint
                self.current.status = 'accepted'
                self.candidate.accept_promotion()
                self.ledger.save()
                self.candidate.close()
                self.current, self.candidate = None, None
                self.state.stage = 'OBSERVE'
            evidence = {}
            if stage == 'LOCAL_ANALYSIS':
                evidence['hypotheses'] = tuple(asdict(h) for h in self.hypotheses)
            if stage == 'CANDIDATE' and hasattr(self, 'generation_evidence'):
                evidence['candidate_generation'] = dict(self.generation_evidence)
            if stage == 'RED' and hasattr(self, 'red'):
                evidence['red'] = asdict(self.red)
            if stage in ('PREVERIFY', 'REVERIFY') and hasattr(self, 'verified'):
                evidence['verification'] = asdict(self.verified)
            if stage == 'CLOUD_REVIEW' and hasattr(self, 'review'):
                evidence['review'] = asdict(self.review)
            if stage == 'MEASURE' and hasattr(self, 'promoted_metrics'):
                evidence['capability'] = self.promoted_metrics
            if stage == 'META_MEASURE' and hasattr(self, 'meta_metrics'):
                evidence['meta'] = self.meta_metrics
            return self._emit(stage, decision=decision.value, next_stage=self.state.stage, **evidence)
        except Exception as error:
            self._reject(type(error).__name__ + ': ' + str(error))
            return self._emit(stage, decision=decision.value, error=type(error).__name__)

    def run(self, stop_event, max_cycles=None):
        if max_cycles is not None and max_cycles < 0:
            raise ValueError('max_cycles must be nonnegative')
        count = 0
        try:
            while not stop_event.is_set() and (max_cycles is None or count < max_cycles):
                self.tick()
                count += 1
                if max_cycles is None or count < max_cycles:
                    stop_event.wait(max(.05, min(300, self.config.interval_seconds)))
        finally:
            if self.candidate:
                self.candidate.close()
                self.candidate = None
