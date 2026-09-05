"""Deterministic drive simulator with exact ground truth.

No IO-VNBD data is required to exercise the estimator, and unlike a recorded
drive the truth here is known to machine precision, so a 2 m error is a 2 m
error rather than the difference between two imperfect estimates.

The simulator is not a substitute for the dataset -- ``docs/08-evaluation.md``
8.9 is explicit that Tier A claims need real 400 Hz logs -- but it is what makes
the physics falsifiable before any data arrives, and it produces the one thing
IO-VNBD cannot: a drive where the answer is known exactly.
"""

from .sensors import (
    ADIS16505,
    DEVICES,
    FOG,
    GNSS_OPEN_SKY,
    GNSS_URBAN,
    PHONE_BUDGET,
    PHONE_FLAGSHIP,
    PHONE_MID,
    PHONE_THROTTLED,
    DriveResult,
    GnssErrorModel,
    ImuErrorModel,
    MountModel,
    simulate_drive,
)
from .truth import flat, parking_ramp, simulate_truth, tunnel_dip
from .vehicle import BUS, CAR, MOTORCYCLE, SCOOTER, VEHICLES, VehicleModel, speed_profile
from .vibration import ROAD_NORMAL, ROAD_ROUGH, ROAD_SMOOTH, VibrationModel, synthesize_vibration

__all__ = [
    # drive
    "simulate_drive",
    "DriveResult",
    # truth
    "simulate_truth",
    "flat",
    "tunnel_dip",
    "parking_ramp",
    # vehicles
    "VehicleModel",
    "CAR",
    "MOTORCYCLE",
    "SCOOTER",
    "BUS",
    "VEHICLES",
    "speed_profile",
    # sensors
    "ImuErrorModel",
    "GnssErrorModel",
    "MountModel",
    "PHONE_FLAGSHIP",
    "PHONE_MID",
    "PHONE_BUDGET",
    "PHONE_THROTTLED",
    "ADIS16505",
    "FOG",
    "DEVICES",
    "GNSS_OPEN_SKY",
    "GNSS_URBAN",
    # vibration
    "VibrationModel",
    "ROAD_SMOOTH",
    "ROAD_NORMAL",
    "ROAD_ROUGH",
    "synthesize_vibration",
]
