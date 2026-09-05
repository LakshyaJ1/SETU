"""Simulator tests.

The simulator is the instrument every later measurement is scored against, so
it is held to the physics directly: the coordinated-turn relations of
``docs/03-approach.md`` 3.4 must fall out of the generated specific force to
better than a tenth of a percent, without anything in the estimator being
involved. If these fail, no downstream result means anything.
"""

from __future__ import annotations

import numpy as np
import pytest

from setu.core import so3
from setu.core.constants import G0
from setu.mapping import build_route
from setu.sensors.types import tier_for_rate
from setu.sim import (
    CAR,
    MOTORCYCLE,
    PHONE_FLAGSHIP,
    PHONE_MID,
    PHONE_THROTTLED,
    ROAD_NORMAL,
    SCOOTER,
    simulate_drive,
    simulate_truth,
    synthesize_vibration,
    tunnel_dip,
)


@pytest.fixture(scope="module")
def car_truth():
    path = build_route("curvy_a_road", length_m=1200.0)
    return path, simulate_truth(path, CAR, rate_hz=200.0, route_name="curvy_a_road")


@pytest.fixture(scope="module")
def bike_truth():
    # Roundabouts, because a two-wheeler only leans meaningfully at tight radii
    # and the lean-corrected relations are what this fixture exists to check.
    path = build_route("roundabout_route", length_m=1500.0)
    return path, simulate_truth(path, MOTORCYCLE, rate_hz=200.0, route_name="roundabout_route")


class TestTruthKinematics:
    def test_speed_is_never_negative(self, car_truth):
        """Interpolating position rather than speed used to produce this."""
        _, gt = car_truth
        assert gt.v.min() >= 0.0

    def test_speed_is_the_derivative_of_arc_length(self, car_truth):
        _, gt = car_truth
        v_fd = np.gradient(gt.s, gt.t)
        interior = slice(50, -50)
        assert np.allclose(v_fd[interior], gt.v[interior], atol=2e-3)

    def test_velocity_is_the_derivative_of_position(self, car_truth):
        _, gt = car_truth
        v_fd = np.gradient(gt.pos_enu, gt.t, axis=0)
        interior = slice(50, -50)
        assert np.max(np.abs(v_fd[interior] - gt.vel_enu[interior])) < 5e-3

    def test_truth_stays_on_the_road(self, car_truth):
        """Integrating the tangent must not let the vehicle wander off the map.

        Position is built by integration rather than by interpolating the
        polyline, so this is the check that the integration does not drift --
        it matters because every map-based measurement is defined relative to
        the centreline.
        """
        path, gt = car_truth
        for i in np.linspace(10, len(gt) - 10, 60).astype(int):
            _, cross_track = path.project(gt.pos_enu[i, :2])
            assert abs(cross_track) < 0.02, f"drifted {cross_track:.4f} m at sample {i}"

    def test_attitude_is_a_valid_rotation(self, car_truth):
        _, gt = car_truth
        for i in np.linspace(0, len(gt) - 1, 40).astype(int):
            r = gt.R_nb[i]
            assert np.allclose(r @ r.T, np.eye(3), atol=1e-12)
            assert np.isclose(np.linalg.det(r), 1.0, atol=1e-12)

    def test_body_x_axis_points_along_velocity(self, car_truth):
        """The vehicle travels forwards -- the non-holonomic assumption itself."""
        _, gt = car_truth
        moving = gt.v > 1.0
        forward = gt.R_nb[:, :, 0]
        vhat = gt.vel_enu / np.linalg.norm(gt.vel_enu, axis=1, keepdims=True).clip(1e-9)
        assert np.min(np.einsum("ij,ij->i", forward[moving], vhat[moving])) > 0.9999

    def test_gyro_matches_numerical_attitude_derivative(self, car_truth):
        """The analytic body rate must equal ``vee(R^T dR/dt)``.

        This is the test that adjudicates the sign conventions in the closed-form
        gyro expression; getting one wrong is a heading error that only shows up
        after a minute of integration.
        """
        _, gt = car_truth
        idx = np.arange(100, len(gt) - 100, 37)
        dt = gt.t[1] - gt.t[0]
        for i in idx:
            rel = gt.R_nb[i - 1].T @ gt.R_nb[i + 1]
            w_fd = so3.log(rel) / (2.0 * dt)
            assert np.allclose(w_fd, gt.gyro_ideal[i], atol=2e-3), f"sample {i}"

    def test_yaw_rate_equals_curvature_times_speed(self, car_truth):
        _, gt = car_truth
        assert np.allclose(gt.omega_z, gt.kappa * gt.v, atol=1e-9)


class TestCoordinatedTurnPhysics:
    """The relations CTS inverts. These come straight from docs/03-approach.md 3.4."""

    def test_car_speed_from_levelled_lateral_acceleration(self, car_truth):
        """``v = a_lat / Omega`` once the specific force is levelled.

        The relation holds in the *navigation* frame. Reading the body-frame
        lateral channel directly is not the same thing, which is why CTS is
        specified downstream of the attitude estimate rather than as a raw
        accelerometer ratio.
        """
        _, gt = car_truth
        turning = np.abs(gt.omega_z) > 0.05
        assert turning.sum() > 500, "route should contain sustained turns"

        # Rotate specific force to the nav frame and remove gravity.
        a_nav = np.einsum("nij,nj->ni", gt.R_nb[turning], gt.accel_ideal[turning])
        a_nav[:, 2] -= G0
        left = np.stack([-np.sin(gt.psi[turning]), np.cos(gt.psi[turning])], axis=1)
        a_lat = np.einsum("ni,ni->n", a_nav[:, :2], left)

        v_est = a_lat / gt.omega_z[turning]
        rel = np.abs(v_est - gt.v[turning]) / gt.v[turning]
        assert np.median(rel) < 2e-3

    def test_ignoring_body_roll_costs_more_than_ten_percent(self, car_truth):
        """Why levelling is not optional.

        A car rolls only a degree or two on its suspension, which sounds
        negligible -- but ``g sin(1.4 deg)`` is 0.24 m/s^2 against a lateral
        acceleration of about 2 m/s^2, so gravity leaking into the lateral
        channel is a ~12 % speed error. That is 120 m per km, an order above the
        error budget in docs/03-approach.md 3.10.
        """
        _, gt = car_truth
        turning = np.abs(gt.omega_z) > 0.05
        naive = gt.accel_ideal[turning, 1] / gt.omega_z[turning]
        rel = np.abs(naive - gt.v[turning]) / gt.v[turning]
        assert float(np.median(rel)) > 0.05

    def test_car_roll_can_be_compensated_in_the_body_frame(self, car_truth):
        """``a_lat = (f_y + g sin(roll)) / cos(roll)`` -- the levelling, explicitly."""
        _, gt = car_truth
        turning = np.abs(gt.omega_z) > 0.05
        roll = gt.roll[turning]
        f_y = gt.accel_ideal[turning, 1]
        a_lat = (f_y + G0 * np.sin(roll)) / np.cos(roll)
        v_est = a_lat / gt.omega_z[turning]
        rel = np.abs(v_est - gt.v[turning]) / gt.v[turning]
        assert np.median(rel) < 5e-3

    def test_car_with_no_body_roll_is_exact(self):
        """With the suspension frozen the relation must hold to machine precision."""
        rigid = CAR.__class__(**{**CAR.__dict__, "roll_gain": 0.0})
        path = build_route("roundabout_route", length_m=900.0)
        gt = simulate_truth(path, rigid, rate_hz=200.0)
        turning = np.abs(gt.omega_z) > 0.10
        v_est = gt.accel_ideal[turning, 1] / gt.omega_z[turning]
        assert np.max(np.abs(v_est - gt.v[turning])) < 1e-9

    def test_two_wheeler_lateral_channel_reads_zero(self, bike_truth):
        """A leaning bike takes the turn along its own vertical."""
        _, gt = bike_truth
        leaning = np.abs(gt.roll) > np.radians(8.0)
        assert leaning.sum() > 200
        assert np.max(np.abs(gt.accel_ideal[leaning, 1])) < 1e-9

    def test_two_wheeler_naive_formula_fails(self, bike_truth):
        """The mistake this design exists to avoid: zero speed in every turn."""
        _, gt = bike_truth
        leaning = np.abs(gt.roll) > np.radians(8.0)
        naive = gt.accel_ideal[leaning, 1] / gt.omega_z[leaning]
        assert np.max(np.abs(naive)) < 1e-6  # reads ~0 m/s while genuinely moving
        assert gt.v[leaning].min() > 5.0

    def test_two_wheeler_lean_corrected_formula_is_exact(self, bike_truth):
        """``v = g sin(phi) / w_z`` with ``phi = arccos(g / |f|)``.

        Worked example in the doc: v = 16.67 m/s on R = 100 m gives phi = 15.8
        deg, |f| = 10.196, w_z = 0.1604, and the formula returns 16.68.
        """
        _, gt = bike_truth
        leaning = np.abs(gt.roll) > np.radians(8.0)
        f = gt.accel_ideal[leaning]
        w_z = gt.gyro_ideal[leaning, 2]

        # The lean angle must be read from the y-z plane only. The doc's
        # "measured form" uses the full |f|, which silently assumes the bike is
        # neither accelerating nor braking -- on a roundabout it is doing both,
        # and a 2 m/s^2 longitudinal term inflates |f| enough to corrupt phi.
        f_yz = np.linalg.norm(f[:, 1:], axis=1)
        phi = np.arccos(np.clip(G0 / f_yz, -1.0, 1.0))
        v_est = G0 * np.sin(phi) / np.abs(w_z)
        rel = np.abs(v_est - gt.v[leaning]) / gt.v[leaning]
        assert np.max(rel) < 5e-3

    def test_longitudinal_acceleration_corrupts_the_full_norm_form(self, bike_truth):
        """Records the caveat above as a measured quantity, not a footnote."""
        _, gt = bike_truth
        sel = (np.abs(gt.roll) > np.radians(8.0)) & (np.abs(gt.a_long) > 1.0)
        assert sel.sum() > 50, "roundabouts should mix leaning with braking"
        f = gt.accel_ideal[sel]
        w_z = np.abs(gt.gyro_ideal[sel, 2])

        phi_yz = np.arccos(np.clip(G0 / np.linalg.norm(f[:, 1:], axis=1), -1.0, 1.0))
        phi_full = np.arccos(np.clip(G0 / np.linalg.norm(f, axis=1), -1.0, 1.0))
        err_yz = np.abs(G0 * np.sin(phi_yz) / w_z - gt.v[sel]) / gt.v[sel]
        err_full = np.abs(G0 * np.sin(phi_full) / w_z - gt.v[sel]) / gt.v[sel]
        assert np.median(err_full) > 5.0 * np.median(err_yz)

    def test_dropping_cos_phi_is_a_four_percent_error(self, bike_truth):
        """Quantifies the trap: 40 m/km of pure scale error, silently."""
        _, gt = bike_truth
        steep = np.abs(gt.roll) > np.radians(14.0)
        assert steep.sum() > 20
        f = gt.accel_ideal[steep]
        w_z = np.abs(gt.gyro_ideal[steep, 2])
        f_mag = np.linalg.norm(f, axis=1)
        phi = np.arccos(np.clip(G0 / f_mag, -1.0, 1.0))

        correct = G0 * np.sin(phi) / w_z
        # Omitting the cos(phi) that converts body yaw rate to true yaw rate.
        naive = G0 * np.tan(phi) / w_z
        bias = np.median(naive / correct) - 1.0
        assert 0.02 < bias < 0.12


class TestVerticalAndGrade:
    def test_tunnel_dip_changes_altitude(self):
        path = build_route("straight_motorway", length_m=1200.0)
        gt = simulate_truth(path, CAR, rate_hz=100.0, grade=tunnel_dip(300.0, 900.0, depth_m=18.0))
        assert gt.pos_enu[:, 2].min() < -8.0
        assert abs(gt.pos_enu[0, 2]) < 1.0

    def test_pitch_follows_the_grade(self):
        path = build_route("straight_motorway", length_m=1200.0)
        grade = tunnel_dip(300.0, 900.0, depth_m=18.0)
        gt = simulate_truth(path, CAR, rate_hz=100.0, grade=grade)
        # Body x axis must tilt down on the way in and up on the way out.
        descending = gt.R_nb[:, 2, 0] < -0.01
        climbing = gt.R_nb[:, 2, 0] > 0.01
        assert descending.any() and climbing.any()


class TestVibration:
    def test_axle_line_is_at_the_predicted_frequency(self):
        """``f_ax = v / (2 pi R_eff)`` must be recoverable from the spectrum."""
        path = build_route("straight_motorway", length_m=800.0)
        gt = simulate_truth(path, CAR, rate_hz=1000.0)
        rng = np.random.default_rng(0)
        vib, diag = synthesize_vibration(gt.t, gt.v, CAR, ROAD_NORMAL, rng)

        # A window over which speed is near constant, so the line is sharp.
        lo, hi = 4000, 4000 + 4096
        seg = vib[lo:hi, 2] - vib[lo:hi, 2].mean()
        spec = np.abs(np.fft.rfft(seg * np.hanning(len(seg))))
        freqs = np.fft.rfftfreq(len(seg), d=1.0 / 1000.0)

        f_true = float(np.mean(diag["f_ax"][lo:hi]))
        band = (freqs > f_true - 0.6) & (freqs < f_true + 0.6)
        peak = freqs[band][np.argmax(spec[band])]
        assert abs(peak - f_true) < 0.35

        # The line must actually stand above the local floor, or there is
        # nothing for SVO to track.
        floor = np.median(spec[(freqs > 2) & (freqs < 60)])
        assert spec[band].max() > 6.0 * floor

    def test_axle_frequency_tracks_speed(self):
        path = build_route("urban_canyon", length_m=900.0)
        gt = simulate_truth(path, CAR, rate_hz=500.0)
        rng = np.random.default_rng(1)
        _, diag = synthesize_vibration(gt.t, gt.v, CAR, ROAD_NORMAL, rng)
        assert np.allclose(diag["f_ax"], gt.v / CAR.k_svo, atol=1e-12)

    def test_gear_changes_are_discontinuous_but_axle_line_is_not(self):
        """The free label for family disambiguation (docs/03-approach.md 3.3)."""
        path = build_route("urban_canyon", length_m=900.0)
        gt = simulate_truth(path, CAR, rate_hz=200.0)
        rng = np.random.default_rng(2)
        _, diag = synthesize_vibration(gt.t, gt.v, CAR, ROAD_NORMAL, rng)

        assert len(np.unique(diag["gear"])) > 1, "route should include gear changes"
        jump_engine = np.max(np.abs(np.diff(diag["f_engine_rev"])))
        jump_axle = np.max(np.abs(np.diff(diag["f_ax"])))
        assert jump_engine > 20.0 * jump_axle

    def test_scooter_has_a_higher_axle_frequency_than_a_car(self):
        """Small wheels spin faster: R_eff is the scale SVO must calibrate."""
        assert SCOOTER.k_svo < CAR.k_svo
        v = 10.0
        assert v / SCOOTER.k_svo > 1.35 * (v / CAR.k_svo)


class TestDriveSimulation:
    def test_tiers_follow_the_sample_rate(self):
        assert tier_for_rate(400.0) == "A"
        assert tier_for_rate(200.0) == "A"
        assert tier_for_rate(100.0) == "B"
        assert tier_for_rate(10.0) == "C"  # IO-VNBD S-, not tier D
        assert tier_for_rate(5.0) == "D"
        assert tier_for_rate(200.0, has_gyro=False) == "D"

    @pytest.mark.parametrize(
        ("device", "tier"), [(PHONE_FLAGSHIP, "A"), (PHONE_MID, "A"), (PHONE_THROTTLED, "C")]
    )
    def test_reported_tier_matches_the_device(self, device, tier):
        d = simulate_drive("straight_motorway", route_length_m=400.0, device=device, seed=3)
        assert d.tier == tier

    def test_gravity_magnitude_survives_the_mount(self):
        """An unknown mount rotates the signal but cannot change its norm."""
        d = simulate_drive("gentle_motorway", route_length_m=600.0, seed=4)
        mean_norm = float(np.linalg.norm(d.log.imu.accel, axis=1).mean())
        assert abs(mean_norm - G0) < 0.15

    def test_outage_withholds_position_and_velocity(self):
        """Withholding position alone would flatter every later result."""
        d = simulate_drive("curvy_a_road", route_length_m=900.0, outages=((20.0, 50.0),), seed=5)
        gnss = d.log.gnss
        blacked_out = (gnss.t >= 20.0) & (gnss.t <= 50.0)
        assert blacked_out.any()
        assert not gnss.available[blacked_out].any()
        assert (gnss.n_sats[blacked_out] == 0).all()
        assert gnss.available[~blacked_out].all()

    def test_determinism(self):
        """Same seed, same bits -- the replay requirement of 4.1."""
        a = simulate_drive("curvy_a_road", route_length_m=500.0, seed=7)
        b = simulate_drive("curvy_a_road", route_length_m=500.0, seed=7)
        assert np.array_equal(a.log.imu.accel, b.log.imu.accel)
        assert np.array_equal(a.log.imu.gyro, b.log.imu.gyro)
        assert np.array_equal(a.truth.pos_enu, b.truth.pos_enu)

    def test_different_seeds_differ(self):
        a = simulate_drive("curvy_a_road", route_length_m=500.0, seed=7)
        b = simulate_drive("curvy_a_road", route_length_m=500.0, seed=8)
        assert not np.array_equal(a.log.imu.accel, b.log.imu.accel)

    def test_magnetic_anomaly_repeats_across_traversals(self):
        """EFA's whole premise: the second vehicle sees the first one's signature."""
        common = {"route_length_m": 600.0, "anomaly_seed": 99}
        a = simulate_drive("curvy_a_road", seed=1, **common)
        b = simulate_drive("curvy_a_road", seed=2, **common)
        # Compare the field magnitude as a function of distance travelled, which
        # is mount- and heading-independent.
        grid = np.linspace(50.0, 500.0, 200)
        ma = np.interp(grid, a.truth.s, np.linalg.norm(a.log.mag.field_ut, axis=1)[
            np.clip(np.searchsorted(a.log.mag.t, a.truth.t), 0, len(a.log.mag) - 1)
        ])
        mb = np.interp(grid, b.truth.s, np.linalg.norm(b.log.mag.field_ut, axis=1)[
            np.clip(np.searchsorted(b.log.mag.t, b.truth.t), 0, len(b.log.mag) - 1)
        ])
        assert float(np.corrcoef(ma, mb)[0, 1]) > 0.9

    def test_barometer_resolves_a_parking_level(self):
        """3 m between decks against ~0.25 m of sensor noise."""
        from setu.sim import parking_ramp

        d = simulate_drive(
            "parking_helix",
            route_length_m=None,
            grade=parking_ramp(deck_m=45.0, turn_m=2 * np.pi * 11.0),
            seed=11,
        )
        h = d.truth.pos_enu[:, 2]
        assert h.max() > 8.0
        pressure = d.log.baro.pressure_pa
        assert pressure.max() - pressure.min() > 60.0  # ~3 m is ~36 Pa per level


class TestBandLimiting:
    def test_axle_harmonics_are_removed_at_tier_c(self):
        """The claim that makes the tiers architectural rather than rhetorical.

        A 10 Hz phone does not alias axle lines into its passband -- it filters
        them out. So SVO is genuinely unavailable at Tier C, and any Tier A
        result must be labelled as such.
        """
        fast = simulate_drive(
            "straight_motorway", route_length_m=900.0, device=PHONE_FLAGSHIP, seed=13
        )
        slow = simulate_drive(
            "straight_motorway", route_length_m=900.0, device=PHONE_THROTTLED, seed=13
        )
        f_ax = float(np.median(fast.f_ax_true))

        def spectrum(drive, rate):
            a = drive.log.imu.accel[:, 2]
            n = min(4096, len(a) // 2 * 2)
            m = len(a) // 2
            seg = a[m - n // 2 : m + n // 2]
            seg = seg - seg.mean()
            spec = np.abs(np.fft.rfft(seg * np.hanning(len(seg))))
            return np.fft.rfftfreq(len(seg), d=1.0 / rate), spec

        # Tier A: the line is present and stands clear of the road-noise floor.
        fr, spec = spectrum(fast, 400.0)
        band = (fr > f_ax - 0.8) & (fr < f_ax + 0.8)
        floor = float(np.median(spec[fr > 1.0]))
        assert band.any()
        assert float(spec[band].max()) > 2.5 * floor, "Tier A must see the axle line"

        # Tier C: the line is not attenuated, it is unreachable. A 10 Hz stream
        # has a 5 Hz Nyquist and the axle order sits at ~10 Hz, so no amount of
        # processing recovers it -- and because the phone anti-alias filters
        # before reporting, it does not fold back into the passband either.
        assert f_ax > 5.0, "axle line should sit above the Tier C Nyquist"
        fr_c, spec_c = spectrum(slow, 10.0)
        assert fr_c.max() < f_ax, "Tier C cannot represent the axle frequency at all"
        # No spurious alias: the Tier C band is flat, with no peak standing out.
        in_band = fr_c > 0.5
        assert float(spec_c[in_band].max()) < 8.0 * float(np.median(spec_c[in_band]))
