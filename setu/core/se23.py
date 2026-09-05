"""SE_2(3), the extended pose group: attitude, velocity and position as one object.

Why this group and not "a quaternion plus two vectors": strapdown IMU dynamics
are *group-affine* on SE_2(3), which means the right-invariant error
``eta = X_hat @ X^-1`` propagates with a Jacobian that does not depend on the
estimated state. That single property is what gives the right-invariant EKF its
convergence from large initial attitude error (docs/03-approach.md 3.7) and it
is the reason a generic EKF library was rejected in docs/06-tech-stack.md 6.10.

Matrix embedding, with R in SO(3) and v, p in R^3::

        [ R  v  p ]
    X = [ 0  1  0 ]
        [ 0  0  1 ]

Tangent vectors are ordered ``xi = [phi, nu, rho]`` (attitude, velocity,
position). That order is fixed here and every Jacobian in the filter follows it.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from . import so3

__all__ = ["ExtendedPose", "exp", "log", "adjoint", "DIM"]

DIM = 9  # dimension of the tangent space


def _eye3() -> np.ndarray:
    return np.eye(3)


def _zeros3() -> np.ndarray:
    return np.zeros(3)


@dataclass
class ExtendedPose:
    """An element of SE_2(3): navigation-frame attitude, velocity and position."""

    R: np.ndarray = field(default_factory=_eye3)
    v: np.ndarray = field(default_factory=_zeros3)
    p: np.ndarray = field(default_factory=_zeros3)

    def __post_init__(self) -> None:
        self.R = np.asarray(self.R, dtype=float).reshape(3, 3)
        self.v = np.asarray(self.v, dtype=float).reshape(3)
        self.p = np.asarray(self.p, dtype=float).reshape(3)

    # -- conversions ------------------------------------------------------
    def matrix(self) -> np.ndarray:
        """The 5x5 matrix embedding."""
        m = np.eye(5)
        m[:3, :3] = self.R
        m[:3, 3] = self.v
        m[:3, 4] = self.p
        return m

    @staticmethod
    def from_matrix(m: np.ndarray) -> ExtendedPose:
        m = np.asarray(m, dtype=float).reshape(5, 5)
        return ExtendedPose(m[:3, :3].copy(), m[:3, 3].copy(), m[:3, 4].copy())

    # -- group operations -------------------------------------------------
    def inverse(self) -> ExtendedPose:
        rt = self.R.T
        return ExtendedPose(rt, -rt @ self.v, -rt @ self.p)

    def compose(self, other: ExtendedPose) -> ExtendedPose:
        """``self @ other`` in the group."""
        return ExtendedPose(
            self.R @ other.R,
            self.R @ other.v + self.v,
            self.R @ other.p + self.p,
        )

    def __matmul__(self, other: ExtendedPose) -> ExtendedPose:
        return self.compose(other)

    def adjoint(self) -> np.ndarray:
        """9x9 adjoint: ``X exp(xi) X^-1 == exp(Ad_X xi)``."""
        return adjoint(self)

    def normalized(self) -> ExtendedPose:
        """Re-project the attitude block onto SO(3)."""
        return ExtendedPose(so3.normalize(self.R), self.v.copy(), self.p.copy())

    def copy(self) -> ExtendedPose:
        return ExtendedPose(self.R.copy(), self.v.copy(), self.p.copy())

    # -- error coordinates ------------------------------------------------
    def boxplus_left(self, xi: np.ndarray) -> ExtendedPose:
        """Right-invariant perturbation: ``exp(xi) @ self``.

        This is the convention the filter uses, so the state update is
        ``X <- exp(K y) @ X``.
        """
        return exp(xi).compose(self)

    def boxminus_left(self, other: ExtendedPose) -> np.ndarray:
        """Inverse of :meth:`boxplus_left`: ``log(self @ other^-1)``."""
        return log(self.compose(other.inverse()))

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        r, pi, y = so3.to_euler_rpy(self.R)
        deg = 180.0 / np.pi
        return (
            f"ExtendedPose(rpy_deg=[{r * deg:.2f}, {pi * deg:.2f}, {y * deg:.2f}], "
            f"v={np.round(self.v, 3).tolist()}, p={np.round(self.p, 2).tolist()})"
        )


def exp(xi: np.ndarray) -> ExtendedPose:
    """Exponential map of SE_2(3) from ``xi = [phi, nu, rho]``."""
    xi = np.asarray(xi, dtype=float).reshape(DIM)
    phi, nu, rho = xi[0:3], xi[3:6], xi[6:9]
    jl = so3.left_jacobian(phi)
    return ExtendedPose(so3.exp(phi), jl @ nu, jl @ rho)


def log(x: ExtendedPose) -> np.ndarray:
    """Logarithm map of SE_2(3), returning ``xi = [phi, nu, rho]``."""
    phi = so3.log(x.R)
    jinv = so3.left_jacobian_inv(phi)
    return np.concatenate([phi, jinv @ x.v, jinv @ x.p])


def adjoint(x: ExtendedPose) -> np.ndarray:
    """9x9 adjoint matrix of ``x``."""
    ad = np.zeros((DIM, DIM))
    ad[0:3, 0:3] = x.R
    ad[3:6, 0:3] = so3.hat(x.v) @ x.R
    ad[3:6, 3:6] = x.R
    ad[6:9, 0:3] = so3.hat(x.p) @ x.R
    ad[6:9, 6:9] = x.R
    return ad
