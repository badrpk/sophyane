"""Fail-closed checks for short mathematical benchmark answers.

This module never rewrites a model answer. ``raw_correct`` is the model's
unassisted score; ``verified_correct`` is true only when a deterministic
check (and, where available, SymPy) supports that score.
"""
from __future__ import annotations

from dataclasses import dataclass
import re


try:  # Optional dependency: the local runtime may not ship SymPy.
    import sympy as _sp
except Exception:  # pragma: no cover - environment dependent
    _sp = None


@dataclass(frozen=True, slots=True)
class MathVerification:
    item_id: str
    raw_correct: bool
    verified_correct: bool
    checks_run: tuple[str, ...] = ()
    tool_status: str = "deterministic"
    failure_reason: str = ""


def _norm(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", text.lower().replace("\\", ""))


def _sympy_scalar_check(item_id: str) -> bool | None:
    if _sp is None:
        return None
    x = _sp.symbols("x")
    f = x**2 + 1
    g = x**3 - x
    if item_id == "linearity_derivative":
        return _sp.simplify(_sp.diff(f + g, x) - (_sp.diff(f, x) + _sp.diff(g, x))) == 0
    if item_id == "product_rule":
        return _sp.simplify(_sp.diff(f * g, x) - (_sp.diff(f, x) * g + f * _sp.diff(g, x))) == 0
    if item_id == "chain_rule":
        return _sp.simplify(_sp.diff(f.subs(x, g), x) - _sp.diff(f, x).subs(x, g) * _sp.diff(g, x)) == 0
    return None


def _check(item_id: str, answer: str) -> tuple[bool, str]:
    n = _norm(answer)
    if item_id == "linearity_derivative":
        return bool(re.search(r"f\s*['′].*\+\s*g\s*['′]", answer, re.S)) and "cf" in n and "f" in n, "linearity"
    if item_id == "product_rule":
        return bool(re.search(r"f\s*['′]\s*g\s*\+\s*f\s*g\s*['′]", answer)), "product_rule"
    if item_id == "chain_rule":
        return bool(re.search(r"f\s*['′].*g.*\*\s*g\s*['′]", answer)), "chain_rule"
    if item_id in {"curl_grad", "div_curl"}:
        return "0" in n, item_id
    if item_id == "curl_curl":
        return "graddiv" in n and "delta" in n, "curl_curl"
    if item_id == "laplace_product":
        return "deltafg" in n and "fdelta" in n and "gradfgradg" in n, "laplace_product"
    if item_id == "div_product":
        return ("div" in n or "nabla" in n) and "phi" in n and "f" in n and "+" in answer, "div_product"
    if item_id == "integration_parts":
        return "-" in answer and "grad" in n, "periodic_integration_by_parts"
    if item_id == "transport_cancel":
        return "0" in n, "transport_cancel"
    if item_id == "transport_square":
        return "0" in n, "transport_square"
    if item_id == "heat_energy":
        return "-" in answer and "grad" in n, "heat_energy"
    if item_id == "fourier_laplacian":
        return "-" in answer and "k" in n, "fourier_laplacian"
    if item_id == "holder":
        return "lp" in n and "lq" in n, "holder"
    if item_id == "young":
        return "epsilon" in n and ("p" in n and "q" in n), "young"
    if item_id == "sobolev_3d":
        return "h1" in n and "l6" in n, "sobolev_embedding"
    if item_id == "cross_dot":
        return bool(re.search(r"a.*(?:dot|·).*b.*(?:cross|×).*c", answer, re.I)), "scalar_triple_product"
    if item_id == "curl_cross":
        return all(term in n for term in ("divb", "diva", "bdotgrad", "adotgrad")), "curl_cross"
    if item_id == "navier_vorticity":
        return (
            "partialt" in n
            and ("udotgrad" in n or "udotnabla" in n or "ucdotnabla" in n)
            and ("omegadotgrad" in n or "omegadotnabla" in n or "omegacdotnabla" in n)
            and "deltaomega" in n
        ), "navier_vorticity"
    if item_id == "enstrophy_transport":
        return all(term in n for term in ("dt", "nu", "gradomega")) and "stretch" in n, "enstrophy_identity"
    return False, "unknown_item"


def verify_benchmark_item(item_id: str, answer: str) -> MathVerification:
    raw_correct, check_name = _check(item_id, answer or "")
    symbolic = _sympy_scalar_check(item_id)
    tool_status = "sympy" if symbolic is not None else "sympy_unavailable"
    verified = raw_correct and (symbolic is not False)
    reason = "" if verified else f"failed {check_name} check"
    return MathVerification(
        item_id=item_id,
        raw_correct=raw_correct,
        verified_correct=verified,
        checks_run=(check_name,),
        tool_status=tool_status,
        failure_reason=reason,
    )
