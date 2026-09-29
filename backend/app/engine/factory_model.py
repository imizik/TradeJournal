"""The strategy factory's learned filter: logistic regression, in plain Python.

Meta-labeling: a rule family decides when a setup exists; this model, trained
on that family's own past trades, estimates the chance a new one ends
positive, and the filter takes it only when that chance is at least the
training base rate. It is small on purpose. A few hundred trades a year
support a handful of coefficients, not a deep model, and each coefficient can
be read.

Features are standardized with the training means and deviations (a missing
value counts as the mean), the weights carry an L2 penalty (the intercept
does not), and the fit is Newton's method, so the same trades always give the
same model.

Pure: no network, no database, no third-party packages.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass


@dataclass(frozen=True)
class LogisticModel:
    features: tuple[str, ...]
    means: tuple[float, ...]
    scales: tuple[float, ...]
    intercept: float
    weights: tuple[float, ...]
    threshold: float
    trained_on: int

    def probability(self, row: Mapping[str, float]) -> float:
        z = self.intercept
        for name, mean, scale, weight in zip(self.features, self.means, self.scales, self.weights):
            value = row.get(name, math.nan)
            if not math.isnan(value):
                z += weight * (value - mean) / scale
        return _sigmoid(z)

    def takes(self, row: Mapping[str, float]) -> bool:
        return self.probability(row) >= self.threshold

    def to_json(self) -> dict:
        return {
            "kind": "logistic",
            "features": list(self.features),
            "means": list(self.means),
            "scales": list(self.scales),
            "intercept": self.intercept,
            "weights": list(self.weights),
            "threshold": self.threshold,
            "trained_on": self.trained_on,
        }

    @classmethod
    def from_json(cls, data: Mapping) -> LogisticModel:
        return cls(
            tuple(data["features"]),
            tuple(float(v) for v in data["means"]),
            tuple(float(v) for v in data["scales"]),
            float(data["intercept"]),
            tuple(float(v) for v in data["weights"]),
            float(data["threshold"]),
            int(data["trained_on"]),
        )


def _sigmoid(z: float) -> float:
    if z >= 0:
        return 1 / (1 + math.exp(-z))
    e = math.exp(z)
    return e / (1 + e)


def _solve(matrix: list[list[float]], vector: list[float]) -> list[float]:
    """Gaussian elimination with partial pivoting."""
    n = len(vector)
    a = [row[:] + [vector[k]] for k, row in enumerate(matrix)]
    for col in range(n):
        pivot = max(range(col, n), key=lambda r: abs(a[r][col]))
        if abs(a[pivot][col]) < 1e-12:
            raise ValueError("singular system")
        a[col], a[pivot] = a[pivot], a[col]
        for r in range(col + 1, n):
            factor = a[r][col] / a[col][col]
            if factor:
                for c in range(col, n + 1):
                    a[r][c] -= factor * a[col][c]
    solution = [0.0] * n
    for r in range(n - 1, -1, -1):
        solution[r] = (a[r][n] - sum(a[r][c] * solution[c] for c in range(r + 1, n))) / a[r][r]
    return solution


def fit_logistic(
    rows: Sequence[Mapping[str, float]],
    labels: Sequence[int],
    features: Sequence[str],
    l2: float = 1.0,
    iterations: int = 100,
) -> LogisticModel:
    """Fit P(label = 1) on `features` of `rows`."""
    if len(rows) != len(labels) or not rows:
        raise ValueError("need one label per row and at least one row")
    means, scales = [], []
    for name in features:
        present = [row.get(name, math.nan) for row in rows]
        present = [v for v in present if not math.isnan(v)]
        mean = sum(present) / len(present) if present else 0.0
        variance = sum((v - mean) ** 2 for v in present) / len(present) if present else 0.0
        means.append(mean)
        scales.append(math.sqrt(variance) if variance > 0 else 1.0)
    x = []
    for row in rows:
        values = [1.0]
        for name, mean, scale in zip(features, means, scales):
            value = row.get(name, math.nan)
            values.append(0.0 if math.isnan(value) else (value - mean) / scale)
        x.append(values)
    width = len(features) + 1
    beta = [0.0] * width
    base_rate = sum(labels) / len(labels)
    if 0 < base_rate < 1:
        beta[0] = math.log(base_rate / (1 - base_rate))
    for _ in range(iterations):
        gradient = [0.0] * width
        hessian = [[0.0] * width for _ in range(width)]
        for values, label in zip(x, labels):
            p = _sigmoid(sum(b * v for b, v in zip(beta, values)))
            weight = p * (1 - p)
            for r in range(width):
                gradient[r] += (label - p) * values[r]
                wr = weight * values[r]
                for c in range(r, width):
                    hessian[r][c] += wr * values[c]
        for r in range(width):
            for c in range(r):
                hessian[r][c] = hessian[c][r]
        for k in range(1, width):
            gradient[k] -= l2 * beta[k]
            hessian[k][k] += l2
        step = _solve(hessian, gradient)
        beta = [b + s for b, s in zip(beta, step)]
        if max(abs(s) for s in step) < 1e-10:
            break
    return LogisticModel(
        features=tuple(features),
        means=tuple(means),
        scales=tuple(scales),
        intercept=beta[0],
        weights=tuple(beta[1:]),
        threshold=base_rate,
        trained_on=len(rows),
    )
