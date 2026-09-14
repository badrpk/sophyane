"""Bounded autonomous RSI stages under host-owned policy and evidence."""
from dataclasses import dataclass, field, asdict
import time
from .resource_governor import ResourceDecision
from .opportunity_scheduler import OpportunityScheduler
from .local_intelligence import LocalIntelligenceRouter, LocalRole
from .experiment import DeterministicExperimentRunner
from .pre_verifier import DeterministicPreVerifier
from .cloud_review import CloudReviewer, EvidencePackage
from .campaign import RedStatus
from .authority import Operation, require
import hashlib
import inspect
import json
import math
from .metrics import RSIMetrics


@dataclass(frozen=True)
class AutonomousRSIConfig:
    observation_batch: int = 16
    interval_seconds: float = 30

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
        self.plans = services.get('plans', {})
        self.workspace_factory = services.get('workspace_factory')
        self.prepare = services.get('prepare')
        self.runner = services.get('runner', DeterministicExperimentRunner())
        self.verifier = DeterministicPreVerifier(self.runner)
        self.cloud = services.get('cloud', CloudReviewer())
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

    def _meta(self, path):
        if inspect.signature(self.meta_measure).parameters:
            return self.meta_measure(path)
        return self.meta_measure()

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
            if (new > value if key in lower_is_better else new < value):
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
                route = ('qwen_then_spark' if decision is ResourceDecision.LOCAL_DEEP and resources.qwen_available
                         else 'spark' if decision is ResourceDecision.LOCAL_DEEP
                         else 'qwen' if resources.qwen_available else 'skip_local')
                counts = dict(self.local.calls)
                self.hypotheses = self.local.analyze(self.context(self.current), route=route)
                for name in ('qwen', 'spark'):
                    self.metrics.increment(name + '_calls', self.local.calls[name] - counts[name])
                if not self.hypotheses:
                    self._reject('local analysis unavailable or uncertain')
                else:
                    self.state.stage = 'EXPERIMENT'
            elif stage == 'EXPERIMENT':
                if self.research and self.governor.decide(resources, research=True) is ResourceDecision.INTERNET_RESEARCH:
                    self.claims = self.research.discover(self.current, resources)
                    self.metrics.increment('sli_calls')
                    self._emit('RESEARCH', claims=tuple(asdict(c) for c in self.claims))
                    if self.claims:
                        counts = dict(self.local.calls)
                        researched = self.local.analyze({'weakness': self.context(self.current),
                            'untrusted_research_claims': [asdict(c) for c in self.claims]},
                            route='qwen' if resources.qwen_available else 'spark',
                            role=LocalRole.EXPERIMENT_DESIGN)
                        self.hypotheses = self.hypotheses + researched
                        for name in ('qwen', 'spark'):
                            self.metrics.increment(name + '_calls', self.local.calls[name] - counts[name])
                self.plan = self.plans.get(self.current.component)
                if self.plan is None or not self.workspace_factory or not self.prepare:
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
                    self.candidate.diff().text, tuple(asdict(h) for h in self.hypotheses), self.current.expected_gain)
                counts = dict(self.cloud.calls)
                self.review = self.cloud.review(package, resources)
                for name, metric in (('codex_cli', 'codex_reviews'), ('nifdu_browser', 'nifdu_reviews')):
                    self.metrics.increment(metric, self.cloud.calls[name] - counts[name])
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
