"""Statistics used to turn pass/fail counts into verdicts. Standard library only.

Everything here is small, exact where it can be, and seeded where it has to resample, so the same
run always produces the same report.
"""

from __future__ import annotations

import math
import random
from typing import Optional, Sequence

Z95 = 1.959963984540054


def wilson(successes: int, n: int, z: float = Z95) -> tuple:
    """Wilson score interval for a binomial proportion. Behaves at 0 and n, unlike the normal
    approximation, which matters for small eval suites."""
    if n <= 0:
        return (0.0, 1.0)
    p = successes / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    lo = 0.0 if successes == 0 else max(0.0, centre - half)
    hi = 1.0 if successes == n else min(1.0, centre + half)
    return (lo, hi)


def pass_at_k(n: int, c: int, k: int) -> float:
    """Probability that at least one of k runs (drawn from the n observed) passes."""
    if k > n:
        raise ValueError(f"k={k} exceeds the {n} runs observed")
    if n - c < k:
        return 1.0
    return 1.0 - math.comb(n - c, k) / math.comb(n, k)


def pass_hat_k(n: int, c: int, k: int) -> float:
    """Probability that all k runs (drawn from the n observed) pass: the reliability metric
    (tau-bench's pass^k). Unbiased estimator C(c, k) / C(n, k)."""
    if k > n:
        raise ValueError(f"k={k} exceeds the {n} runs observed")
    return math.comb(c, k) / math.comb(n, k)


def mcnemar_exact(b: int, c: int) -> float:
    """Two-sided exact McNemar p-value for paired binary outcomes.

    ``b`` = pairs that passed on the baseline and failed on the candidate (regressions),
    ``c`` = pairs that failed on the baseline and passed on the candidate (fixes).
    Under H0 the discordant pairs split 50/50, so this is a binomial test on min(b, c)."""
    n = b + c
    if n == 0:
        return 1.0
    k = min(b, c)
    tail = sum(math.comb(n, i) for i in range(k + 1)) / 2 ** n
    return min(1.0, 2 * tail)


def bootstrap_mean_diff(pairs: Sequence[tuple], iters: int = 5000, alpha: float = 0.05,
                        seed: int = 0) -> tuple:
    """Paired bootstrap interval for mean(candidate - baseline).

    ``pairs`` holds (baseline_score, candidate_score) per case; cases are resampled as units so the
    pairing (same case on both sides) is preserved. Returns (estimate, lo, hi)."""
    if not pairs:
        return (0.0, 0.0, 0.0)
    diffs = [float(cand) - float(base) for base, cand in pairs]
    n = len(diffs)
    est = sum(diffs) / n
    rng = random.Random(seed)
    means = sorted(sum(diffs[rng.randrange(n)] for _ in range(n)) / n for _ in range(iters))
    lo = means[int(math.floor(alpha / 2 * iters))]
    hi = means[min(iters - 1, int(math.ceil((1 - alpha / 2) * iters)) - 1)]
    return (est, lo, hi)


def bootstrap_mean(values: Sequence[float], iters: int = 5000, alpha: float = 0.05,
                   seed: int = 0) -> tuple:
    """Bootstrap interval for a mean. Used over per-case pass fractions, so repeats of one case
    (which are correlated) are resampled together. Returns (estimate, lo, hi)."""
    return bootstrap_mean_diff([(0.0, v) for v in values], iters, alpha, seed)


def cohen_kappa(a: Sequence, b: Sequence, labels: Optional[Sequence] = None) -> float:
    """Cohen's kappa between two raters over the same items. 1 = perfect agreement, 0 = chance."""
    if len(a) != len(b):
        raise ValueError("raters must label the same items")
    n = len(a)
    if n == 0:
        return float("nan")
    labels = list(labels) if labels is not None else sorted(set(a) | set(b), key=str)
    po = sum(x == y for x, y in zip(a, b)) / n
    pe = sum((list(a).count(lab) / n) * (list(b).count(lab) / n) for lab in labels)
    if pe >= 1.0:
        return 1.0 if po == 1.0 else 0.0
    return (po - pe) / (1 - pe)


def kappa_ci(a: Sequence, b: Sequence, iters: int = 2000, alpha: float = 0.05,
             seed: int = 0) -> tuple:
    """Bootstrap interval for Cohen's kappa (items resampled). Returns (kappa, lo, hi)."""
    k = cohen_kappa(a, b)
    n = len(a)
    if n < 2:
        return (k, float("nan"), float("nan"))
    labels = sorted(set(a) | set(b), key=str)
    rng = random.Random(seed)
    ks = []
    for _ in range(iters):
        idx = [rng.randrange(n) for _ in range(n)]
        ks.append(cohen_kappa([a[i] for i in idx], [b[i] for i in idx], labels))
    ks.sort()
    lo = ks[int(math.floor(alpha / 2 * iters))]
    hi = ks[min(iters - 1, int(math.ceil((1 - alpha / 2) * iters)) - 1)]
    return (k, lo, hi)


def describe_kappa(k: float) -> str:
    """Landis and Koch bands, used only as labels in reports."""
    if k != k:  # nan
        return "undefined"
    for bound, name in ((0.0, "poor"), (0.2, "slight"), (0.4, "fair"), (0.6, "moderate"),
                        (0.8, "substantial")):
        if k <= bound:
            return name
    return "almost perfect"
