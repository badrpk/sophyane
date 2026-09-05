from __future__ import annotations

from sophyane.agent import _local_graph_answer


class FakeProvider:
    def __init__(self):
        self.calls = []

    def generate(self, prompt, system):
        self.calls.append(prompt)
        if prompt.startswith("Synthesize") or prompt.startswith("Verify"):
            return "aggregated answer"
        return "worker evidence"


def test_local_graph_runs_parallel_workers_and_aggregates():
    provider = FakeProvider()
    answer = _local_graph_answer(provider, "Design and review a robust parser with tests and failure handling.")
    assert answer == "aggregated answer"
    assert len(provider.calls) == 5
    assert any(prompt.startswith("Synthesize") for prompt in provider.calls)
