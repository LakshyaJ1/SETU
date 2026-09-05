"""Filter, alignment and registration tests.

The filter tests are structured around what can go silently wrong in a Kalman
filter: a sign error in a Jacobian shows up not as a crash but as a slow
divergence, so each channel is checked for actually *reducing* the error it is
supposed to observe, and the covariance is checked against the real error
spread rather than merely being finite.
"""

from __future__ import annotations

import numpy as np
import pytest

from setu.core import so3
from setu.estimation import InvariantEkf
from setu.measurements.alignment import estimate_mount
from setu.measurements.csa import CsaConfig, align_heading_profile
from setu.sim import MountModel, PHONE_FLAGSHIP, PHONE_MID, simulate_drive


@pytest.fixture(scope="module")
def drive():
    return simulate_drive("curvy_a_road", route_length_m=1200.0, device=PHONE_MID, seed=3)


def run_open_loop(d, ideal: bool, R0=None):
    gt, imu = d.truth, d.log.imu
    accel = gt.accel_ideal if ideal else imu.accel
    gyro = gt.gyro_ideal if ideal else imu.gyro
    ekf = InvariantEkf.initialise(gt.pos_enu[0], gt.vel_enu[0], R0 if R0 is not None else gt.R_nb[0])
    dt = 1.0 / imu.rate_hz
    for i in range(1, len(gt)):
        ekf.propagate(accel[i], gyro[i], dt)
    return ekf


class TestPropagation:
    def test_ideal_imu_reproduces_the_trajectory(self, drive):
        """With a perfect IMU the strapdown is arithmetic, and must be accurate."""
        ekf = run_open_loop(drive, ideal=True)
        gt = drive.truth
        err = np.linalg.norm(ekf.s.position - gt.pos_enu[-1])
        assert err < 1.5, f"{err:.2f} m of pure integrator error over {gt.s[-1]:.0f} m"
        assert abs(ekf.s.heading - np.arctan2(gt.R_nb[-1][1, 0], gt.R_nb[-1][0, 0])) < 1e-5

    def test_integration_error_is_second_order(self, drive):
        """Trapezoidal, not Euler: halving dt must cut the error by roughly four.

        Both runs use the *same* truth, decimated, so the only thing that
        changes is the integration step. Comparing two separately simulated
        devices would also change the truth's own discretisation and would not
        isolate the integrator.
        """
        gt = drive.truth
        rate = drive.log.imu.rate_hz

        def final_error(stride: int) -> float:
            ekf = InvariantEkf.initialise(gt.pos_enu[0], gt.vel_enu[0], gt.R_nb[0])
            dt = stride / rate
            idx = np.arange(0, len(gt), stride)
            for i in idx[1:]:
                ekf.propagate(gt.accel_ideal[i], gt.gyro_ideal[i], dt)
            return float(np.linalg.norm(ekf.s.position - gt.pos_enu[idx[-1]]))

        coarse, fine = final_error(4), final_error(2)
        assert fine < 0.4 * coarse

    def test_real_imu_diverges_without_aiding(self, drive):
        """The t^2/t^3 divergence the whole design exists to avoid (baseline B1)."""
        R0 = drive.truth.R_nb[0] @ drive.mount.rotation().T
        ekf = run_open_loop(drive, ideal=False, R0=R0)
        err = np.linalg.norm(ekf.s.position - drive.truth.pos_enu[-1])
        assert err > 100.0

    def test_covariance_grows_and_stays_symmetric(self, drive):
        gt, imu = drive.truth, drive.log.imu
        ekf = InvariantEkf.initialise(gt.pos_enu[0], gt.vel_enu[0], gt.R_nb[0])
        p0 = ekf.s.position_sigma()
        for i in range(1, 4000):
            ekf.propagate(imu.accel[i], imu.gyro[i], 1.0 / imu.rate_hz)
        assert ekf.s.position_sigma() > p0
        assert np.allclose(ekf.s.P, ekf.s.P.T, atol=1e-12)
        assert np.all(np.linalg.eigvalsh(ekf.s.P) > -1e-9)

    def test_attitude_stays_on_the_manifold(self, drive):
        ekf = run_open_loop(drive, ideal=True)
        R = ekf.s.X.R
        assert np.allclose(R @ R.T, np.eye(3), atol=1e-10)
        assert np.isclose(np.linalg.det(R), 1.0, atol=1e-10)


class TestUpdates:
    def _fresh(self, d, pos_offset=np.zeros(3)):
        gt = d.truth
        return InvariantEkf.initialise(gt.pos_enu[0] + pos_offset, gt.vel_enu[0], gt.R_nb[0])

    def test_position_update_pulls_toward_the_measurement(self, drive):
        ekf = self._fresh(drive, pos_offset=np.array([20.0, -15.0, 0.0]))
        before = np.linalg.norm(ekf.s.position - drive.truth.pos_enu[0])
        r = ekf.update_position(drive.truth.pos_enu[0], 2.0)
        assert r.accepted
        assert np.linalg.norm(ekf.s.position - drive.truth.pos_enu[0]) < 0.3 * before

    def test_velocity_update_pulls_toward_the_measurement(self, drive):
        # Within the gate: a 1 m/s error against a 0.5 m/s prior is 2 sigma.
        # A 4 m/s error is an 8 sigma outlier and is correctly *rejected*, which
        # is the subject of test_chi_square_gate_rejects_an_outlier.
        gt = drive.truth
        ekf = InvariantEkf.initialise(
            gt.pos_enu[0], gt.vel_enu[0] + np.array([1.0, 0, 0]), gt.R_nb[0]
        )
        before = np.linalg.norm(ekf.s.velocity - gt.vel_enu[0])
        r = ekf.update_velocity(gt.vel_enu[0], 0.1)
        assert r.accepted
        assert np.linalg.norm(ekf.s.velocity - gt.vel_enu[0]) < 0.3 * before

    def test_forward_speed_update(self, drive):
        gt = drive.truth
        ekf = InvariantEkf.initialise(gt.pos_enu[0], gt.vel_enu[0] * 1.3, gt.R_nb[0])
        ekf.update_forward_speed(float(np.linalg.norm(gt.vel_enu[0])), 0.1)
        assert abs(ekf.s.body_speed - np.linalg.norm(gt.vel_enu[0])) < 0.6

    def test_nhc_removes_side_slip(self, drive):
        gt = drive.truth
        R = gt.R_nb[0]
        # 0.8 m/s of lateral velocity: implausible for a vehicle but inside the
        # innovation gate given the 0.5 m/s prior.
        v_bad = gt.vel_enu[0] + R[:, 1] * 0.8
        ekf = InvariantEkf.initialise(gt.pos_enu[0], v_bad, R)
        before = abs((R.T @ ekf.s.velocity)[1])
        r = ekf.update_nhc(sigma=0.05)
        assert r.accepted
        assert abs((ekf.s.X.R.T @ ekf.s.velocity)[1]) < 0.4 * before

    def test_zupt_zeroes_velocity(self, drive):
        gt = drive.truth
        ekf = InvariantEkf.initialise(gt.pos_enu[0], np.array([3.0, 1.0, 0.2]), gt.R_nb[0])
        ekf.update_zupt(sigma=0.01)
        assert np.linalg.norm(ekf.s.velocity) < 0.5

    def test_chi_square_gate_rejects_an_outlier(self, drive):
        ekf = self._fresh(drive)
        r = ekf.update_position(drive.truth.pos_enu[0] + np.array([5000.0, 0, 0]), 1.0)
        assert not r.accepted
        assert np.linalg.norm(ekf.s.position - drive.truth.pos_enu[0]) < 1.0

    def test_gating_stats_are_recorded(self, drive):
        ekf = self._fresh(drive)
        ekf.update_position(drive.truth.pos_enu[0], 3.0)
        ekf.update_position(drive.truth.pos_enu[0] + np.array([9000.0, 0, 0]), 1.0)
        assert ekf.gating_stats()["gnss_pos"] == (1, 2)

    def test_svo_frequency_update_observes_the_scale(self, drive):
        """The calibration cascade: a known speed plus a frequency identifies k.

        This is the mechanism by which a turn calibrates the odometer, so if it
        does not move k, the central claim of docs/03-approach.md 3.4 is not
        actually implemented.
        """
        gt = drive.truth
        speed = float(np.linalg.norm(gt.vel_enu[0]))
        ekf = InvariantEkf.initialise(gt.pos_enu[0], gt.vel_enu[0], gt.R_nb[0], k_svo=1.60)
        k_before = ekf.s.k_svo
        true_k = 1.7467
        for _ in range(40):
            ekf.update_forward_speed(speed, 0.05)  # CTS-like absolute speed
            ekf.update_svo_frequency(speed / true_k, 0.02)
        assert abs(ekf.s.k_svo - true_k) < abs(k_before - true_k) * 0.5

    def test_bias_states_converge_with_aiding(self, drive):
        """Accelerometer bias must be observable, or CTS keeps its offset."""
        gt, imu = drive.truth, drive.log.imu
        ekf = InvariantEkf.initialise(
            gt.pos_enu[0], gt.vel_enu[0], gt.R_nb[0] @ drive.mount.rotation().T
        )
        dt = 1.0 / imu.rate_hz
        gnss_every = int(round(imu.rate_hz))
        for i in range(1, len(gt)):
            ekf.propagate(imu.accel[i], imu.gyro[i], dt)
            if i % gnss_every == 0:
                ekf.update_position(gt.pos_enu[i], 2.5)
                ekf.update_velocity(gt.vel_enu[i], 0.05)
        assert np.linalg.norm(ekf.s.position - gt.pos_enu[-1]) < 8.0
        assert np.linalg.norm(ekf.s.b_g) > 1e-4  # it actually estimated something


class TestAlignment:
    @pytest.mark.parametrize("yaw", [0.0, 25.0, -110.0, 175.0])
    def test_recovers_mount_yaw(self, yaw):
        """Mount yaw is the degree of freedom gravity cannot resolve."""
        d = simulate_drive(
            "curvy_a_road",
            route_length_m=1200.0,
            mount=MountModel(roll_deg=4.0, pitch_deg=-68.0, yaw_deg=yaw),
            seed=2,
        )
        r = estimate_mount(d.log.imu, gnss=d.log.gnss)
        assert r.converged
        err = np.degrees(np.linalg.norm(so3.log(r.R_pv @ d.mount.rotation())))
        assert err < 4.0

    def test_reports_failure_on_a_straight_road(self):
        """No turns, no yaw observability -- and it must say so, not guess."""
        d = simulate_drive("straight_motorway", route_length_m=1200.0, seed=2)
        r = estimate_mount(d.log.imu, gnss=d.log.gnss)
        assert not r.converged
        assert r.method == "no-turns"
        assert not np.isfinite(r.sigma_yaw_rad)

    def test_result_is_a_valid_rotation(self):
        d = simulate_drive("curvy_a_road", route_length_m=900.0, seed=2)
        r = estimate_mount(d.log.imu, gnss=d.log.gnss)
        assert np.allclose(r.R_pv @ r.R_pv.T, np.eye(3), atol=1e-9)
        assert np.isclose(np.linalg.det(r.R_pv), 1.0, atol=1e-9)


class TestCurvatureSignatureAlignment:
    def _window(self, d, t_end, span_s=30.0, seed=0):
        rng = np.random.default_rng(seed)
        gt = d.truth
        sel = (gt.t > t_end - span_s) & (gt.t <= t_end)
        psi = gt.psi[sel] + rng.normal(0, 0.004)
        s_hat = gt.s[sel] * 1.01  # a residual 1 % speed-scale error
        prior = gt.s[sel][0] + rng.normal(0, 60.0)  # position prior 60 m out
        return psi, s_hat, prior, gt.s[sel][-1]

    def test_registers_a_curvy_road_to_metres(self):
        """docs/03-approach.md 3.5 predicts 3-12 m at a curvature landmark."""
        d = simulate_drive("curvy_a_road", route_length_m=1500.0, seed=3)
        the_map = d.path.perturbed(1.5, np.random.default_rng(0))
        errs = []
        for t_end in np.arange(40.0, d.truth.t[-1] - 1.0, 12.0):
            psi, s_hat, prior, s_true = self._window(d, t_end)
            if len(psi) < 50:
                continue
            fix = align_heading_profile(the_map, psi, s_hat, s0_prior=prior)
            if fix.observable:
                errs.append(abs(fix.s - s_true))
        assert len(errs) >= 4
        assert float(np.median(errs)) < 8.0

    def test_is_blind_on_a_straight_road_and_says_so(self):
        """The honest failure. CSA reporting confidence here would be a lie.

        It is also precisely why SVO and CTS exist -- see
        test_complementary_to_svo in test_measurements.py.
        """
        d = simulate_drive("straight_motorway", route_length_m=1500.0, seed=3)
        the_map = d.path.perturbed(1.5, np.random.default_rng(0))
        for t_end in np.arange(40.0, d.truth.t[-1] - 1.0, 15.0):
            psi, s_hat, prior, _ = self._window(d, t_end)
            if len(psi) < 50:
                continue
            fix = align_heading_profile(the_map, psi, s_hat, s0_prior=prior)
            assert not fix.observable
            assert not np.isfinite(fix.sigma_s) or fix.sigma_s > 20.0

    def _z_scores(self, route, seed=3, step=10.0):
        d = simulate_drive(route, route_length_m=1500.0, seed=seed)
        the_map = d.path.perturbed(1.5, np.random.default_rng(0))
        z = []
        for t_end in np.arange(40.0, d.truth.t[-1] - 1.0, step):
            psi, s_hat, prior, s_true = self._window(d, t_end)
            if len(psi) < 50:
                continue
            fix = align_heading_profile(the_map, psi, s_hat, s0_prior=prior)
            if fix.observable:
                z.append(abs(fix.s - s_true) / fix.sigma_s)
        return np.array(z)

    def test_uncertainty_is_calibrated_on_a_non_repeating_road(self):
        """Errors must mostly lie inside the stated sigma."""
        z = self._z_scores("curvy_a_road")
        assert len(z) >= 5
        assert float(np.mean(z < 3.0)) > 0.85

    def test_a_repeating_urban_grid_aliases(self):
        """A known and structural failure mode, recorded rather than tuned away.

        A grid of near-identical blocks is self-similar in curvature, so the
        cost surface has several almost equally deep minima and CSA can lock
        confidently onto the wrong one. On the urban route this produces a rare
        fix that is tens of metres out while reporting a small sigma -- not
        noise, but a genuine mis-registration.

        The mitigation is not a better sigma; it is refusing to commit to one
        hypothesis. That is exactly the job of the Rao-Blackwellised particle
        filter over the road graph in docs/03-approach.md 3.7, which this
        increment does not yet implement. Until it does, this test documents the
        exposure so that a later change cannot quietly claim to have fixed it.
        """
        z = self._z_scores("urban_canyon")
        assert len(z) >= 5
        # Most fixes are fine ...
        assert float(np.mean(z < 3.0)) > 0.7
        # ... but at least one gross, confidently-wrong outlier is expected here,
        # and its absence would mean this test has stopped measuring anything.
        assert float(z.max()) > 10.0

    def test_short_window_is_rejected(self):
        d = simulate_drive("curvy_a_road", route_length_m=600.0, seed=3)
        psi, s_hat, prior, _ = self._window(d, 20.0, span_s=2.0)
        fix = align_heading_profile(d.path, psi, s_hat, s0_prior=prior)
        assert not fix.observable

    def test_decimation_does_not_change_the_answer(self):
        """A 200 Hz heading trace holds no more shape than a metre-spaced one."""
        d = simulate_drive("curvy_a_road", route_length_m=1200.0, seed=3)
        psi, s_hat, prior, _ = self._window(d, 60.0)
        coarse = align_heading_profile(d.path, psi, s_hat, s0_prior=prior)
        fine = align_heading_profile(
            d.path, psi, s_hat, s0_prior=prior, config=CsaConfig(max_window_samples=100000)
        )
        assert coarse.observable == fine.observable
        if coarse.observable:
            assert abs(coarse.s - fine.s) < 2.0
