"""Spectral front-end: STFT, harmonic summation and Viterbi ridge tracking.

This is the signal-processing half of SVO (``docs/03-approach.md`` 3.3). The
claim it implements is that a rolling wheel is a rotating machine bolted to the
chassis, so the accelerometer already contains a wheel-speed sensor -- in the
frequency domain, at ``f_ax = v / (2 pi R_eff)`` and its harmonics.

Three pieces, in order:

**Harmonic summation** scores a candidate fundamental by the energy at all of
its harmonics at once. A single peak-pick would lock onto whichever order
happens to be loudest in the current window, which changes with road surface
and speed; summing over orders is what makes the estimate stable.

**Ridge tracking** then resolves the ambiguity harmonic summation cannot: the
score at ``f0/2`` and ``2*f0`` is nearly as good as at ``f0``, because a
subharmonic's harmonic set contains the true one. Octave slips are *the*
classic failure of pitch trackers. A Viterbi pass over frames with a transition
prior fixes it, and when the longitudinal accelerometer channel is available
the prior becomes a physical one -- the axle frequency can only change as fast
as the vehicle can accelerate.

**Uncertainty** comes from the sharpness of the summed peak, so the estimate
arrives with a calibrated sigma rather than a tuned constant. Without that, a
good speed with a bad covariance still destroys the filter.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

__all__ = [
    "SpectrogramResult",
    "RidgeTrack",
    "stft_magnitude",
    "harmonic_sum",
    "track_ridge",
    "parabolic_refine",
]


@dataclass(frozen=True)
class SpectrogramResult:
    """Short-time power spectrum."""

    t: np.ndarray  # (T,) window centre times, s
    f: np.ndarray  # (F,) bin frequencies, Hz
    power: np.ndarray  # (F, T) power, linear


@dataclass(frozen=True)
class RidgeTrack:
    """A tracked fundamental frequency with per-frame uncertainty."""

    t: np.ndarray  # (T,)
    f0: np.ndarray  # (T,) Hz
    sigma_f0: np.ndarray  # (T,) Hz, 1-sigma
    score: np.ndarray  # (T,) harmonic-sum score at the chosen frequency
    confidence: np.ndarray  # (T,) 0..1, peak prominence against the runner-up


def stft_magnitude(
    x: np.ndarray,
    rate_hz: float,
    *,
    window_s: float = 2.56,
    hop_s: float = 0.1,
    detrend_s: float = 0.5,
) -> SpectrogramResult:
    """Power spectrogram of a one-dimensional signal.

    The default 2.56 s window is the one specified in ``docs/03-approach.md``
    3.3: it buys a 0.39 Hz raw bin spacing, which parabolic interpolation then
    refines by roughly an order of magnitude. Longer would resolve better but
    would smear the estimate across real acceleration.

    ``detrend_s`` removes the slow component -- gravity and vehicle
    acceleration -- which otherwise dominates the low-frequency bins and leaks
    across the whole band through the window sidelobes.
    """
    x = np.asarray(x, dtype=float).ravel()
    n_win = max(int(round(window_s * rate_hz)), 16)
    n_hop = max(int(round(hop_s * rate_hz)), 1)
    if len(x) < n_win:
        raise ValueError(f"signal of {len(x)} samples is shorter than the {n_win}-sample window")

    # Remove the slow-moving mean with a boxcar high-pass. A cumulative-sum
    # moving average is exact and O(n).
    k = max(int(round(detrend_s * rate_hz)), 1)
    if k > 1:
        pad = np.concatenate([np.full(k // 2, x[0]), x, np.full(k - k // 2, x[-1])])
        csum = np.concatenate([[0.0], np.cumsum(pad)])
        moving = (csum[k:] - csum[:-k]) / k
        x = x - moving[: len(x)]

    starts = np.arange(0, len(x) - n_win + 1, n_hop)
    window = np.hanning(n_win)
    # Zero-pad by 2x so the parabolic refinement has a well-sampled peak shape.
    n_fft = int(2 ** np.ceil(np.log2(n_win * 2)))

    frames = np.lib.stride_tricks.sliding_window_view(x, n_win)[starts] * window
    spec = np.fft.rfft(frames, n=n_fft, axis=1)
    power = (np.abs(spec) ** 2).T  # (F, T)

    f = np.fft.rfftfreq(n_fft, d=1.0 / rate_hz)
    t = (starts + n_win / 2.0) / rate_hz
    return SpectrogramResult(t=t, f=f, power=power)


def harmonic_sum(
    spec: SpectrogramResult,
    f0_grid: np.ndarray,
    *,
    n_orders: int = 8,
    order_weight: float = 0.85,
    log_compress: bool = True,
) -> np.ndarray:
    """Score every candidate fundamental by the energy at all of its harmonics.

    Returns ``(len(f0_grid), n_frames)``.

    Log compression matters more than it looks. Raw power is dominated by
    whichever single order is loudest, so the sum degenerates into a peak-pick
    on that order; compressing first makes the score reward *agreement across
    orders*, which is the property that distinguishes a real harmonic family
    from a loud isolated tone.
    """
    f0_grid = np.asarray(f0_grid, dtype=float)
    p = spec.power
    if log_compress:
        p = np.log1p(p / (np.median(p) + 1e-30))

    orders = np.arange(1, n_orders + 1)
    weights = order_weight ** (orders - 1)
    weights /= weights.sum()

    # Bilinear lookup of p at k*f0 for every (order, candidate) pair at once.
    df = spec.f[1] - spec.f[0]
    targets = np.outer(f0_grid, orders) / df  # (G, K) in fractional bin units
    lo = np.floor(targets).astype(int)
    frac = targets - lo
    valid = (lo >= 0) & (lo + 1 < len(spec.f))
    lo_c = np.clip(lo, 0, len(spec.f) - 2)

    # (G, K, T) would be large; accumulate over orders instead.
    out = np.zeros((len(f0_grid), p.shape[1]))
    for k in range(len(orders)):
        interp = (1.0 - frac[:, k, None]) * p[lo_c[:, k]] + frac[:, k, None] * p[lo_c[:, k] + 1]
        out += weights[k] * np.where(valid[:, k, None], interp, 0.0)
    return out


def parabolic_refine(grid: np.ndarray, values: np.ndarray, idx: int) -> tuple[float, float]:
    """Sub-bin peak location and curvature by fitting a parabola to three points.

    Returns ``(location, curvature)``. Curvature is negative at a maximum and
    its magnitude sets the uncertainty: a sharp peak is a confident estimate.
    """
    if idx <= 0 or idx >= len(grid) - 1:
        return float(grid[idx]), 0.0
    y0, y1, y2 = values[idx - 1], values[idx], values[idx + 1]
    denom = y0 - 2.0 * y1 + y2
    if abs(denom) < 1e-30:
        return float(grid[idx]), 0.0
    delta = 0.5 * (y0 - y2) / denom
    delta = float(np.clip(delta, -1.0, 1.0))
    step = grid[idx + 1] - grid[idx]
    return float(grid[idx] + delta * step), float(denom / (step * step))


def track_ridge(
    score: np.ndarray,
    f0_grid: np.ndarray,
    t: np.ndarray,
    *,
    max_rate_hz_per_s: float = 3.0,
    transition_weight: float = 0.6,
    expected_df: np.ndarray | None = None,
) -> RidgeTrack:
    """Viterbi over frames, choosing the most consistent frequency path.

    ``expected_df`` is the physical prior: the frequency change the longitudinal
    accelerometer says should have happened between frames, ``a_long * dt /
    (2 pi R_eff)``. Supplying it is what rejects half- and double-frequency
    slips, because an octave jump implies an acceleration the vehicle did not
    experience. Without it the prior degrades to plain smoothness, which is
    weaker but still breaks most slips.
    """
    score = np.asarray(score, dtype=float)
    f0_grid = np.asarray(f0_grid, dtype=float)
    n_grid, n_frames = score.shape
    if n_frames == 0:
        empty = np.zeros(0)
        return RidgeTrack(empty, empty, empty, empty, empty)

    dt = float(np.median(np.diff(t))) if n_frames > 1 else 0.1
    step = f0_grid[1] - f0_grid[0]
    band = max(int(np.ceil(max_rate_hz_per_s * dt / step)), 1)

    # Normalise per frame so the path cost is not dominated by loud windows.
    emission = score - score.max(axis=0, keepdims=True)
    emission /= np.std(emission) + 1e-12

    total = np.empty((n_grid, n_frames))
    back = np.zeros((n_grid, n_frames), dtype=np.int32)
    total[:, 0] = emission[:, 0]

    offsets = np.arange(-band, band + 1)
    penalty = transition_weight * (offsets.astype(float) * step) ** 2

    for j in range(1, n_frames):
        shift = 0
        if expected_df is not None:
            shift = int(round(float(expected_df[j]) / step))
        best = np.full(n_grid, -np.inf)
        best_from = np.zeros(n_grid, dtype=np.int32)
        for o, pen in zip(offsets + shift, penalty, strict=False):
            prev = np.roll(total[:, j - 1], o)
            # Rolling wraps; invalidate the wrapped region.
            if o > 0:
                prev[:o] = -np.inf
            elif o < 0:
                prev[o:] = -np.inf
            cand = prev - pen
            better = cand > best
            best[better] = cand[better]
            best_from[better] = -o
        total[:, j] = emission[:, j] + best
        back[:, j] = np.clip(np.arange(n_grid) + best_from, 0, n_grid - 1)

    path = np.zeros(n_frames, dtype=int)
    path[-1] = int(np.argmax(total[:, -1]))
    for j in range(n_frames - 1, 0, -1):
        path[j - 1] = int(back[path[j], j])

    f0 = np.empty(n_frames)
    sigma = np.empty(n_frames)
    conf = np.empty(n_frames)
    chosen = np.empty(n_frames)
    for j, i in enumerate(path):
        loc, curv = parabolic_refine(f0_grid, score[:, j], i)
        f0[j] = loc
        chosen[j] = score[i, j]
        # A parabola fitted to a log-likelihood has curvature 1/sigma^2. The
        # floor keeps a flat, ambiguous peak from claiming a tiny sigma.
        sigma[j] = float(np.clip(np.sqrt(1.0 / max(-curv, 1e-9)), 0.25 * step, 5.0))
        # Prominence against the best competitor outside this peak's own lobe.
        mask = np.ones(n_grid, dtype=bool)
        mask[max(i - 3, 0) : i + 4] = False
        runner_up = float(score[mask, j].max()) if mask.any() else 0.0
        spread = float(score[:, j].max() - score[:, j].min()) + 1e-12
        conf[j] = float(np.clip((score[i, j] - runner_up) / spread, 0.0, 1.0))

    return RidgeTrack(t=np.asarray(t), f0=f0, sigma_f0=sigma, score=chosen, confidence=conf)
