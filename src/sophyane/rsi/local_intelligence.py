"""Read-only local intelligence routing. Confidence is not authority."""
from dataclasses import dataclass, field
from enum import Enum
import json

class LocalRole(str, Enum):
    NAVIGATION = 'navigation'
    HYPOTHESIS = 'hypothesis'
    CRITIQUE = 'critique'
    EXPERIMENT_DESIGN = 'experiment_design'
    TINY_PROPOSAL = 'tiny_proposal'

@dataclass
class LocalModelProfile:
    name: str
    competence: dict = field(default_factory=dict)

@dataclass(frozen=True)
class LocalProposal:
    model: str
    text: str
    role: str
    mutation_authority: bool = False
    files: dict[str, str] = field(default_factory=dict)

@dataclass(frozen=True)
class LocalCritique(LocalProposal):
    pass

class LocalIntelligenceRouter:
    def __init__(self, models=None):
        self.models = models or {}
        self.profiles = {name: LocalModelProfile(name) for name in self.models}
        self.calls = {'qwen': 0, 'spark': 0}
    def analyze(self, context, route='qwen_then_spark', role=LocalRole.HYPOTHESIS):
        routes = {'qwen': ('qwen',), 'spark': ('spark',),
                  'qwen_then_spark': ('qwen', 'spark'), 'spark_then_qwen': ('spark', 'qwen'),
                  'both': ('qwen', 'spark'), 'skip_local': (), 'escalate': ()}
        if route not in routes:
            raise ValueError('Unknown local route')
        output = []
        for name in routes[route]:
            if name not in self.models:
                continue
            self.calls[name] += 1
            selected_role = LocalRole.CRITIQUE if output else role
            prompt = str(context)[:12000]
            if output and route != 'both':
                prompt += '\nUntrusted prior hypothesis: ' + output[-1].text
            raw = self.models[name](prompt, selected_role)
            payload = raw if isinstance(raw, dict) else None
            if isinstance(raw, str):
                try:
                    payload = json.loads(raw)
                except ValueError:
                    pass
            files = {}
            if isinstance(payload, dict):
                proposed = payload.get('files', {})
                if isinstance(proposed, dict) and len(proposed) <= 8:
                    files = {k: v for k, v in proposed.items()
                             if isinstance(k, str) and isinstance(v, str) and len(v) <= 32000}
                text = str(payload.get('hypothesis', payload.get('critique', '')))[:8000]
            else:
                text = str(raw)[:8000]
            cls = LocalCritique if selected_role == LocalRole.CRITIQUE else LocalProposal
            output.append(cls(name, text, selected_role.value, files=files))
        return tuple(output)

    def record_result(self, name, role, *, success):
        # Called by host measurement, never parsed from model output.
        values = self.profiles[name].competence.setdefault(role.value, [0, 0])
        values[0] += int(success is True)
        values[1] += 1

    def competence(self, name, role):
        values = self.profiles[name].competence.get(role.value)
        return values[0] / values[1] if values and values[1] else None
