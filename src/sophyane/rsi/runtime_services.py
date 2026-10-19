"""Lazy production adapters. Construction performs no model/network requests.

Experiment policy is host-owned JSON in the external supervisor state directory.
Models and research cannot add policies, commands or editable paths to it.
"""
from dataclasses import asdict, replace
import json
import hashlib
import os
from pathlib import Path
import shlex
import shutil
import socket
import sys
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
from .resource_governor import ResourceGovernor, ResourceDecision, ResourcePolicy
from .weakness_ledger import WeaknessLedger


def build_curriculum_runtime(state_dir, controller, *, proposal_adapter=None):
    """Build the opt-in curriculum adapter for a trusted host.

    The existing autonomous observation controller is wrapped in a bounded
    task adapter; it remains responsible for all candidate and promotion gates.
    """
    from .curriculum import CurriculumPolicy, CurriculumScheduler, CurriculumStore
    from .curriculum_adapter import NativeEvolutionTaskAdapter
    from .curriculum_proposals import CurriculumProposalAdapter, ProposalContext
    from .curriculum_source import CurriculumTaskSource
    from .curriculum_runtime import ContinuousCurriculumRuntime
    from .heartbeat import HeartbeatStore
    from .local_intelligence import LocalRole

    root = Path(state_dir)
    policy = CurriculumPolicy(
        max_iterations=max(1, int(os.environ.get("SOPHYANE_RSI_MAX_ITERATIONS", "100"))),
        max_wall_seconds=max(1.0, float(os.environ.get("SOPHYANE_RSI_MAX_WALL_SECONDS", "86400"))),
        cooldown_seconds=max(0.0, float(os.environ.get("SOPHYANE_RSI_COOLDOWN_SECONDS", "30"))),
        max_queue_length=max(1, int(os.environ.get("SOPHYANE_RSI_MAX_QUEUE", "32"))),
        max_follow_ups=max(0, int(os.environ.get("SOPHYANE_RSI_MAX_FOLLOW_UPS", "1"))),
        max_task_attempts=max(1, int(os.environ.get("SOPHYANE_RSI_MAX_TASK_ATTEMPTS", "3"))),
    )
    enabled = os.environ.get("SOPHYANE_CONTINUOUS_RSI", "1").strip() == "1"
    if proposal_adapter is None:
        proposal_adapter = CurriculumProposalAdapter(
            lambda prompt: _curriculum_proposal_with_fallback(prompt, LocalRole.TINY_PROPOSAL)
        )
    repository = Path(__file__).resolve().parents[3]
    health_text = os.environ.get("SOPHYANE_RSI_LIVE_HEALTH_COMMAND", "")
    health_command = tuple(shlex.split(health_text)) if health_text.strip() else (
        sys.executable,
        "-c",
        "import sophyane",
    )
    from .promotion import PromotionManager
    promotion_manager = PromotionManager(repository, root, health_command=health_command)
    task_runner = NativeEvolutionTaskAdapter(
        repository,
        timeout_seconds=max(1, int(os.environ.get("SOPHYANE_RSI_TASK_TIMEOUT", "300"))),
        promotion_manager=promotion_manager,
    )
    scheduler = CurriculumScheduler(CurriculumStore(root / "curriculum.json"), policy)
    runtime = ContinuousCurriculumRuntime(
        root,
        task_runner,
        scheduler,
        proposal_adapter=proposal_adapter,
        enabled=enabled,
    )

    def context_factory():
        state = scheduler.store.load()
        ability = state.abilities[-1] if state.abilities else None
        if ability is None:
            from .curriculum import AbilityRecord
            ability = AbilityRecord("seed", "initial bounded RSI ability", ("host policy",))
        allowed = tuple(sorted({path for plan in getattr(controller, "plans", {}).values()
                                for path in getattr(plan, "allowed_paths", ())})[:8])
        if not allowed:
            return None
        return ProposalContext(
            ability=ability,
            allowed_paths=allowed,
            existing_task_ids=tuple(task.task_id for task in state.queue),
            capability_summary="request one bounded, measurable RSI follow-up",
        )

    runtime.heartbeat = HeartbeatStore(root / "heartbeat.json")
    runtime.heartbeat_interval = max(0.5, float(os.environ.get("SOPHYANE_RSI_HEARTBEAT_SECONDS", "5")))
    runtime.stale_seconds = max(runtime.heartbeat_interval * 2, float(os.environ.get("SOPHYANE_RSI_STALE_SECONDS", "30")))
    runtime.watchdog_enabled = os.environ.get("SOPHYANE_RSI_WATCHDOG", "1").strip() == "1"
    runtime.task_source_name = os.environ.get("SOPHYANE_RSI_TASK_SOURCE", "qwen").strip() or "qwen"
    generator = getattr(proposal_adapter, "generate", None)
    runtime.task_source = (
        CurriculumTaskSource(generator, proposal_adapter)
        if callable(generator) else None
    )
    runtime.context_factory = context_factory
    return runtime


def build_qemu_runner(state_dir):
    """Return the opt-in QEMU runner, or None for the normal host path."""
    if os.environ.get("SOPHYANE_RSI_EXECUTION_BACKEND", "").strip().lower() != "qemu":
        return None
    from .qemu_runner import QemuRunnerConfig, QemuRsiRunner

    root = Path(state_dir)
    image = Path(os.environ.get("SOPHYANE_RSI_QEMU_IMAGE", ""))
    executable = os.environ.get("SOPHYANE_RSI_QEMU_EXECUTABLE", "qemu-system-aarch64")
    scratch = Path(os.environ.get("SOPHYANE_RSI_QEMU_SCRATCH", str(root / "qemu-scratch")))
    config = QemuRunnerConfig(
        executable=executable,
        guest_image=image,
        architecture="aarch64",
        scratch_root=scratch,
        timeout_seconds=max(1.0, float(os.environ.get("SOPHYANE_RSI_QEMU_TIMEOUT", "300"))),
        max_output_bytes=max(1024, int(os.environ.get("SOPHYANE_RSI_QEMU_OUTPUT_LIMIT", "1048576"))),
        enabled=True,
    )
    return QemuRsiRunner(config)


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


def _deterministic_curriculum_proposal(prompt: str) -> str:
    """Create one safe task from host-frozen proposal context.

    This is only a liveness fallback when proposal intelligence is unavailable;
    the normal CurriculumProposalAdapter still validates every field and path.
    It never invents editable paths or commands outside the supplied context.
    """
    payload = json.loads(prompt)
    ability_id = str(payload.get("ability_id") or "seed")
    allowed_paths = tuple(str(item) for item in payload.get("allowed_paths", ()))
    if not allowed_paths:
        raise ValueError("fallback proposal requires host-approved allowed paths")
    parent_id = ability_id
    path = allowed_paths[0]
    # Native EvolutionEngine consumes capability names (filesystem/python/
    # shell/...), not experiment identifiers such as ``demo_score``.
    # A deterministic fallback is deliberately conservative: its bounded
    # artifact task is handled by the filesystem capability validator.
    component = "filesystem"
    digest = hashlib.sha256(f"{parent_id}:{path}".encode()).hexdigest()[:12]
    existing = {str(item) for item in payload.get("existing_task_ids", ())}
    task_id = f"autonomous-fallback-{digest}"
    retry = 1
    while task_id in existing:
        task_id = f"autonomous-fallback-{digest}-retry{retry}"
        retry += 1
    return json.dumps({
        "task_id": task_id,
        "parent_ability_id": parent_id,
        "objective": (
            "Run one bounded native RSI cycle for the frozen capability, "
            "preserve all protected checks, and accept only a verified promotion."
        ),
        "editable_paths": [path],
        "verification": ["native RSI promotion gate passes"],
        "component": component,
    })


def _curriculum_proposal_with_fallback(prompt: str, role) -> str:
    try:
        raw = local_request("qwen", prompt, role)
        payload = json.loads(raw)
        required = {"task_id", "parent_ability_id", "objective", "editable_paths", "verification"}
        if not isinstance(payload, dict) or not required.issubset(payload):
            raise ValueError("local proposal schema is incomplete")
        return raw
    except (OSError, TimeoutError, ConnectionError, RuntimeError, TypeError, ValueError):
        return _deterministic_curriculum_proposal(prompt)


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
    qemu_runner = build_qemu_runner(state_dir)
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
    resource_spec = {}
    if len(specs) == 1:
        resource_spec = next(iter(specs.values())).get("resource_policy", {})
    try:
        maximum_load = float(resource_spec.get("maximum_load_per_cpu", 0.75))
    except (TypeError, ValueError):
        raise ValueError("invalid resource policy load threshold")
    if not 0 < maximum_load <= 4:
        raise ValueError("resource policy load threshold is out of bounds")
    sensor = ResourceGovernor(policy=ResourcePolicy(maximum_load_per_cpu=maximum_load))
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

    from .experiment import DeterministicExperimentRunner
    experiment_runner = DeterministicExperimentRunner()
    if qemu_runner is not None:
        experiment_runner = DeterministicExperimentRunner(command_runner=qemu_runner.run_command)
    controller = AutonomousRSIController(autonomous_bus, WeaknessLedger(state_dir / 'weaknesses.json'),
        ResourceGovernor(policy=ResourcePolicy(maximum_load_per_cpu=maximum_load), sampler=sample),
        local=LocalIntelligenceRouter({name: lambda context, role, name=name: local_request(name, context, role)
                                       for name in ('qwen', 'spark')}),
        research=TargetedSLIResearch(),
        cloud=CloudReviewer({name: lambda package, name=name: review(name, package)
                            for name in ('codex_cli', 'nifdu_browser')}),
        plans=plans, runner=experiment_runner,
        workspace_factory=lambda: CandidateWorkspace(repository, state_dir / 'candidates').create(),
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
