"""Deterministic resource policy with optional platform sensors."""
from dataclasses import dataclass
from enum import Enum

class ResourceDecision(str, Enum):
    OBSERVE_ONLY = 'OBSERVE_ONLY'
    LOCAL_LIGHT = 'LOCAL_LIGHT'
    LOCAL_DEEP = 'LOCAL_DEEP'
    INTERNET_RESEARCH = 'INTERNET_RESEARCH'
    CLOUD_REVIEW = 'CLOUD_REVIEW'

@dataclass(frozen=True)
class ResourceSnapshot:
    load: float | None = None
    logical_cpus: int = 1
    available_ram: int | None = None
    total_ram: int | None = None
    battery_percent: float | None = None
    charging: bool | None = None
    thermal_state: str | None = None
    online: bool = False
    user_active: bool = True
    qwen_available: bool = False
    spark_available: bool = False
    codex_available: bool = False
    nifdu_available: bool = False
    sli_available: bool = False
    cloud_budget_available: bool = False

@dataclass(frozen=True)
class ResourcePolicy:
    minimum_ram: int = 512 * 1024**2
    deep_ram: int = 4 * 1024**3
    maximum_load_per_cpu: float = .75
    minimum_battery: float = 20

class ResourceGovernor:
    def __init__(self, policy=None, sampler=None):
        self.policy, self.sampler = policy or ResourcePolicy(), sampler
    def decide(self, snapshot, *, research=False, promising=False):
        p, s = self.policy, snapshot
        if (s.user_active or
            (s.load is not None and s.load / max(1, s.logical_cpus) > p.maximum_load_per_cpu) or
            (s.available_ram is not None and s.available_ram < p.minimum_ram) or
            (s.battery_percent is not None and s.battery_percent < p.minimum_battery and s.charging is not True) or
            s.thermal_state in ('hot', 'critical', 'severe')):
            return ResourceDecision.OBSERVE_ONLY
        if promising and s.online and s.cloud_budget_available and (s.codex_available or s.nifdu_available):
            return ResourceDecision.CLOUD_REVIEW
        if research and s.online and s.sli_available:
            return ResourceDecision.INTERNET_RESEARCH
        if s.spark_available and s.available_ram is not None and s.available_ram >= p.deep_ram:
            return ResourceDecision.LOCAL_DEEP
        return ResourceDecision.LOCAL_LIGHT

    def sample(self):
        if self.sampler:
            return self.sampler()
        import os
        from pathlib import Path
        load, available, total = None, None, None
        try:
            load = os.getloadavg()[0]
        except (OSError, AttributeError):
            pass
        try:
            values = {line.split(':')[0]: int(line.split()[1]) * 1024
                      for line in Path('/proc/meminfo').read_text().splitlines()}
            available, total = values.get('MemAvailable'), values.get('MemTotal')
        except (OSError, ValueError, IndexError):
            pass
        return ResourceSnapshot(load=load, logical_cpus=os.cpu_count() or 1,
                                available_ram=available, total_ram=total)
