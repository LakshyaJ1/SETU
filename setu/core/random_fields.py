"""Smooth correlated random fields, without edge artefacts.

Several parts of the simulator need "a random signal that varies slowly": the
driver's free-flow speed, road-surface texture, magnetic anomalies, map
digitisation error. The obvious construction -- filter white noise with a wide
Gaussian and rescale to the wanted amplitude -- has a trap at the boundary.

``scipy.ndimage.gaussian_filter1d`` extends the input past its ends, and with
``mode="nearest"`` it does so by replicating the boundary *sample*. For a wide
kernel that means the output near the edge is dominated by one draw repeated
hundreds of times, so it barely averages at all while the interior averages
heavily. Rescaling by the whole array's standard deviation -- computed mostly
from that quiet interior -- then blows the edge up.

That is not hypothetical. It set the simulated driver's opening speed to
126 km/h against a 60 km/h cruise, a factor of 2.25, because the field's first
element came out at 1.25 where the interior spanned +-0.1. It also perturbed
the first metres of every map and every magnetic signature the same way.

The fix is to generate a longer field, filter it, and cut the padded ends off.
"""

from __future__ import annotations

import numpy as np
from scipy.ndimage import gaussian_filter1d

__all__ = ["smooth_field"]


def smooth_field(
    rng: np.random.Generator,
    n: int,
    sigma_samples: float,
    *,
    amplitude: float = 1.0,
    channels: int | None = None,
) -> np.ndarray:
    """A zero-mean, smoothly-varying random field of length ``n``.

    The result is scaled so its standard deviation equals ``amplitude``. The
    correlation length is ``sigma_samples``.

    ``channels`` returns an ``(n, channels)`` array whose columns are
    independent fields, each normalised separately.
    """
    if n <= 0:
        raise ValueError("n must be positive")
    sigma_samples = max(float(sigma_samples), 1e-6)

    # Pad by three correlation lengths at each end, then discard the padding.
    # Whatever the boundary handling does, it does it to samples we throw away.
    pad = int(np.ceil(3.0 * sigma_samples)) + 1
    total = n + 2 * pad

    shape = (total,) if channels is None else (total, channels)
    raw = rng.normal(size=shape)
    smoothed = gaussian_filter1d(raw, sigma=sigma_samples, axis=0, mode="reflect")
    core = smoothed[pad : pad + n]

    std = np.std(core, axis=0, keepdims=True)
    return core / np.where(std > 1e-12, std, 1.0) * amplitude
