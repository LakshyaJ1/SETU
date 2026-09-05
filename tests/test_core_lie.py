"""Manifold algebra tests.

These are the tests that catch sign and Jacobian errors before they reach the
filter, where they present as a slow divergence that is very hard to attribute.
Every assertion is against an identity that holds exactly in exact arithmetic,
so the tolerances are float64 tolerances rather than tuned thresholds.
"""

from __future__ import annotations

import numpy as np
import pytest

from setu.core import se23, so3

RNG = np.random.default_rng(20260905)


def random_rotvec(rng: np.random.Generator, max_angle: float = np.pi - 1e-9) -> np.ndarray:
    axis = rng.normal(size=3)
    axis /= np.linalg.norm(axis)
    return axis * rng.uniform(0.0, max_angle)


# --------------------------------------------------------------------- SO(3)
class TestSO3:
    def test_hat_is_cross_product(self):
        rng = np.random.default_rng(1)
        for _ in range(100):
            a, b = rng.normal(size=3), rng.normal(size=3)
            assert np.allclose(so3.hat(a) @ b, np.cross(a, b))

    def test_vee_inverts_hat(self):
        rng = np.random.default_rng(2)
        for _ in range(100):
            a = rng.normal(size=3)
            assert np.allclose(so3.vee(so3.hat(a)), a)

    def test_exp_produces_valid_rotations(self):
        rng = np.random.default_rng(3)
        for _ in range(500):
            r = so3.exp(random_rotvec(rng))
            assert np.allclose(r @ r.T, np.eye(3), atol=1e-13)
            assert np.isclose(np.linalg.det(r), 1.0, atol=1e-13)

    def test_log_inverts_exp(self):
        rng = np.random.default_rng(4)
        for _ in range(1000):
            phi = random_rotvec(rng)
            assert np.allclose(so3.log(so3.exp(phi)), phi, atol=1e-11)

    @pytest.mark.parametrize(
        "theta", [0.0, 1e-14, 1e-10, 1e-8, 1e-7, 1e-6, 1e-3, 1.0, np.pi - 1e-8, np.pi - 1e-12]
    )
    def test_log_exp_roundtrip_at_extremes(self, theta):
        """The series/closed-form crossover and the near-pi branch.

        Near pi is the case that motivates routing ``log`` through a quaternion:
        the naive trace formula divides by ``sin(theta)``.
        """
        axis = np.array([0.3, -0.5, 0.81])
        axis /= np.linalg.norm(axis)
        phi = axis * theta
        assert np.allclose(so3.log(so3.exp(phi)), phi, atol=1e-10)

    def test_exp_matches_scipy_rotation(self):
        """Cross-check against an independent implementation."""
        scipy_spatial = pytest.importorskip("scipy.spatial.transform")
        rng = np.random.default_rng(5)
        for _ in range(200):
            phi = random_rotvec(rng)
            expected = scipy_spatial.Rotation.from_rotvec(phi).as_matrix()
            assert np.allclose(so3.exp(phi), expected, atol=1e-12)

    def test_left_jacobian_inverse(self):
        rng = np.random.default_rng(6)
        for _ in range(500):
            phi = random_rotvec(rng)
            jl, jli = so3.left_jacobian(phi), so3.left_jacobian_inv(phi)
            assert np.allclose(jl @ jli, np.eye(3), atol=1e-10)

    def test_left_jacobian_at_identity(self):
        assert np.allclose(so3.left_jacobian(np.zeros(3)), np.eye(3))
        assert np.allclose(so3.left_jacobian_inv(np.zeros(3)), np.eye(3))

    def test_left_jacobian_defining_property(self):
        """``exp(phi + J_l^-1 d) ~= exp(d) exp(phi)`` to first order in d."""
        rng = np.random.default_rng(7)
        for _ in range(200):
            phi = random_rotvec(rng, max_angle=2.0)
            d = rng.normal(size=3) * 1e-6
            lhs = so3.exp(phi + so3.left_jacobian_inv(phi) @ d)
            rhs = so3.exp(d) @ so3.exp(phi)
            assert np.allclose(lhs, rhs, atol=1e-10)

    def test_normalize_repairs_drift(self):
        rng = np.random.default_rng(8)
        r = so3.exp(random_rotvec(rng)) + rng.normal(size=(3, 3)) * 1e-6
        rn = so3.normalize(r)
        assert np.allclose(rn @ rn.T, np.eye(3), atol=1e-14)
        assert np.isclose(np.linalg.det(rn), 1.0, atol=1e-14)

    def test_euler_roundtrip(self):
        rng = np.random.default_rng(9)
        for _ in range(300):
            roll = rng.uniform(-np.pi, np.pi)
            pitch = rng.uniform(-np.pi / 2 + 0.05, np.pi / 2 - 0.05)
            yaw = rng.uniform(-np.pi, np.pi)
            r = so3.from_euler_rpy(roll, pitch, yaw)
            got = so3.to_euler_rpy(r)
            assert np.allclose(got, (roll, pitch, yaw), atol=1e-10)

    def test_quaternion_roundtrip(self):
        rng = np.random.default_rng(10)
        for _ in range(300):
            r = so3.exp(random_rotvec(rng))
            assert np.allclose(so3.from_quat(so3.to_quat(r)), r, atol=1e-12)


# ------------------------------------------------------------------ SE_2(3)
def random_pose(rng: np.random.Generator) -> se23.ExtendedPose:
    return se23.ExtendedPose(
        so3.exp(random_rotvec(rng)), rng.normal(size=3) * 5.0, rng.normal(size=3) * 50.0
    )


class TestSE23:
    def test_matrix_roundtrip(self):
        rng = np.random.default_rng(11)
        for _ in range(100):
            x = random_pose(rng)
            y = se23.ExtendedPose.from_matrix(x.matrix())
            assert np.allclose(x.R, y.R) and np.allclose(x.v, y.v) and np.allclose(x.p, y.p)

    def test_compose_matches_matrix_product(self):
        """The dataclass composition must agree with the 5x5 embedding."""
        rng = np.random.default_rng(12)
        for _ in range(200):
            a, b = random_pose(rng), random_pose(rng)
            assert np.allclose((a @ b).matrix(), a.matrix() @ b.matrix(), atol=1e-10)

    def test_inverse(self):
        rng = np.random.default_rng(13)
        for _ in range(200):
            x = random_pose(rng)
            assert np.allclose((x @ x.inverse()).matrix(), np.eye(5), atol=1e-10)
            assert np.allclose(x.inverse().matrix(), np.linalg.inv(x.matrix()), atol=1e-10)

    def test_exp_log_roundtrip(self):
        rng = np.random.default_rng(14)
        for _ in range(500):
            xi = np.concatenate([random_rotvec(rng), rng.normal(size=3), rng.normal(size=3) * 10])
            assert np.allclose(se23.log(se23.exp(xi)), xi, atol=1e-9)

    def test_exp_matches_matrix_exponential(self):
        """``exp`` must equal the true matrix exponential of the algebra element."""
        scipy_linalg = pytest.importorskip("scipy.linalg")
        rng = np.random.default_rng(15)
        for _ in range(100):
            xi = np.concatenate(
                [random_rotvec(rng, 2.5), rng.normal(size=3), rng.normal(size=3) * 3]
            )
            alg = np.zeros((5, 5))
            alg[:3, :3] = so3.hat(xi[0:3])
            alg[:3, 3] = xi[3:6]
            alg[:3, 4] = xi[6:9]
            assert np.allclose(se23.exp(xi).matrix(), scipy_linalg.expm(alg), atol=1e-9)

    def test_adjoint_identity(self):
        """``X exp(xi) X^-1 == exp(Ad_X xi)`` -- the property the filter relies on."""
        rng = np.random.default_rng(16)
        for _ in range(200):
            x = random_pose(rng)
            xi = np.concatenate([random_rotvec(rng, 1.0), rng.normal(size=3), rng.normal(size=3)])
            lhs = (x @ se23.exp(xi) @ x.inverse()).matrix()
            rhs = se23.exp(x.adjoint() @ xi).matrix()
            assert np.allclose(lhs, rhs, atol=1e-8)

    def test_boxplus_boxminus_roundtrip(self):
        rng = np.random.default_rng(17)
        for _ in range(200):
            x = random_pose(rng)
            xi = np.concatenate(
                [random_rotvec(rng, 0.5), rng.normal(size=3) * 0.1, rng.normal(size=3) * 0.1]
            )
            y = x.boxplus_left(xi)
            assert np.allclose(y.boxminus_left(x), xi, atol=1e-9)

    def test_identity_element(self):
        i = se23.ExtendedPose()
        assert np.allclose(i.matrix(), np.eye(5))
        assert np.allclose(se23.log(i), np.zeros(9))
