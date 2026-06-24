"""Acquisition functions for next-round parent selection (the 'Learn' step).

Greedy top-k EXPLOITS predicted quality only. ML-guided-design practice (ALDE, EVOLVEpro) is
blunt that top-k yields near-duplicate batches and that exploration — UCB and Thompson sampling
— matters on rugged fitness landscapes. Each acquisition maps (mu, sigma, beta, rng) -> score:

    mu    = predicted quality (Prediction.value)
    sigma = uncertainty proxy = the trust gate's CALIBRATED RISK, P(SFM wrong). A candidate the
            gate is unsure about is an exploration target; this reuses the gate's own signal
            rather than inventing a second uncertainty estimate.
    beta  = exploration weight.
    rng   = a seeded RNG (Thompson only), so a campaign is reproducible.

Higher score = preferred parent.
"""

from __future__ import annotations

import random


def _greedy(mu: float, sigma: float, beta: float, rng: random.Random) -> float:
    return mu                                   # pure exploitation


def _ucb(mu: float, sigma: float, beta: float, rng: random.Random) -> float:
    return mu + beta * sigma                    # optimism under uncertainty


def _thompson(mu: float, sigma: float, beta: float, rng: random.Random) -> float:
    return rng.gauss(mu, max(beta * sigma, 1e-9))   # a posterior draw; explore via sampling


ACQUISITIONS = {"greedy": _greedy, "ucb": _ucb, "thompson": _thompson}


def hamming(a: str, b: str) -> int:
    """Hamming distance over the common prefix plus any length difference."""
    n = min(len(a), len(b))
    return sum(a[i] != b[i] for i in range(n)) + abs(len(a) - len(b))
