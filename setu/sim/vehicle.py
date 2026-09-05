"""Vehicle models and the speed profile a driver would actually produce.

The distinction that matters here is roll behaviour, because it is what decides
which coordinated-turn relation CTS must use. A car's body rolls *outward* by a
couple of degrees on its suspension while the chassis stays essentially level,
so ``v = a_lat / Omega`` holds. A two-wheeler leans *into* the turn until the
resultant force runs along its own vertical, so its lateral accelerometer
channel reads approximately zero and the naive relation returns zero speed in
every turn (``docs/03-approach.md`` 3.4).

Getting that wrong is a silent 4 % scale error -- 40 m per km -- which is why
the vehicle class is a first-class model parameter and not a footnote.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy.ndimage import gaussian_filter1d

from ..core.constants import G0
from ..core.random_fields import smooth_field
from ..mapping.road import RoadPath

__all__ = ["VehicleModel", "CAR", "MOTORCYCLE", "SCOOTER", "BUS", "VEHICLES", "speed_profile"]


@dataclass(frozen=True)
class VehicleModel:
    """Physical parameters of the simulated vehicle."""

    name: str
    kind: str  # "car" | "two_wheeler"
    v_cruise: float  # m/s, free-flow target speed
    a_accel_max: float  # m/s^2
    a_brake_max: float  # m/s^2, positive magnitude
    a_lat_max: float  # m/s^2, comfort limit that sets curve speed
    wheel_radius_m: float  # R_eff, the effective rolling radius SVO calibrates
    roll_gain: float  # rad per m/s^2; used only when kind == "car"
    n_tread_blocks: int  # tread-block count, sets the f_tb line
    engine_orders: tuple[float, ...] = (2.0,)  # firing orders present in vibration

    @property
    def k_svo(self) -> float:
        """The spectral odometer scale, ``2 pi R_eff`` (a filter state)."""
        return 2.0 * np.pi * self.wheel_radius_m

    def roll_angle(self, a_lat: np.ndarray) -> np.ndarray:
        """Roll angle for a given lateral acceleration, in radians.

        Positive is a left lean. A two-wheeler's lean is exact -- it is set by
        force balance, not by a suspension constant -- so it uses ``arctan``
        rather than a linear gain.
        """
        a_lat = np.asarray(a_lat, dtype=float)
        if self.kind == "two_wheeler":
            return np.arctan2(a_lat, G0)
        return self.roll_gain * a_lat


# R_eff = 0.278 m rather than the ~0.30 m a tyre-sidewall calculation gives:
# that is the value recovered empirically from IO-VNBD's wheel speeds. Assuming
# the label value instead is an 8 % scale bias, which SVO would inherit whole.
CAR = VehicleModel(
    name="car",
    kind="car",
    v_cruise=16.67,  # 60 km/h
    a_accel_max=1.8,
    a_brake_max=2.6,
    a_lat_max=3.0,
    wheel_radius_m=0.278,
    roll_gain=-0.012,  # negative: the body leans out of the turn
    n_tread_blocks=72,
    engine_orders=(2.0, 4.0),
)

MOTORCYCLE = VehicleModel(
    name="motorcycle",
    kind="two_wheeler",
    v_cruise=15.0,
    a_accel_max=2.6,
    a_brake_max=3.2,
    a_lat_max=4.5,
    wheel_radius_m=0.31,
    roll_gain=0.0,  # unused; lean is computed from force balance
    n_tread_blocks=56,
    engine_orders=(1.0, 2.0),
)

SCOOTER = VehicleModel(
    name="scooter",
    kind="two_wheeler",
    v_cruise=11.0,
    a_accel_max=1.6,
    a_brake_max=2.6,
    a_lat_max=3.2,
    wheel_radius_m=0.20,  # 10-inch wheels: a much higher axle frequency
    roll_gain=0.0,
    n_tread_blocks=40,
    engine_orders=(1.0,),
)

BUS = VehicleModel(
    name="bus",
    kind="car",
    v_cruise=13.9,
    a_accel_max=1.0,
    a_brake_max=1.8,
    a_lat_max=2.0,
    wheel_radius_m=0.52,
    roll_gain=-0.022,  # tall and soft: more body roll than a car
    n_tread_blocks=96,
    engine_orders=(3.0,),
)

VEHICLES: dict[str, VehicleModel] = {
    v.name: v for v in (CAR, MOTORCYCLE, SCOOTER, BUS)
}


def speed_profile(
    path: RoadPath,
    vehicle: VehicleModel,
    *,
    dt: float = 0.02,
    v0: float | None = None,
    stops: tuple[float, ...] = (),
    stop_duration_s: float = 6.0,
    lookahead_m: float = 220.0,
    rng: np.random.Generator | None = None,
) -> tuple[np.ndarray, np.ndarray]:
    """Forward-simulate a plausible drive along ``path``.

    Returns ``(t, v)`` on a uniform ``dt`` grid. **Speed** is the primary output
    and the caller integrates it to get arc length, rather than the other way
    round. Differentiating a spline through ``s`` looks equivalent but is not:
    the driver model produces kinks at the hard-braking points, and a cubic
    spline overshoots a kink into *negative speed*. Integrating a smoothed speed
    cannot do that, and it keeps s, v and a exactly consistent, which matters
    because an inconsistent truth would reward or punish an estimator for the
    simulator's own error rather than its own.

    The driver model brakes for curves using a look-ahead over the braking
    distance, which is what produces the deceleration-into-a-bend followed by
    acceleration-out that makes CTS observable in the first place.
    """
    rng = rng or np.random.default_rng(0)
    v_cruise = vehicle.v_cruise * float(rng.uniform(0.92, 1.08))
    v_min = 0.6  # never integrate through exactly zero except at a scheduled stop

    # Curve-limited speed at every 1 m of the path, from the comfort limit.
    kappa_abs = np.abs(path.kappa) + 1e-9
    v_curve = np.sqrt(vehicle.a_lat_max / kappa_abs)

    # Stops are modelled as an extra speed limit that dips to zero at the stop
    # point, so the look-ahead brakes for them exactly as it does for a bend.
    v_limit = np.minimum(v_curve, v_cruise)
    for s_stop in stops:
        near = np.abs(path.s - s_stop) < 2.0
        v_limit = np.where(near, 0.0, v_limit)

    # Traffic, gradient and ordinary inattention mean nobody holds one speed for
    # a kilometre. A perfectly constant cruise would be an unrealistically easy
    # target for any velocity estimator -- there would be nothing to track -- so
    # the free-flow speed wanders slowly by about +-10 % with a ~15 s
    # correlation time.
    n_guess = int(6.0 * path.length / max(v_cruise, 1.0) / dt) + 4000
    wander = smooth_field(rng, n_guess, max(8.0 / dt, 1.0), amplitude=0.10)

    lookahead = np.arange(0.0, lookahead_m + 1.0, 2.0)
    v_hist: list[float] = []
    s = 0.0
    # Start in equilibrium with the wander. Seeding at the mean cruise speed
    # instead would open every run with a spurious hard brake back onto the
    # profile, which would then be the largest acceleration event in the log.
    v = float(v0 if v0 is not None else v_cruise * (1.0 + wander[0]))
    total = path.length
    dwell_left = 0.0
    stops_done: set[float] = set()
    max_steps = int(4.0 * (total / max(v_min, 1.0)) / dt) + 20000

    for step in range(max_steps):
        if s >= total:
            break

        if dwell_left > 0.0:  # parked at a scheduled stop
            dwell_left -= dt
            v_hist.append(0.0)
            continue

        # Braking-distance look-ahead: the speed that can still be shed in time.
        probe = np.interp(s + lookahead, path.s, v_limit)
        allowed = np.sqrt(probe**2 + 2.0 * vehicle.a_brake_max * lookahead)
        v_free = v_cruise * (1.0 + wander[min(step, len(wander) - 1)])
        v_target = float(min(v_free, allowed.min()))

        if v_target < v:
            v = max(v_target, v - vehicle.a_brake_max * dt)
        else:
            v = min(v_target, v + vehicle.a_accel_max * dt)

        for s_stop in stops:
            if s_stop not in stops_done and s >= s_stop - 1.0 and v < 1.0:
                dwell_left = stop_duration_s
                stops_done.add(s_stop)
                v = 0.0

        v = max(v, v_min if dwell_left <= 0.0 else 0.0)
        v_hist.append(v)
        s += v * dt

    v_arr = np.asarray(v_hist, dtype=float)
    if len(v_arr) < 8:
        return np.arange(len(v_arr)) * dt, v_arr

    # Smooth the speed to give the powertrain finite jerk. The driver model
    # switches between accelerate and brake instantaneously, which is not a
    # thing a vehicle can do, and the resulting corner in v would appear in the
    # specific force as a broadband click that no real accelerometer would see.
    sigma_samples = max(0.12 / dt, 1.0)
    v_arr = gaussian_filter1d(v_arr, sigma=sigma_samples, mode="nearest")
    return np.arange(len(v_arr)) * dt, np.maximum(v_arr, 0.0)
