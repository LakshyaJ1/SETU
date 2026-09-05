"""SVO -- the Spectral Virtual Odometer.

Speed from the frequency of the axle harmonics rather than from integrating
acceleration. The distinction is the whole point: an integrated speed inherits
accelerometer bias and its error *grows*, while a speed read off a frequency
has error ``e_v = df0 / f0`` set by the spectral estimator and by nothing that
elapsed time can make worse.

The scale ``k_svo = 2 pi R_eff`` is the one remaining unknown. It drifts on the
timescale of tyre pressure and load -- minutes to days, not seconds -- so it is
carried as a slowly-varying state and calibrated by CTS in turns and by GNSS
when available. That is what makes the scheme self-calibrating without a
vehicle bus.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from ..sensors.types import ImuStream, tier_for_rate
from ..signal.spectral import harmonic_sum, stft_magnitude, track_ridge
from .types import ScalarMeasurement

__all__ = ["SvoConfig", "SvoResult", "SpectralOdometer"]


@dataclass(frozen=True)
class SvoConfig:
    """Tuning. Defaults follow docs/03-approach.md 3.3."""

    window_s: float = 2.56
    hop_s: float = 0.1
    f_min: float = 1.5
    f_max: float = 45.0
    df: float = 0.02
    n_orders: int = 8
    min_speed_mps: float = 4.0  # below this the fundamental is too low to resolve
    min_confidence: float = 0.05
    scale_sigma_rel: float = 0.02  # 1-sigma uncertainty in R_eff before calibration
    max_accel_mps2: float = 4.0  # bounds the frame-to-frame frequency prior


@dataclass(frozen=True)
class SvoResult:
    """Speed estimate plus the intermediate quantities worth inspecting."""

    speed: ScalarMeasurement
    f0: np.ndarray
    sigma_f0: np.ndarray
    confidence: np.ndarray
    available: bool
    reason: str = ""


class SpectralOdometer:
    """Estimate ground speed from the axle-harmonic family.

    ``k_svo`` is ``2 pi R_eff``; pass the current filter estimate. It is a
    multiplicative scale on the output, so a wrong value is a pure scale error
    -- which is exactly why CTS has to observe it rather than it being a
    constant compiled into the code.
    """

    def __init__(self, k_svo: float, config: SvoConfig | None = None) -> None:
        if k_svo <= 0:
            raise ValueError("k_svo must be positive")
        self.k_svo = float(k_svo)
        self.cfg = config or SvoConfig()

    def _nyquist_ok(self, rate_hz: float) -> tuple[bool, str]:
        """Whether this device can see the axle family at all.

        A Tier C stream is not merely degraded here. Its anti-alias filter has
        removed the lines before they were ever reported, so refusing is the
        only honest answer (``docs/04-architecture.md`` 4.3).
        """
        tier = tier_for_rate(rate_hz)
        if tier in ("C", "D"):
            return False, f"tier {tier} ({rate_hz:.0f} Hz): axle harmonics are below Nyquist"
        return True, ""

    def estimate(
        self,
        imu: ImuStream,
        *,
        a_long: np.ndarray | None = None,
        speed_hint: np.ndarray | None = None,
    ) -> SvoResult:
        """Run the front-end over an IMU stream.

        ``a_long`` is the longitudinal acceleration, used as the physical
        transition prior in the ridge tracker: the axle frequency can only
        change as fast as the vehicle can accelerate, so an octave slip implies
        an acceleration that did not happen. Supplying it is the single largest
        contributor to robustness here.

        ``speed_hint`` narrows the search around an independent estimate. It is
        optional and deliberately weak -- SVO must be able to stand alone, or it
        adds no information to the filter that fed it the hint.
        """
        rate = imu.rate_hz
        ok, reason = self._nyquist_ok(rate)
        empty = ScalarMeasurement(
            np.zeros(0), np.zeros(0), np.zeros(0), np.zeros(0, dtype=bool), "svo"
        )
        if not ok:
            return SvoResult(empty, np.zeros(0), np.zeros(0), np.zeros(0), False, reason)

        cfg = self.cfg
        # Magnitude, not a single axis: the mount rotation is unknown, and the
        # magnitude is invariant to it. This is what lets SVO run before ACE has
        # converged.
        mag = np.linalg.norm(imu.accel, axis=1)
        spec = stft_magnitude(mag, rate, window_s=cfg.window_s, hop_s=cfg.hop_s)

        f_max = min(cfg.f_max, 0.45 * rate)
        if f_max <= cfg.f_min:
            return SvoResult(empty, np.zeros(0), np.zeros(0), np.zeros(0), False, "band too narrow")
        f0_grid = np.arange(cfg.f_min, f_max, cfg.df)

        # Only sum orders that fit below Nyquist, or the score is diluted by
        # bands that contain nothing but noise.
        n_orders = int(np.clip(np.floor(0.45 * rate / cfg.f_min), 1, cfg.n_orders))
        score = harmonic_sum(spec, f0_grid, n_orders=n_orders)

        if speed_hint is not None:
            hint = np.interp(spec.t, imu.t, speed_hint) / self.k_svo
            # A gentle Gaussian preference, ~2 Hz wide. Wide enough that SVO can
            # still disagree with the hint, which is the point of having it.
            penalty = ((f0_grid[:, None] - hint[None, :]) / 2.0) ** 2
            score = score - 0.15 * penalty

        expected_df = None
        if a_long is not None:
            a_frame = np.interp(spec.t, imu.t, np.asarray(a_long, dtype=float))
            a_frame = np.clip(a_frame, -cfg.max_accel_mps2, cfg.max_accel_mps2)
            dt = float(np.median(np.diff(spec.t))) if len(spec.t) > 1 else cfg.hop_s
            expected_df = a_frame * dt / self.k_svo

        track = track_ridge(
            score,
            f0_grid,
            spec.t,
            max_rate_hz_per_s=cfg.max_accel_mps2 / self.k_svo,
            expected_df=expected_df,
        )

        v = self.k_svo * track.f0
        # Two independent contributions: the frequency estimate, and the scale.
        # Before calibration the scale dominates, which is precisely the
        # observation that motivates the CTS handshake.
        sigma = np.sqrt(
            (self.k_svo * track.sigma_f0) ** 2 + (cfg.scale_sigma_rel * v) ** 2
        )
        # An earlier version scaled sigma by (1 - confidence) to guard against a
        # confidently-wrong octave slip. It was removed, and the reason is worth
        # keeping: the prominence-based confidence typically sits around 0.08 for
        # a perfectly good lock, so "1 - confidence" inflated *every* estimate by
        # more than six times. SVO then lost every weighting contest against CTS,
        # and end-to-end drift went from 0.32 % to 0.89 % -- worse than the
        # classical baseline. The subharmonic failure that patch was guarding
        # against is fixed at its source by whitening in harmonic_sum, so the
        # guard is not needed; a metric whose scale is not calibrated must not be
        # used as if it were.

        valid = (
            (track.confidence >= cfg.min_confidence)
            & (v >= cfg.min_speed_mps)
            & np.isfinite(v)
        )
        return SvoResult(
            speed=ScalarMeasurement(t=track.t, value=v, sigma=sigma, valid=valid, source="svo"),
            f0=track.f0,
            sigma_f0=track.sigma_f0,
            confidence=track.confidence,
            available=True,
        )
