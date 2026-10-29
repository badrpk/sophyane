"""Bounded, reproducible 2-D incompressible Navier--Stokes experiments."""
from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class NavierStokesExecution:
    ok: bool
    capability_id: str
    text: str
    data: dict


def verify_vorticity_equation() -> dict:
    """Return a deterministic check of the standard smooth-solution identity.

    This records the algebraic structure and its scope; it is not a proof of
    global regularity for arbitrary three-dimensional data.
    """
    return {
        "ok": True,
        "equation": "domega_dt + (u·grad)omega = (omega·grad)u + nu Laplacian(omega)",
        "assumptions": ["smooth velocity", "divergence-free velocity", "viscosity nu > 0"],
        "terms": {
            "advection": {"expression": "(u·grad)omega", "sign": "plus_left"},
            "stretching": {"expression": "(omega·grad)u", "sign": "plus_right"},
            "diffusion": {"expression": "nu Laplacian(omega)", "sign": "plus_right"},
        },
        "scope": "identity_for_smooth_divergence_free_solutions",
        "not_proven": "unconditional_3d_global_regularity",
    }


def research_status() -> dict:
    """Describe the supported research boundary without overstating results."""
    return {
        "status": "open",
        "unconditional_3d_global_regularity": False,
        "supported_next_steps": [
            "bounded 2D simulation",
            "verify smooth-solution identities",
            "review conditional regularity criteria",
        ],
        "claim_boundary": "Numerical evidence and conditional identities are not an unconditional 3D proof.",
    }


def _periodic(values, i, j):
    n = len(values)
    return values[i % n][j % n]


def _laplacian(values, i, j, h):
    return (_periodic(values, i + 1, j) + _periodic(values, i - 1, j)
            + _periodic(values, i, j + 1) + _periodic(values, i, j - 1)
            - 4.0 * _periodic(values, i, j)) / (h * h)


def _velocity_from_vorticity(omega, h, iterations=80):
    n = len(omega)
    psi = [[0.0] * n for _ in range(n)]
    for _ in range(iterations):
        updated = [[0.0] * n for _ in range(n)]
        for i in range(n):
            for j in range(n):
                updated[i][j] = 0.25 * (
                    _periodic(psi, i + 1, j) + _periodic(psi, i - 1, j)
                    + _periodic(psi, i, j + 1) + _periodic(psi, i, j - 1)
                    + h * h * omega[i][j]
                )
        psi = updated
    u = [[(_periodic(psi, i, j + 1) - _periodic(psi, i, j - 1)) / (2 * h)
          for j in range(n)] for i in range(n)]
    v = [[-(_periodic(psi, i + 1, j) - _periodic(psi, i - 1, j)) / (2 * h)
          for j in range(n)] for i in range(n)]
    return u, v


def run_taylor_green(workspace: str | Path, *, grid_size=24, steps=20,
                     dt=0.001, viscosity=0.1) -> NavierStokesExecution:
    n, steps = int(grid_size), int(steps)
    if n < 8 or n > 96 or steps < 1 or steps > 500:
        raise ValueError("grid_size must be 8..96 and steps must be 1..500")
    if not math.isfinite(float(dt)) or not math.isfinite(float(viscosity)):
        raise ValueError("dt and viscosity must be finite")
    if dt <= 0 or viscosity < 0:
        raise ValueError("dt must be positive and viscosity cannot be negative")
    h = 2.0 * math.pi / n
    omega = [[2.0 * math.sin(i * h) * math.sin(j * h) for j in range(n)] for i in range(n)]
    u, v = _velocity_from_vorticity(omega, h)

    def energy(ux, vy):
        return sum((ux[i][j] ** 2 + vy[i][j] ** 2) * 0.5 for i in range(n) for j in range(n)) / (n * n)

    initial_energy = energy(u, v)
    energy_history = [initial_energy]
    max_divergence = 0.0
    for _ in range(steps):
        next_omega = [[0.0] * n for _ in range(n)]
        for i in range(n):
            for j in range(n):
                wx = (_periodic(omega, i, j + 1) - _periodic(omega, i, j - 1)) / (2 * h)
                wy = (_periodic(omega, i + 1, j) - _periodic(omega, i - 1, j)) / (2 * h)
                next_omega[i][j] = omega[i][j] + dt * (-u[i][j] * wx - v[i][j] * wy + viscosity * _laplacian(omega, i, j, h))
        omega = next_omega
        u, v = _velocity_from_vorticity(omega, h)
        for i in range(n):
            for j in range(n):
                divergence = abs(((_periodic(u, i, j + 1) - _periodic(u, i, j - 1))
                                  + (_periodic(v, i + 1, j) - _periodic(v, i - 1, j))) / (2 * h))
                max_divergence = max(max_divergence, divergence)
        energy_history.append(energy(u, v))

    final_energy = energy(u, v)
    final_vorticity_l2 = math.sqrt(sum(value * value for row in omega for value in row) / (n * n))
    stable = bool(
        math.isfinite(final_energy)
        and all(math.isfinite(value) for value in energy_history)
        and final_energy <= initial_energy * 1.001
        and max_divergence < 0.05
    )
    payload = {
        "ok": stable,
        "stability": "stable" if stable else "unstable",
        "capability": "fluid.navier_stokes.2d", "method": "periodic finite-difference vorticity solver",
        "case": "Taylor-Green vortex", "grid_size": n, "steps": steps, "dt": dt, "viscosity": viscosity,
        "initial_energy": initial_energy, "final_energy": final_energy,
        "energy_history": energy_history, "final_vorticity_l2": final_vorticity_l2,
        "max_divergence": max_divergence,
        "limitations": ["2D periodic domain", "bounded numerical experiment", "not a 3D proof"],
    }
    root = Path(workspace).expanduser().resolve(); root.mkdir(parents=True, exist_ok=True)
    (root / "navier-stokes-evidence.json").write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    text = json.dumps(payload, indent=2, sort_keys=True) + "\n3D proof: the existence and smoothness problem remains unsolved."
    return NavierStokesExecution(payload["ok"], payload["capability"], text, payload)


def unsupported_three_dimensional_request(workspace: str | Path) -> NavierStokesExecution:
    payload = {"ok": False, "capability": "fluid.navier_stokes.boundary", "status": "unsolved",
               "message": "The 3D Navier-Stokes existence and smoothness problem remains unsolved.",
               "next_steps": ["run a bounded 2D experiment", "check a special analytical case", "review known partial results"]}
    root = Path(workspace).expanduser().resolve(); root.mkdir(parents=True, exist_ok=True)
    (root / "navier-stokes-boundary.json").write_text(json.dumps(payload, indent=2) + "\n")
    return NavierStokesExecution(False, payload["capability"], json.dumps(payload, indent=2), payload)
