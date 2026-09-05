from pathlib import Path

from sophyane.arc_agi3 import ArcRSIMemory, SophyaneArcAgent, capability_rank, parse_decision, run_game
from sophyane.arc_ecosystem import BadrpkArcEcosystem


class Action:
    def __init__(self, name): self.name = name


class State:
    def __init__(self, name): self.name = name


class Observation:
    def __init__(self, state="PLAYING", frame=None):
        self.state = State(state)
        self.frame = frame or [[0, 1], [1, 0]]


class Environment:
    action_space = [Action("ACTION1"), Action("ACTION6")]
    def __init__(self): self.steps = 0
    @property
    def observation_space(self): return Observation()
    def step(self, action, data=None, reasoning=None):
        self.steps += 1
        return Observation("WIN" if self.steps == 2 else "PLAYING", [[self.steps]])
    def reset(self): return Observation()


class Arcade:
    def __init__(self): self.env = Environment()
    def make(self, *args, **kwargs): return self.env
    def get_scorecard(self): return type("Score", (), {"score": 0.42, "card_id": "test-card"})()


def test_parse_decision_validates_and_bounds_coordinates():
    result = parse_decision('{"action":"ACTION6","data":{"x":99,"y":-2}}', [Action("ACTION1"), Action("ACTION6")])
    assert result.action == "ACTION6"
    assert result.data == {"x": 63, "y": 0}


def test_run_game_persists_rsi_trajectory_and_manual(tmp_path: Path):
    responses = iter(['{"action":"ACTION1","hypothesis":"moves token"}', '{"action":"ACTION1","hypothesis":"repeat reaches goal"}'])
    result = run_game(Arcade(), "ls20", SophyaneArcAgent(lambda *_: next(responses), ArcRSIMemory(tmp_path)), max_steps=2)
    assert result.wins == 1 and result.score == 0.42 and result.scorecard_id == "test-card"
    assert len((tmp_path / "ls20" / "trajectory.jsonl").read_text().splitlines()) == 2
    assert "repeat reaches goal" in (tmp_path / "ls20" / "manual.md").read_text()


def test_capability_rank_never_invents_a_score():
    rank = capability_rank(toolkit=True, real_frames=True, action_loop=True, durable_learning=True)
    assert rank["tier"] == "evaluation-ready" and rank["rhae"] is None


def test_badrpk_ecosystem_uses_neuron_change_and_xerus_memory(tmp_path: Path):
    neuron = tmp_path / "neuron/embodiment/perception"
    neuron.mkdir(parents=True)
    (neuron / "screen_change.py").write_text(
        "from dataclasses import dataclass\n"
        "@dataclass\nclass ScreenFingerprint: width:int; height:int; digest:str; samples:tuple\n"
        "@dataclass\nclass Change: changed:bool; distance:float\n"
        "def compare(a,b,threshold=0): return Change(a is None or a.digest != b.digest, 1.0 if a is None or a.digest != b.digest else 0.0)\n"
    )
    xerus = tmp_path / "xerus/src/xerus"
    xerus.mkdir(parents=True)
    (xerus / "memory.py").write_text(
        "items=[]\n"
        "def remember(content, **kw): items.append(dict(content=content, **kw)); return {'ok':True}\n"
        "def recall(query, namespace=None, limit=4): return [x for x in items if x.get('namespace') == namespace][-limit:]\n"
    )
    nifdu = tmp_path / "nifdu/include/nifdu"
    nifdu.mkdir(parents=True)
    (nifdu / "evidence_manifest.hpp").write_text("// contract")
    eco = BadrpkArcEcosystem(tmp_path / "state", nifdu_repo=tmp_path / "nifdu", neuron_repo=tmp_path / "neuron", xerus_repo=tmp_path / "xerus")
    before = eco.evidence("ls20", 1, Observation(frame=[[1, 1]]), {"frame": [[1, 1]]})
    after = eco.evidence("ls20", 1, Observation(frame=[[1, 2]]), {"frame": [[1, 2]]})
    assert all(value["available"] for value in eco.status().values())
    assert after.changed and after.change_distance == 1.0
    assert eco.remember("codex_cli", "ls20", before, "ACTION1", {}, after, "NOT_FINISHED")["ok"]
    assert eco.recall("codex_cli", "ls20", before)
