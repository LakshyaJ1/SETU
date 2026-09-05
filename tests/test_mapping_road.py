"""Road geometry tests.

The arc and circle cases have closed-form answers, so these check the
integrator against exact geometry rather than against a stored snapshot.
"""

from __future__ import annotations

import numpy as np
import pytest

from setu.mapping import RoadPath, build_route, route_names, wrap_angle


class TestFromCurvatureProfile:
    def test_straight_line(self):
        p = RoadPath.from_curvature_profile([(100.0, 0.0)])
        assert np.isclose(p.length, 100.0)
        assert np.allclose(p.xy[:, 1], 0.0, atol=1e-9)
        assert np.allclose(p.psi, 0.0, atol=1e-12)
        assert np.allclose(p.kappa, 0.0)
        assert np.allclose(p.position_at(50.0), [50.0, 0.0], atol=1e-6)

    def test_full_circle_closes(self):
        """A 2 pi R arc must return to its origin -- the integrator's hardest case."""
        radius = 100.0
        p = RoadPath.from_curvature_profile([(2 * np.pi * radius, 1.0 / radius)], ds=0.5)
        assert np.linalg.norm(p.xy[-1] - p.xy[0]) < 0.02
        assert np.isclose(p.psi[-1] - p.psi[0], 2 * np.pi, atol=1e-6)

    def test_quarter_circle_geometry(self):
        """Exact endpoint of a left quarter-turn starting east from the origin."""
        radius = 50.0
        p = RoadPath.from_curvature_profile([(0.5 * np.pi * radius, 1.0 / radius)], ds=0.25)
        assert np.allclose(p.xy[-1], [radius, radius], atol=1e-3)
        assert np.isclose(p.psi[-1], np.pi / 2, atol=1e-7)

    def test_curvature_sign_convention(self):
        """Positive curvature turns left (heading increases)."""
        left = RoadPath.from_curvature_profile([(50.0, 1.0 / 100.0)])
        right = RoadPath.from_curvature_profile([(50.0, -1.0 / 100.0)])
        assert left.psi[-1] > 0 and right.psi[-1] < 0

    def test_radius_matches_curvature(self):
        """Fitted radius of the sampled arc equals 1 / kappa."""
        radius = 75.0
        p = RoadPath.from_curvature_profile([(0.9 * np.pi * radius, 1.0 / radius)], ds=0.5)
        centre = p.xy[0] + radius * np.array([-np.sin(p.psi[0]), np.cos(p.psi[0])])
        r_fit = np.linalg.norm(p.xy - centre, axis=1)
        assert np.allclose(r_fit, radius, atol=5e-3)

    def test_rejects_bad_input(self):
        with pytest.raises(ValueError):
            RoadPath.from_curvature_profile([])
        with pytest.raises(ValueError):
            RoadPath.from_curvature_profile([(-10.0, 0.0)])


class TestQueries:
    def test_heading_and_curvature_interpolation(self):
        radius = 200.0
        p = RoadPath.from_curvature_profile([(300.0, 1.0 / radius)])
        assert np.isclose(p.curvature_at(150.0), 1.0 / radius, atol=1e-9)
        assert np.isclose(p.heading_at(150.0), 150.0 / radius, atol=1e-6)

    def test_project_on_straight(self):
        p = RoadPath.from_curvature_profile([(100.0, 0.0)])
        s, ct = p.project(np.array([40.0, 3.0]))
        assert np.isclose(s, 40.0, atol=1e-6)
        assert np.isclose(ct, 3.0, atol=1e-6)  # left of travel is positive

    def test_project_sign_is_left_positive(self):
        p = RoadPath.from_curvature_profile([(100.0, 0.0)])
        _, ct_left = p.project(np.array([40.0, 2.5]))
        _, ct_right = p.project(np.array([40.0, -2.5]))
        assert ct_left > 0 > ct_right

    def test_project_recovers_own_points(self):
        p = build_route("curvy_a_road", length_m=600.0)
        for s_true in (25.0, 150.0, 400.0, 575.0):
            s_hat, ct = p.project(p.position_at(s_true))
            assert abs(s_hat - s_true) < 1.0
            assert abs(ct) < 0.05

    def test_project_is_subsample_accurate(self):
        """Refinement must beat the ds quantisation of nearest-vertex search."""
        p = RoadPath.from_curvature_profile([(100.0, 0.0)], ds=1.0)
        s, _ = p.project(np.array([40.37, 0.0]))
        assert abs(s - 40.37) < 0.02


class TestPolylineAndPerturbation:
    def test_polyline_roundtrip(self):
        p = build_route("curvy_a_road", length_m=500.0)
        q = RoadPath.from_polyline(p.xy, ds=p.ds)
        assert np.isclose(q.length, p.length, atol=1.0)
        n = min(len(p.s), len(q.s))
        assert np.max(np.linalg.norm(p.xy[:n] - q.xy[:n], axis=1)) < 0.2

    def test_perturbation_has_requested_magnitude(self):
        rng = np.random.default_rng(0)
        p = build_route("curvy_a_road", length_m=1500.0)
        q = p.perturbed(2.0, rng)
        n = min(len(p.s), len(q.s))
        offsets = np.linalg.norm(p.xy[:n] - q.xy[:n], axis=1)
        assert 0.5 < float(np.mean(offsets)) < 5.0

    def test_perturbation_is_spatially_correlated(self):
        """Neighbouring samples must move together, as a mis-digitised way does."""
        rng = np.random.default_rng(1)
        p = build_route("straight_motorway", length_m=1500.0)
        q = p.perturbed(2.0, rng, correlation_m=60.0)
        n = min(len(p.s), len(q.s))
        err = q.xy[:n, 1] - p.xy[:n, 1]
        assert abs(float(np.corrcoef(err[:-5], err[5:])[0, 1])) > 0.9

    def test_resample(self):
        p = build_route("curvy_a_road", length_m=400.0)
        q = p.resampled(0.5)
        assert np.isclose(q.ds, 0.5)
        assert np.allclose(q.position_at(200.0), p.position_at(200.0), atol=0.05)


class TestRoutes:
    @pytest.mark.parametrize("name", route_names())
    def test_heading_is_the_tangent_of_the_geometry(self, name):
        """Stored heading must be the actual direction of travel.

        For a constant-curvature cell the chord direction equals the mean of the
        cell's endpoint headings analytically, so the bulk of the path agrees to
        the integrator's floor -- 1e-6 rad is 6e-5 degrees, set by the 5 cm fine
        grid on the tightest (11 m) helix and far below anything navigation
        cares about. Any real defect -- a sign flip, a frame error, a bad
        interpolation -- lands two to four orders of magnitude above it.
        Cells straddling a curvature discontinuity cannot agree better than the
        heading change across one cell, so the maximum is bounded by that rather
        than by a tolerance pulled out of the air.
        """
        p = build_route(name)
        assert p.length > 50.0
        assert np.all(np.isfinite(p.xy))
        step = np.diff(p.xy, axis=0)
        psi_from_xy = np.arctan2(step[:, 1], step[:, 0])
        psi_mid = 0.5 * (p.psi[1:] + p.psi[:-1])
        err = np.abs(wrap_angle(psi_from_xy - psi_mid))

        assert float(np.median(err)) < 1e-6, "smooth cells must agree to integrator precision"
        cell_turn = float(np.max(np.abs(np.diff(p.psi))))
        assert float(np.max(err)) < 0.55 * cell_turn + 1e-6

    @pytest.mark.parametrize("name", route_names())
    def test_curvature_integrates_back_to_heading(self, name):
        """``psi(s) = psi(0) + \\int kappa ds`` -- the relation CSA depends on.

        Bounded by one cell's worth of turning, which is the resolution limit of
        any finite curvature table at a corner.
        """
        from scipy.integrate import cumulative_trapezoid

        p = build_route(name)
        psi_from_kappa = p.psi[0] + cumulative_trapezoid(p.kappa, dx=p.ds, initial=0.0)
        tol = max(1e-6, 0.35 * p.ds * float(np.max(np.abs(p.kappa))))
        assert np.max(np.abs(psi_from_kappa - p.psi)) < tol

    def test_straight_motorway_has_no_curvature(self):
        """The scenario that isolates SVO must genuinely offer CSA nothing."""
        p = build_route("straight_motorway")
        assert np.allclose(p.kappa, 0.0, atol=1e-12)

    def test_roundabout_route_turns_a_lot(self):
        p = build_route("roundabout_route")
        assert abs(p.psi[-1] - p.psi[0]) > 2 * np.pi
