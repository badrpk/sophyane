import json


def test_taylor_green_run_is_finite_divergence_free_and_dissipative(tmp_path):
    from sophyane.navier_stokes_capability import run_taylor_green
    result = run_taylor_green(tmp_path, grid_size=16, steps=8, dt=0.002, viscosity=0.1)
    assert result.ok is True
    assert result.data["capability"] == "fluid.navier_stokes.2d"
    assert result.data["max_divergence"] < 0.05
    assert result.data["final_energy"] <= result.data["initial_energy"]
    json.loads((tmp_path / "navier-stokes-evidence.json").read_text())


def test_navier_stokes_request_routes_to_deterministic_capability(tmp_path):
    from sophyane.capability_executors import execute_deterministic_capability
    result = execute_deterministic_capability("simulate a 2D Taylor-Green Navier-Stokes flow", workspace=tmp_path)
    assert result is not None and result.capability_id == "fluid.navier_stokes.2d"
    assert result.ok is True and "3D proof" in result.text


def test_common_navier_stroke_typo_also_routes(tmp_path):
    from sophyane.capability_executors import execute_deterministic_capability
    result = execute_deterministic_capability("solve navier stroke problem", workspace=tmp_path)
    assert result is not None and result.capability_id == "fluid.navier_stokes.2d"


def test_navier_stokes_capability_refuses_unsupported_3d_proof_claim(tmp_path):
    from sophyane.capability_executors import execute_deterministic_capability
    result = execute_deterministic_capability("solve the 3D Navier-Stokes existence and smoothness problem", workspace=tmp_path)
    assert result is not None and result.capability_id == "fluid.navier_stokes.boundary"
    assert result.ok is False and "unsolved" in result.text.lower()
