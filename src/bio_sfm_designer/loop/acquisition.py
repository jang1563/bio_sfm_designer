"""Acquisition functions for next-round parent selection (the 'Learn' step).

Greedy top-k EXPLOITS predicted quality only. ML-guided-design practice (ALDE, EVOLVEpro) notes
that top-k yields near-duplicate batches and motivates exploration (UCB / Thompson) on rugged
landscapes. These are provided as pluggable MECHANISM stubs: on the current synthetic landscape
greedy+elitism is in fact competitive and UCB/Thompson do NOT reliably beat it -- partly because
`sigma` here is ~(1 - quality) (see below), a crude exploration signal rather than a posterior
variance over the property. Whether exploration pays is an empirical question for real fitness data
(M4+). Each acquisition maps (mu, sigma, beta, rng) -> score:

    mu    = predicted quality (Prediction.value)
    sigma = uncertainty PROXY = the trust gate's CALIBRATED RISK, P(SFM wrong). This reuses the
            gate's own signal instead of inventing a second estimate, but in the calibrated regime
            it is ~(1 - quality), so it up-weights low-quality candidates -- a known limitation.
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
