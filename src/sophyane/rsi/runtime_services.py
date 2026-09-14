"""Lazy production adapters. Construction performs no model/network requests.

Experiment policy is host-owned JSON in the external supervisor state directory.
Models and research cannot add policies, commands or editable paths to it.
"""
from dataclasses import asdict, replace
import json
import os
from pathlib import Path
import shutil
import socket
import tempfile
import time
from urllib.parse import urlparse

from .autonomous import AutonomousRSIController
from .candidate_workspace import CandidateWorkspace
from .cloud_review import CloudReviewer, provider_reviewer
from .experiment import ExperimentPlan
from .local_intelligence import LocalIntelligenceRouter
from .observation_bus import autonomous_bus
from .research import TargetedSLIResearch
from .resource_governor import ResourceGovernor, ResourceDecision
from .weakness_ledger import WeaknessLedger


def local_request(name, context, role):
    from sophyane.local_model_profiles import qwen_profile, spark_profile
    from sophyane.providers.http import post_json
    profile = qwen_profile() if name == 'qwen' else spark_profile()
    response = post_json(profile['endpoint'] + '/v1/chat/completions', {
        'model': profile['model'], 'messages': [
            {'role': 'system', 'content': 'Read-only RSI analysis: ' + role.value +
             '. Return JSON hypothesis (or critique), and optional files mapping of tiny replacement proposals. No tools, commands, authority or verification claims.'},
            {'role': 'user', 'content': context[:12000]}],
        'max_tokens': 512, 'temperature': 0}, timeout=30)
    return response['choices'][0]['message']['content']


def _reachable(endpoint):
    value = urlparse(endpoint)
    try:
        with socket.create_connection((value.hostname, value.port or 443), timeout=.15):
            return True
    except OSError:
        return False


def build_controller(state_dir, *, active=lambda: True):
    state_dir = Path(state_dir)
    repository = Path(__file__).resolve().parents[3]
    specs = {}
    policy_file = state_dir / 'experiments.json'
    if policy_file.exists():
        specs = json.loads(policy_file.read_text())
    plans = {}
    for component, spec in specs.items():
        from .controller import protects_verification
        protected_commands = (tuple(spec.get('benchmark_command', ())), tuple(spec.get('meta_command', ())))
        if not protects_verification(spec['allowed_paths'], protected_commands):
            raise ValueError('Benchmark and meta benchmark paths are frozen')
        plans[component] = ExperimentPlan(spec['identifier'],
            tuple(tuple(c) for c in spec['focused']), tuple(tuple(c) for c in spec['holdout']),
            tuple(tuple(c) for c in spec['regression']), spec['expected_failure'],
            frozenset(spec['allowed_paths']), spec['version'], min(60, spec.get('timeout', 60)))
    sensor = ResourceGovernor()
    profiles, cached, sampled = {}, None, 0
    budget = max(0, min(20, int(os.environ.get('SOPHYANE_RSI_CLOUD_REVIEWS', '2'))))
    used = 0

    def sample():
        nonlocal cached, sampled, profiles
        current = replace(sensor.sample(), user_active=active())
        if sensor.decide(current) is ResourceDecision.OBSERVE_ONLY:
            return current
        if cached is None or time.monotonic() - sampled > 60:
            from sophyane.local_model_profiles import qwen_profile, spark_profile
            profiles = {'qwen': qwen_profile(), 'spark': spark_profile()}
            cached = dict(qwen_available=_reachable(profiles['qwen']['endpoint']),
                spark_available=_reachable(profiles['spark']['endpoint']),
                online=_reachable('https://1.1.1.1:443'),
                codex_available=bool(shutil.which('codex')), nifdu_available=True,
                sli_available=True)
            sampled = time.monotonic()
        return replace(current, **cached, cloud_budget_available=used < budget)

    def review(name, package):
        nonlocal used
        from .availability import AvailabilityStore
        from .coding_provider import create_provider
        store = AvailabilityStore(state_dir / 'cloud-availability.json')
        if store.blocked(name):
            raise RuntimeError('Provider temporarily unavailable')
        if used >= budget:
            raise RuntimeError('Cloud quota exhausted')
        used += 1
        try:
            # Cloud tools see an empty scratch directory, never the primary tree.
            with tempfile.TemporaryDirectory(prefix='rsi-cloud-') as scratch:
                provider = create_provider(name, Path(scratch), 60)
                result = provider_reviewer(provider)(package)
            store.success(name)
            return result
        except Exception as error:
            store.failure(name, error)
            raise

    def prepare(candidate, plan, hypotheses):
        spec = next(s for s in specs.values() if s['identifier'] == plan.identifier)
        # Host-authored deterministic replacement fixture, not parsed model output.
        proposals = next((h.files for h in hypotheses if h.files), {})
        if not proposals:
            raise ValueError('No concrete local proposal; retain weakness for later analysis')
        candidate.preview(proposals, plan.allowed_paths)

    def measure(path):
        from .verification import run_command
        if len(specs) != 1:
            raise ValueError('Measurement requires one frozen active benchmark policy')
        spec = next(iter(specs.values()))
        command = tuple(spec['benchmark_command'])
        result = run_command(command, path, timeout=60)
        if result.exit_code:
            raise ValueError('Capability benchmark failed')
        return json.loads(result.output)

    def context(record):
        plan = plans.get(record.component)
        files = {}
        if plan:
            for name in sorted(plan.allowed_paths)[:8]:
                target = repository / name
                if target.is_file() and not target.is_symlink() and target.resolve().is_relative_to(repository):
                    files[name] = target.read_text()[:12000]
        return {'weakness': asdict(record), 'source_files': files}

    controller = AutonomousRSIController(autonomous_bus, WeaknessLedger(state_dir / 'weaknesses.json'),
        ResourceGovernor(sampler=sample),
        local=LocalIntelligenceRouter({name: lambda context, role, name=name: local_request(name, context, role)
                                       for name in ('qwen', 'spark')}),
        research=TargetedSLIResearch(),
        cloud=CloudReviewer({name: lambda package, name=name: review(name, package)
                            for name in ('codex_cli', 'nifdu_browser')}),
        plans=plans, workspace_factory=lambda: CandidateWorkspace(repository, state_dir / 'candidates').create(),
        prepare=prepare, measure=measure, context=context)
    # No meta benchmark is invented from operational counters. A policy must
    # supply a frozen external command before promotion can be admitted.
    def meta_measure(path):
        from .verification import run_command
        spec = next(iter(specs.values()))
        result = run_command(tuple(spec['meta_command']), path, timeout=60)
        if result.exit_code:
            raise ValueError('Meta benchmark failed')
        return json.loads(result.output)
    if len(specs) == 1 and next(iter(specs.values())).get('meta_command'):
        controller.meta_measure = meta_measure
    metrics_path = state_dir / 'metrics.json'
    if metrics_path.exists():
        previous = json.loads(metrics_path.read_text())
        controller.metrics.counters.update(previous.get('counters', {}))
        controller.metrics.measurements = previous.get('measurements', [])[-256:]
        controller.seen = set(previous.get('candidate_fingerprints', [])[:2048])
        for name, profile in controller.local.profiles.items():
            profile.competence = previous.get('competence', {}).get(name, {})
    def persist(record):
        state_dir.mkdir(parents=True, exist_ok=True)
        stages = state_dir / 'stages.jsonl'
        if stages.exists() and stages.stat().st_size > 4 * 1024**2:
            stages.replace(state_dir / 'stages.previous.jsonl')
        with stages.open('a') as stream:
            stream.write(json.dumps(record, default=str, sort_keys=True) + '\n')
        data = asdict(controller.metrics)
        data['candidate_fingerprints'] = sorted(controller.seen)
        data['competence'] = {name: profile.competence for name, profile in controller.local.profiles.items()}
        temporary = metrics_path.with_suffix('.tmp')
        temporary.write_text(json.dumps(data, sort_keys=True))
        temporary.replace(metrics_path)
    controller.evidence_sink = persist
    return controller
