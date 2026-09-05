"""Chassis vibration synthesis: the signal SVO reads.

``docs/03-approach.md`` 3.3 makes a strong claim -- that the accelerometer
already contains a wheel-speed sensor, in the frequency domain, and that every
published smartphone system throws it away by low-pass filtering at 5-20 Hz.
Testing that claim requires a vibration signal with the right structure, so this
module synthesises it from the physics rather than decorating the trace with
noise:

* **Axle orders** at ``k * f_ax`` where ``f_ax = v / (2 pi R_eff)``. These are
  rigidly proportional to ground speed -- tyre non-uniformity, imbalance, brake
  disc runout, hub bearing. This is the line SVO tracks.
* **The tread-block line** at ``N_blocks * f_ax``, usually the strongest feature
  but often above Nyquist on a phone.
* **Engine orders** at ``f_ax * i_diff * i_gear * n_order``. These are *not*
  proportional to speed: they jump discontinuously at every gear change, which
  is exactly what lets the two families be told apart for free.
* **Broadband road excitation**, a red-noise floor everything else sits on.

Frequency is accumulated as phase, ``phi(t) = 2 pi k \\int f_ax dt``, so the
instantaneous frequency is correct through acceleration. Synthesising with
``sin(2 pi f(t) t)`` instead is a classic error that produces a chirp of the
wrong rate and would make the ridge tracker look better than it is.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
from scipy.ndimage import gaussian_filter1d

from ..core.random_fields import smooth_field
from .vehicle import VehicleModel

__all__ = ["VibrationModel", "ROAD_SMOOTH", "ROAD_NORMAL", "ROAD_ROUGH", "synthesize_vibration"]


@dataclass(frozen=True)
class VibrationModel:
    """Road surface and driveline character.

    Amplitudes are in m/s^2 at the reference speed and scale as ``sqrt(v)``,
    which is the usual approximation for tyre-road excitation.
    """

    name: str
    road_floor: float  # broadband road noise, m/s^2 RMS
    axle_amp: float  # amplitude of axle order 1
    axle_orders: tuple[int, ...] = (1, 2, 3, 4, 5, 6, 8, 10)
    order_decay: float = 0.72  # amplitude ratio between successive orders
    tread_amp: float = 0.05
    engine_amp: float = 0.22
    v_ref: float = 16.67
    gear_ratios: tuple[float, ...] = (3.55, 2.04, 1.38, 1.0, 0.79)
    final_drive: float = 3.9
    shift_speeds: tuple[float, ...] = (4.5, 8.5, 13.0, 19.0)
    # Fraction of the vibration appearing on each vehicle axis. Vertical
    # dominates: the wheel pushes the body up, not forward.
    axis_gain: tuple[float, float, float] = field(default=(0.35, 0.30, 1.0))


ROAD_SMOOTH = VibrationModel(
    name="smooth", road_floor=0.045, axle_amp=0.055, tread_amp=0.02, engine_amp=0.16
)
ROAD_NORMAL = VibrationModel(name="normal", road_floor=0.11, axle_amp=0.14)
ROAD_ROUGH = VibrationModel(
    name="rough", road_floor=0.30, axle_amp=0.26, tread_amp=0.09, engine_amp=0.30
)


def _gear_index(v: np.ndarray, shift_speeds: tuple[float, ...]) -> np.ndarray:
    """Selected gear (0-based) for each speed, with hysteresis-free thresholds."""
    return np.searchsorted(np.asarray(shift_speeds), v, side="right")


def synthesize_vibration(
    t: np.ndarray,
    v: np.ndarray,
    vehicle: VehicleModel,
    model: VibrationModel,
    rng: np.random.Generator,
) -> tuple[np.ndarray, dict[str, np.ndarray]]:
    """Return ``(vibration_xyz, diagnostics)`` in the vehicle frame, m/s^2.

    ``diagnostics`` carries the true axle frequency and gear index so that a
    test can score a frequency estimate against the value that generated it --
    the only way to separate "SVO tracked the right line" from "SVO tracked a
    line".
    """
    t = np.asarray(t, dtype=float)
    v = np.asarray(v, dtype=float)
    n = len(t)
    dt = float(np.median(np.diff(t))) if n > 1 else 0.005

    # Axle rotation frequency: the quantity the whole method rests on.
    f_ax = np.maximum(v, 0.0) / vehicle.k_svo

    # Excitation grows with speed; sqrt keeps it from dominating at motorway
    # speed while still vanishing at a standstill.
    speed_gain = np.sqrt(np.clip(v, 0.0, None) / model.v_ref + 1e-6)

    # Slow amplitude modulation: surface texture changes every few tens of
    # metres, so a constant-amplitude tone would be unrealistically easy to find.
    am = 1.0 + smooth_field(rng, n, max(0.6 / dt, 1.0), amplitude=0.35)
    am = np.clip(am, 0.25, 2.5)

    signal = np.zeros(n)

    def add_tone(freq: np.ndarray, amp: np.ndarray) -> None:
        """Add a tone whose instantaneous frequency is ``freq``."""
        phase = 2.0 * np.pi * np.cumsum(freq) * dt + rng.uniform(0, 2 * np.pi)
        signal[:] += amp * np.sin(phase)

    # -- axle family --------------------------------------------------------
    for order in model.axle_orders:
        amp = model.axle_amp * (model.order_decay ** (order - 1)) * speed_gain * am
        add_tone(order * f_ax, amp)

    # Tread-block passing frequency: strong, but N_blocks * f_ax is above a
    # phone's Nyquist at any normal speed, so it is mostly of academic interest.
    add_tone(vehicle.n_tread_blocks * f_ax, model.tread_amp * speed_gain * am)

    # -- engine family ------------------------------------------------------
    # The discontinuity at a gear change is the free label for family
    # disambiguation (docs/03-approach.md 3.3).
    gear = _gear_index(v, model.shift_speeds)
    ratios = np.asarray(model.gear_ratios)
    i_gear = ratios[np.clip(gear, 0, len(ratios) - 1)]
    f_engine_rev = f_ax * model.final_drive * i_gear
    for k, order in enumerate(vehicle.engine_orders):
        add_tone(f_engine_rev * order, model.engine_amp * (0.6**k) * speed_gain * am)

    # -- broadband road floor ----------------------------------------------
    # Red noise: road roughness has more energy at low frequency. Built by
    # low-pass filtering white noise and mixing a little of the white back in.
    white = rng.normal(size=n)
    red = gaussian_filter1d(white, sigma=max(0.012 / dt, 1.0))
    red *= model.road_floor / (np.std(red) + 1e-12)
    signal += red * speed_gain + white * model.road_floor * 0.28 * speed_gain

    gains = np.asarray(model.axis_gain, dtype=float)
    # Decorrelate the axes slightly; a perfectly rank-1 vibration would let a
    # projection trivially recover the signal.
    vib = signal[:, None] * gains[None, :]
    vib += rng.normal(size=(n, 3)) * model.road_floor * 0.12 * speed_gain[:, None]

    return vib, {"f_ax": f_ax, "gear": gear.astype(int), "f_engine_rev": f_engine_rev}
