"""The common shape of every measurement generator's output.

``docs/04-architecture.md`` 4.4 makes this the key interface: every generator
emits ``<value, covariance, validity, timestamp>`` and nothing else, which is
what lets the filter stay agnostic and lets a module be removed without the
estimator knowing. A generator that cannot produce a value at some epoch does
not raise and does not silently interpolate -- it marks the epoch invalid and
lets the filter carry on with whatever else is available.

The heteroscedastic sigma is not decoration. A good speed estimate delivered
with a bad covariance still destroys a Kalman filter, so a generator that
cannot say how wrong it might be is not usable.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

__all__ = ["ScalarMeasurement", "merge_inverse_variance"]


@dataclass(frozen=True)
class ScalarMeasurement:
    """A scalar observation with per-epoch uncertainty and validity."""

    t: np.ndarray  # (N,) seconds
    value: np.ndarray  # (N,)
    sigma: np.ndarray  # (N,) 1-sigma, same units as value
    valid: np.ndarray  # (N,) bool
    source: str = "unknown"

    def __post_init__(self) -> None:
        n = len(self.t)
        for name in ("value", "sigma", "valid"):
            arr = np.asarray(getattr(self, name))
            if arr.shape != (n,):
                raise ValueError(f"{name} must have shape ({n},), got {arr.shape}")
        object.__setattr__(self, "value", np.asarray(self.value, dtype=float))
        object.__setattr__(self, "sigma", np.asarray(self.sigma, dtype=float))
        object.__setattr__(self, "valid", np.asarray(self.valid, dtype=bool))

    def __len__(self) -> int:
        return len(self.t)

    @property
    def coverage(self) -> float:
        """Fraction of epochs this generator could actually speak to."""
        return float(self.valid.mean()) if len(self.valid) else 0.0

    def resampled_to(self, t_new: np.ndarray) -> ScalarMeasurement:
        """Nearest-neighbour resample onto another time grid.

        Nearest rather than linear: interpolating between a valid and an invalid
        epoch would manufacture a measurement where the generator said it had
        none, and interpolating sigma across a gap understates it.
        """
        t_new = np.asarray(t_new, dtype=float)
        if len(self.t) == 0:
            nan = np.full(len(t_new), np.nan)
            return ScalarMeasurement(
                t_new, nan, nan, np.zeros(len(t_new), dtype=bool), self.source
            )
        idx = np.clip(np.searchsorted(self.t, t_new), 0, len(self.t) - 1)
        left = np.clip(idx - 1, 0, len(self.t) - 1)
        take_left = np.abs(self.t[left] - t_new) < np.abs(self.t[idx] - t_new)
        idx = np.where(take_left, left, idx)
        return ScalarMeasurement(
            t=t_new,
            value=self.value[idx],
            sigma=self.sigma[idx],
            valid=self.valid[idx],
            source=self.source,
        )


def merge_inverse_variance(
    measurements: list[ScalarMeasurement],
    *,
    chi2_gate: float = 9.0,
    inflate: float = 3.0,
) -> ScalarMeasurement:
    """Fuse several estimates of the same scalar by inverse-variance weighting.

    ``docs/03-approach.md`` 3.4 specifies the posture explicitly: channels are
    combined *after* a pairwise consistency check, and a disagreement larger
    than three sigma raises the uncertainty of all of them rather than picking a
    winner. That is fault detection, not voting -- when SVO and CTS disagree,
    the honest conclusion is that something is wrong with one of them and we do
    not know which, so the fused estimate should widen, not gamble.
    """
    if not measurements:
        raise ValueError("nothing to merge")
    t = measurements[0].t
    for m in measurements:
        if not np.array_equal(m.t, t):
            raise ValueError("measurements must share a time grid; resample first")

    values = np.stack([m.value for m in measurements])
    sigmas = np.stack([m.sigma for m in measurements])
    valid = np.stack([m.valid for m in measurements]) & np.isfinite(values) & (sigmas > 0)

    weights = np.where(valid, 1.0 / np.maximum(sigmas, 1e-9) ** 2, 0.0)
    wsum = weights.sum(axis=0)
    any_valid = wsum > 0
    fused = np.where(any_valid, (weights * np.where(valid, values, 0.0)).sum(axis=0) / np.maximum(
        wsum, 1e-30
    ), np.nan)
    fused_sigma = np.where(any_valid, 1.0 / np.sqrt(np.maximum(wsum, 1e-30)), np.inf)

    # Pairwise consistency: the largest normalised disagreement at each epoch.
    n = len(measurements)
    worst = np.zeros_like(fused)
    for i in range(n):
        for j in range(i + 1, n):
            both = valid[i] & valid[j]
            if not both.any():
                continue
            denom = np.sqrt(sigmas[i] ** 2 + sigmas[j] ** 2)
            d = np.where(both, ((values[i] - values[j]) / np.maximum(denom, 1e-9)) ** 2, 0.0)
            worst = np.maximum(worst, d)

    inconsistent = worst > chi2_gate
    fused_sigma = np.where(inconsistent & any_valid, fused_sigma * inflate, fused_sigma)

    return ScalarMeasurement(
        t=t,
        value=fused,
        sigma=fused_sigma,
        valid=any_valid,
        source="+".join(m.source for m in measurements),
    )
