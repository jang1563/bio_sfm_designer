"""Temporary split-LTT compatibility for the published trust-core v0.1.0 tag."""

from __future__ import annotations

import math
from functools import lru_cache
from typing import Any, Dict, Optional, Sequence


def _check(risks: Sequence[float], wrong: Sequence[int]) -> None:
    if len(risks) != len(wrong):
        raise ValueError("risks and wrong must have equal length")
    if any(int(value) not in (0, 1) for value in wrong):
        raise ValueError("wrong values must be binary (0 or 1)")


def _probability(name: str, value: float) -> None:
    if not 0.0 < float(value) < 1.0:
        raise ValueError(f"{name} must be strictly between 0 and 1")


def _hoeffding(empirical: float, n: int, delta: float) -> float:
    return min(1.0, empirical + math.sqrt(math.log(1.0 / delta) / (2 * n)))


@lru_cache(maxsize=256)
def _log_binomial_coefficient(n: int, value: int) -> float:
    return math.log(math.comb(n, value))


def _binomial_boundary_pmf(value: int, n: int, probability: float) -> float:
    return math.exp(
        _log_binomial_coefficient(n, value)
        + value * math.log(probability)
        + (n - value) * math.log1p(-probability)
    )


def _binomial_lower_tail(k: int, n: int, probability: float) -> float:
    q = 1.0 - probability
    term = _binomial_boundary_pmf(k, n, probability)
    terms = [term]
    reverse_odds = q / probability
    for value in range(k, 0, -1):
        term *= (value / (n - value + 1)) * reverse_odds
        terms.append(term)
    return min(1.0, math.fsum(terms))


def _binomial_upper_tail(k: int, n: int, probability: float) -> float:
    q = 1.0 - probability
    first = k + 1
    term = _binomial_boundary_pmf(first, n, probability)
    terms = [term]
    odds = probability / q
    for value in range(first, n):
        term *= ((n - value) / (value + 1)) * odds
        terms.append(term)
    return min(1.0, math.fsum(terms))


def _binomial_cdf(k: int, n: int, probability: float) -> float:
    if k >= n:
        return 1.0
    if probability <= 0.0:
        return 1.0
    if probability >= 1.0:
        return 0.0
    if k < (n + 1) * probability:
        return _binomial_lower_tail(k, n, probability)
    return max(0.0, 1.0 - _binomial_upper_tail(k, n, probability))


def _binomial_survival(k: int, n: int, probability: float) -> float:
    if k >= n:
        return 0.0
    if probability <= 0.0:
        return 0.0
    if probability >= 1.0:
        return 1.0
    if k >= (n + 1) * probability:
        return _binomial_upper_tail(k, n, probability)
    return max(0.0, 1.0 - _binomial_lower_tail(k, n, probability))


def clopper_pearson_upper_bound(false_accepts: int, n: int, delta: float = 0.1) -> float:
    _probability("delta", delta)
    if n <= 0:
        raise ValueError("n must be positive")
    if isinstance(false_accepts, bool) or int(false_accepts) != false_accepts:
        raise ValueError("false_accepts must be an integer")
    false_accepts = int(false_accepts)
    if not 0 <= false_accepts <= n:
        raise ValueError("false_accepts must be between 0 and n")
    if false_accepts == n:
        return 1.0
    low, high = 0.0, 1.0
    for _ in range(100):
        midpoint = (low + high) / 2.0
        if delta <= 0.5:
            cdf_exceeds_delta = _binomial_cdf(false_accepts, n, midpoint) > delta
        else:
            cdf_exceeds_delta = (
                _binomial_survival(false_accepts, n, midpoint) < 1.0 - delta
            )
        if cdf_exceeds_delta:
            low = midpoint
        else:
            high = midpoint
    return high


def _upper_bound(false_accepts: int, n: int, delta: float, bound: str) -> float:
    if bound == "hoeffding":
        return _hoeffding(false_accepts / n, n, delta)
    if bound == "clopper_pearson":
        return clopper_pearson_upper_bound(false_accepts, n, delta)
    raise ValueError("bound must be 'hoeffding' or 'clopper_pearson'")


def _select(risks: Sequence[float], wrong: Sequence[int], alpha: float) -> Optional[float]:
    pairs = sorted(zip([float(value) for value in risks], [int(value) for value in wrong]))
    best = None
    for tau in sorted({risk for risk, _ in pairs}):
        accepted = [label for risk, label in pairs if risk <= tau]
        if sum(accepted) / len(accepted) <= alpha:
            best = tau
    return best


def split_ltt_threshold(
    fit_risks: Sequence[float],
    fit_wrong: Sequence[int],
    certification_risks: Sequence[float],
    certification_wrong: Sequence[int],
    alpha: float,
    delta: float = 0.1,
    bound: str = "hoeffding",
) -> Dict[str, Any]:
    """Match trust-core v0.2 split selection and independent fixed-rule validation."""
    _check(fit_risks, fit_wrong)
    _check(certification_risks, certification_wrong)
    _probability("alpha", alpha)
    _probability("delta", delta)
    if bound not in ("hoeffding", "clopper_pearson"):
        raise ValueError("bound must be 'hoeffding' or 'clopper_pearson'")
    candidate = _select(fit_risks, fit_wrong, alpha)
    base = {
        "method": f"split_learn_then_test_{bound}",
        "tau_candidate": candidate,
        "alpha": float(alpha),
        "delta": float(delta),
        "n_fit": len(fit_risks),
        "n_certification": len(certification_risks),
    }
    if candidate is None:
        return {
            **base,
            "tau": None,
            "certified": False,
            "reason": "no_candidate_threshold_on_fit_split",
            "certification": None,
        }
    accepted = [
        int(label)
        for risk, label in zip(certification_risks, certification_wrong)
        if float(risk) <= candidate
    ]
    if not accepted:
        certification = {
            "tau": candidate,
            "n": len(certification_risks),
            "n_accepted": 0,
            "false_accepts": 0,
            "empirical_false_accept_rate": None,
            "ucb": None,
            "alpha": float(alpha),
            "delta": float(delta),
            "certified": False,
            "reason": "empty_certification_accept_set",
        }
    else:
        false_accepts = sum(accepted)
        empirical = false_accepts / len(accepted)
        ucb = _upper_bound(false_accepts, len(accepted), delta, bound)
        certified = ucb <= alpha
        certification = {
            "tau": candidate,
            "n": len(certification_risks),
            "n_accepted": len(accepted),
            "false_accepts": false_accepts,
            "empirical_false_accept_rate": empirical,
            "ucb": ucb,
            "alpha": float(alpha),
            "delta": float(delta),
            "certified": certified,
            "bound": bound,
            "reason": "certified" if certified else f"{bound}_ucb_exceeds_alpha",
        }
    certified = bool(certification["certified"])
    return {
        **base,
        "tau": candidate if certified else None,
        "certified": certified,
        "reason": certification["reason"],
        "certification": certification,
    }
