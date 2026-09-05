"""Measurement-generator tests.

Two things are checked for every generator: that the value is right, and that
the *stated uncertainty* is honest. The second matters as much as the first --
``docs/08-evaluation.md`` 8.2 makes sigma-coverage a first-class metric,
because a good estimate with a bad covariance still destroys the filter that
consumes it.
"""

from __future__ import annotations

import numpy as np
import pytest

from setu.measurements.cts import lean_corrected_speed, levelled_speed
from setu.measurements.svo import SpectralOdometer, SvoConfig
from setu.measurements.types import ScalarMeasurement, merge_inverse_variance
from setu.sim import (
    CAR,
    MOTORCYCLE,
    PHONE_FLAGSHIP,
    PHONE_MID,
    PHONE_THROTTLED,
    ROAD_ROUGH,
    simulate_drive,
)


def phone_attitude(drive):
    """True phone-frame attitude. ``mount.rotation()`` is vehicle -> phone."""
    return drive.truth.R_nb @ drive.mount.rotation().T


def normalised_errors(m: ScalarMeasurement, truth_t, truth_v) -> np.ndarray:
    v_true = np.interp(m.t, truth_t, truth_v)
    ok = m.valid & np.isfinite(m.sigma) & (m.sigma > 0)
    return (m.value[ok] - v_true[ok]) / m.sigma[ok]


# --------------------------------------------------------------------- SVO
class TestSpectralOdometer:
    def test_recovers_speed_at_tier_a(self):
        """The central claim of docs/03-approach.md 3.3, measured.

        The doc predicts 0.1-0.6 % from a 2.56 s window with harmonic summation.
        """
        d = simulate_drive(
            "straight_motorway", route_length_m=1200.0, device=PHONE_FLAGSHIP, seed=5
        )
        r = SpectralOdometer(k_svo=CAR.k_svo).estimate(d.log.imu, a_long=d.truth.a_long)
        assert r.available

        v_true = np.interp(r.speed.t, d.truth.t, d.truth.v)
        ok = r.speed.valid
        rel = np.abs(r.speed.value[ok] - v_true[ok]) / v_true[ok]
        assert r.speed.coverage > 0.5
        assert float(np.median(rel)) < 0.006
        assert float(np.percentile(rel, 90)) < 0.02

    def test_refuses_at_tier_c(self):
        """Not degraded -- unavailable. The anti-alias filter removed the lines."""
        d = simulate_drive(
            "straight_motorway", route_length_m=800.0, device=PHONE_THROTTLED, seed=5
        )
        r = SpectralOdometer(k_svo=CAR.k_svo).estimate(d.log.imu)
        assert not r.available
        assert "tier C" in r.reason
        assert len(r.speed) == 0

    def test_works_on_a_straight_road(self):
        """The scenario that defeats every shape-based method."""
        d = simulate_drive(
            "straight_motorway", route_length_m=1500.0, device=PHONE_FLAGSHIP, seed=6
        )
        assert np.allclose(d.truth.kappa, 0.0, atol=1e-6)
        r = SpectralOdometer(k_svo=CAR.k_svo).estimate(d.log.imu, a_long=d.truth.a_long)
        v_true = np.interp(r.speed.t, d.truth.t, d.truth.v)
        ok = r.speed.valid
        assert float(np.median(np.abs(r.speed.value[ok] - v_true[ok]) / v_true[ok])) < 0.01

    def test_survives_a_rough_road(self):
        d = simulate_drive(
            "gentle_motorway",
            route_length_m=1200.0,
            device=PHONE_FLAGSHIP,
            road=ROAD_ROUGH,
            seed=7,
        )
        r = SpectralOdometer(k_svo=CAR.k_svo).estimate(d.log.imu, a_long=d.truth.a_long)
        v_true = np.interp(r.speed.t, d.truth.t, d.truth.v)
        ok = r.speed.valid
        assert float(np.median(np.abs(r.speed.value[ok] - v_true[ok]) / v_true[ok])) < 0.02

    def test_does_not_slip_an_octave(self):
        """Half- and double-frequency locks are the classic ridge-tracker failure.

        A subharmonic scores almost as well as the truth under harmonic
        summation, because its harmonic set contains the true fundamental.
        """
        d = simulate_drive(
            "gentle_motorway", route_length_m=1500.0, device=PHONE_FLAGSHIP, seed=8
        )
        r = SpectralOdometer(k_svo=CAR.k_svo).estimate(d.log.imu, a_long=d.truth.a_long)
        f_true = np.interp(r.speed.t, d.truth.t, d.f_ax_true)
        ok = r.speed.valid
        ratio = r.f0[ok] / f_true[ok]
        # No frame may sit near 0.5x or 2x the true fundamental.
        assert np.max(np.abs(ratio - 1.0)) < 0.25

    def test_scale_error_is_pure_scale(self):
        """A wrong R_eff is a scale error, which is why CTS must observe it."""
        d = simulate_drive(
            "straight_motorway", route_length_m=1000.0, device=PHONE_FLAGSHIP, seed=9
        )
        good = SpectralOdometer(k_svo=CAR.k_svo).estimate(d.log.imu, a_long=d.truth.a_long)
        bad = SpectralOdometer(k_svo=CAR.k_svo * 1.08).estimate(d.log.imu, a_long=d.truth.a_long)
        ok = good.speed.valid & bad.speed.valid
        ratio = bad.speed.value[ok] / good.speed.value[ok]
        assert np.allclose(ratio, 1.08, atol=1e-9)

    def test_uncertainty_is_not_wildly_optimistic(self):
        d = simulate_drive(
            "gentle_motorway", route_length_m=1200.0, device=PHONE_MID, seed=10
        )
        r = SpectralOdometer(
            k_svo=CAR.k_svo, config=SvoConfig(scale_sigma_rel=0.0)
        ).estimate(d.log.imu, a_long=d.truth.a_long)
        z = normalised_errors(r.speed, d.truth.t, d.truth.v)
        assert len(z) > 100
        assert float(np.mean(np.abs(z) < 3.0)) > 0.90


# --------------------------------------------------------------------- CTS
class TestCoordinatedTurnSpeedometer:
    def test_car_speed_in_turns(self):
        d = simulate_drive(
            "roundabout_route", route_length_m=1500.0, vehicle=CAR, device=PHONE_MID, seed=4
        )
        m = levelled_speed(
            d.truth.t, d.log.imu.accel, d.log.imu.gyro, phone_attitude(d), d.truth.psi
        )
        ok = m.valid
        assert ok.sum() > 1000
        rel = np.abs(m.value[ok] - d.truth.v[ok]) / d.truth.v[ok]
        assert float(np.median(rel)) < 0.04

    def test_unobservable_on_a_straight_road(self):
        """CTS must *report* that it is blind rather than return a wild number."""
        d = simulate_drive(
            "straight_motorway", route_length_m=1200.0, device=PHONE_MID, seed=11
        )
        m = levelled_speed(
            d.truth.t, d.log.imu.accel, d.log.imu.gyro, phone_attitude(d), d.truth.psi
        )
        assert m.coverage < 0.05

    def test_complementary_to_svo(self):
        """Neither channel alone suffices; between them they cover both cases.

        This is the calibration cascade of docs/03-approach.md 3.4 stated as a
        test: CTS is blind on the straight where SVO works, and SVO is scale-
        ambiguous where CTS is absolute.
        """
        straight = simulate_drive(
            "straight_motorway", route_length_m=1200.0, device=PHONE_FLAGSHIP, seed=12
        )
        curvy = simulate_drive(
            "roundabout_route", route_length_m=1200.0, device=PHONE_FLAGSHIP, seed=12
        )

        def cts_cov(d):
            return levelled_speed(
                d.truth.t, d.log.imu.accel, d.log.imu.gyro, phone_attitude(d), d.truth.psi
            ).coverage

        def svo_cov(d):
            return SpectralOdometer(k_svo=CAR.k_svo).estimate(
                d.log.imu, a_long=d.truth.a_long
            ).speed.coverage

        assert cts_cov(straight) < 0.05 and svo_cov(straight) > 0.4
        assert cts_cov(curvy) > 0.2

    def test_two_wheeler_naive_ratio_is_useless(self):
        """Body lateral over yaw rate returns ~zero speed in every turn."""
        d = simulate_drive(
            "roundabout_route", route_length_m=1200.0, vehicle=MOTORCYCLE, seed=13
        )
        gt = d.truth
        leaning = np.abs(gt.roll) > np.radians(10.0)
        naive = gt.accel_ideal[leaning, 1] / gt.gyro_ideal[leaning, 2]
        assert np.max(np.abs(naive)) < 0.5
        assert gt.v[leaning].min() > 4.0

    def test_two_wheeler_lean_corrected_recovers_speed(self):
        d = simulate_drive(
            "roundabout_route", route_length_m=1500.0, vehicle=MOTORCYCLE, seed=13
        )
        gt = d.truth
        m = lean_corrected_speed(gt.t, gt.accel_ideal, gt.gyro_ideal)
        ok = m.valid
        assert ok.sum() > 500
        rel = np.abs(m.value[ok] - gt.v[ok]) / gt.v[ok]
        assert float(np.median(rel)) < 0.05

    def test_levelled_form_handles_a_leaning_bike(self):
        """Given attitude, one relation covers both vehicle classes."""
        d = simulate_drive(
            "roundabout_route", route_length_m=1500.0, vehicle=MOTORCYCLE, seed=14
        )
        m = levelled_speed(
            d.truth.t, d.log.imu.accel, d.log.imu.gyro, phone_attitude(d), d.truth.psi
        )
        ok = m.valid
        rel = np.abs(m.value[ok] - d.truth.v[ok]) / d.truth.v[ok]
        assert float(np.median(rel)) < 0.06

    def test_sigma_tracks_the_actual_error(self):
        """The stated uncertainty must be informative, not decorative.

        Measured on a route with *varied* radii. A fixed-radius roundabout has
        an almost constant yaw rate, so sigma barely varies there and any split
        on it is degenerate -- which is how an earlier version of this test
        passed a sigma model that was six times overconfident.
        """
        d = simulate_drive(
            "curvy_a_road", route_length_m=2500.0, vehicle=CAR, device=PHONE_MID, seed=15
        )
        m = levelled_speed(
            d.truth.t, d.log.imu.accel, d.log.imu.gyro, phone_attitude(d), d.truth.psi
        )
        ok = m.valid
        assert ok.sum() > 500
        err = np.abs(m.value[ok] - d.truth.v[ok])
        assert float(np.corrcoef(err, m.sigma[ok])[0, 1]) > 0.35

    def test_sigma_is_not_overconfident(self):
        """Errors must mostly fall inside the stated 3-sigma band."""
        d = simulate_drive(
            "roundabout_route", route_length_m=1500.0, vehicle=CAR, device=PHONE_MID, seed=15
        )
        m = levelled_speed(
            d.truth.t, d.log.imu.accel, d.log.imu.gyro, phone_attitude(d), d.truth.psi
        )
        z = normalised_errors(m, d.truth.t, d.truth.v)
        assert len(z) > 500
        assert float(np.mean(np.abs(z) < 3.0)) > 0.85

    def test_residual_bias_needs_the_filter(self):
        """CTS alone carries the accelerometer's bias into its speed.

        With ideal sensors the relation is exact; with a phone's turn-on bias it
        acquires a systematic offset of a percent or two, because a constant
        error in the lateral channel divided by the yaw rate is a constant speed
        error. Nothing inside CTS can remove it -- the filter's accelerometer
        bias state is what does, which is why CTS is specified as a measurement
        inside the estimator rather than as a standalone speedometer.
        """
        d = simulate_drive(
            "roundabout_route", route_length_m=1500.0, vehicle=CAR, device=PHONE_MID, seed=15
        )
        gt = d.truth
        ideal = levelled_speed(gt.t, gt.accel_ideal, gt.gyro_ideal, gt.R_nb, gt.psi)
        real = levelled_speed(
            gt.t, d.log.imu.accel, d.log.imu.gyro, phone_attitude(d), gt.psi
        )
        ok_i, ok_r = ideal.valid, real.valid
        assert abs(float(np.median(ideal.value[ok_i] - gt.v[ok_i]))) < 0.02
        assert abs(float(np.median(real.value[ok_r] - gt.v[ok_r]))) > 0.05


# ------------------------------------------------------------------- fusion
class TestFusion:
    def _m(self, value, sigma, n=50, source="x", valid=True):
        t = np.arange(n) * 0.1
        return ScalarMeasurement(
            t, np.full(n, value), np.full(n, sigma), np.full(n, valid, dtype=bool), source
        )

    def test_inverse_variance_weighting(self):
        fused = merge_inverse_variance([self._m(10.0, 1.0, source="a"),
                                        self._m(12.0, 1.0, source="b")])
        assert np.allclose(fused.value, 11.0)
        assert np.allclose(fused.sigma, 1.0 / np.sqrt(2.0))

    def test_confident_channel_dominates(self):
        fused = merge_inverse_variance([self._m(10.0, 0.1, source="a"),
                                        self._m(20.0, 10.0, source="b")])
        assert fused.value[0] < 10.1

    def test_disagreement_inflates_rather_than_picking_a_winner(self):
        """Fault detection, not voting (docs/03-approach.md 3.4)."""
        agree = merge_inverse_variance([self._m(10.0, 0.5, source="a"),
                                        self._m(10.1, 0.5, source="b")])
        disagree = merge_inverse_variance([self._m(10.0, 0.5, source="a"),
                                           self._m(18.0, 0.5, source="b")])
        assert disagree.sigma[0] > 2.5 * agree.sigma[0]

    def test_invalid_channels_are_skipped(self):
        fused = merge_inverse_variance([self._m(10.0, 1.0, source="a"),
                                        self._m(99.0, 0.01, source="b", valid=False)])
        assert np.allclose(fused.value, 10.0)
        assert fused.valid.all()

    def test_all_invalid_yields_no_measurement(self):
        fused = merge_inverse_variance([self._m(1.0, 1.0, source="a", valid=False)])
        assert not fused.valid.any()
        assert np.isinf(fused.sigma).all()

    def test_requires_a_shared_grid(self):
        a = self._m(1.0, 1.0, n=10)
        b = ScalarMeasurement(
            np.arange(10) * 0.2, np.ones(10), np.ones(10), np.ones(10, dtype=bool), "b"
        )
        with pytest.raises(ValueError, match="share a time grid"):
            merge_inverse_variance([a, b])

    def test_resample_does_not_invent_validity(self):
        t = np.arange(10) * 1.0
        m = ScalarMeasurement(
            t, np.arange(10, dtype=float), np.ones(10),
            np.array([True] * 5 + [False] * 5), "a",
        )
        r = m.resampled_to(np.array([0.4, 4.6, 9.0]))
        assert list(r.valid) == [True, False, False]
