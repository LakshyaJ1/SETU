"""SO(3): rotations, their exponential map and the Jacobians the filter needs.

Everything here is written for float64 and for correctness at every angle,
including near 0 and near pi. The near-pi case matters more than it usually does
in navigation code: SETU cold-starts with an unknown phone mount, so the initial
attitude error can be arbitrarily large (docs/03-approach.md 3.7), and a `log`
that degraded near pi would corrupt exactly the situation the right-invariant
filter exists to handle.

Series expansions take over below `SMALL_ANGLE`. The closed forms all have the
shape `f(t)/t^n`, which is 0/0 at the origin; the expansions are carried to
enough terms that the crossover is smooth to well past float64 resolution.
"""

from __future__ import annotations

import numpy as np

from .constants import SMALL_ANGLE

__all__ = [
    "hat",
    "vee",
    "exp",
    "log",
    "left_jacobian",
    "left_jacobian_inv",
    "normalize",
    "from_euler_rpy",
    "to_euler_rpy",
    "from_quat",
    "to_quat",
]


def hat(v: np.ndarray) -> np.ndarray:
    """Skew-symmetric matrix such that ``hat(a) @ b == np.cross(a, b)``."""
    v = np.asarray(v, dtype=float).reshape(3)
    return np.array(
        [
            [0.0, -v[2], v[1]],
            [v[2], 0.0, -v[0]],
            [-v[1], v[0], 0.0],
        ]
    )


def vee(m: np.ndarray) -> np.ndarray:
    """Inverse of :func:`hat`. Uses the antisymmetric part, so it is total."""
    m = np.asarray(m, dtype=float).reshape(3, 3)
    return 0.5 * np.array([m[2, 1] - m[1, 2], m[0, 2] - m[2, 0], m[1, 0] - m[0, 1]])


def _exp_coeffs(theta: float) -> tuple[float, float]:
    """Rodrigues coefficients ``(sin t / t, (1 - cos t) / t**2)``."""
    if theta < SMALL_ANGLE:
        t2 = theta * theta
        return (
            1.0 - t2 / 6.0 + t2 * t2 / 120.0,
            0.5 - t2 / 24.0 + t2 * t2 / 720.0,
        )
    return np.sin(theta) / theta, (1.0 - np.cos(theta)) / (theta * theta)


def exp(phi: np.ndarray) -> np.ndarray:
    """Exponential map: rotation vector (axis * angle, rad) -> rotation matrix."""
    phi = np.asarray(phi, dtype=float).reshape(3)
    theta = float(np.linalg.norm(phi))
    k = hat(phi)
    a, b = _exp_coeffs(theta)
    return np.eye(3) + a * k + b * (k @ k)


def to_quat(r: np.ndarray) -> np.ndarray:
    """Rotation matrix -> unit quaternion ``[w, x, y, z]`` (Shepperd's method).

    Branching on the largest diagonal term keeps the divisor bounded away from
    zero for every input, which is what makes :func:`log` robust near pi.
    """
    r = np.asarray(r, dtype=float).reshape(3, 3)
    tr = r[0, 0] + r[1, 1] + r[2, 2]
    if tr > 0.0:
        s = np.sqrt(tr + 1.0) * 2.0
        q = np.array(
            [0.25 * s, (r[2, 1] - r[1, 2]) / s, (r[0, 2] - r[2, 0]) / s, (r[1, 0] - r[0, 1]) / s]
        )
    elif r[0, 0] > r[1, 1] and r[0, 0] > r[2, 2]:
        s = np.sqrt(1.0 + r[0, 0] - r[1, 1] - r[2, 2]) * 2.0
        q = np.array(
            [(r[2, 1] - r[1, 2]) / s, 0.25 * s, (r[0, 1] + r[1, 0]) / s, (r[0, 2] + r[2, 0]) / s]
        )
    elif r[1, 1] > r[2, 2]:
        s = np.sqrt(1.0 + r[1, 1] - r[0, 0] - r[2, 2]) * 2.0
        q = np.array(
            [(r[0, 2] - r[2, 0]) / s, (r[0, 1] + r[1, 0]) / s, 0.25 * s, (r[1, 2] + r[2, 1]) / s]
        )
    else:
        s = np.sqrt(1.0 + r[2, 2] - r[0, 0] - r[1, 1]) * 2.0
        q = np.array(
            [(r[1, 0] - r[0, 1]) / s, (r[0, 2] + r[2, 0]) / s, (r[1, 2] + r[2, 1]) / s, 0.25 * s]
        )
    q /= np.linalg.norm(q)
    return q if q[0] >= 0.0 else -q


def from_quat(q: np.ndarray) -> np.ndarray:
    """Unit quaternion ``[w, x, y, z]`` -> rotation matrix."""
    q = np.asarray(q, dtype=float).reshape(4)
    q = q / np.linalg.norm(q)
    w, x, y, z = q
    return np.array(
        [
            [1 - 2 * (y * y + z * z), 2 * (x * y - w * z), 2 * (x * z + w * y)],
            [2 * (x * y + w * z), 1 - 2 * (x * x + z * z), 2 * (y * z - w * x)],
            [2 * (x * z - w * y), 2 * (y * z + w * x), 1 - 2 * (x * x + y * y)],
        ]
    )


def log(r: np.ndarray) -> np.ndarray:
    """Logarithm map: rotation matrix -> rotation vector, valid for all angles.

    Routed through the quaternion because the direct trace formula
    ``theta / (2 sin theta) * vee(R - R.T)`` loses all precision as theta -> pi,
    where ``sin theta -> 0`` while the numerator stays finite.
    """
    q = to_quat(r)
    w = float(np.clip(q[0], -1.0, 1.0))
    v = q[1:]
    n = float(np.linalg.norm(v))
    if n < SMALL_ANGLE:
        # theta ~ 2n/w; the (1 - n^2/(3 w^2)) factor is the next series term.
        return 2.0 * v / w * (1.0 - (n * n) / (3.0 * w * w))
    theta = 2.0 * np.arctan2(n, w)
    return theta * v / n


def left_jacobian(phi: np.ndarray) -> np.ndarray:
    """Left Jacobian of SO(3), ``Jl``, with ``exp(phi + d) ~= exp(Jl d) exp(phi)``."""
    phi = np.asarray(phi, dtype=float).reshape(3)
    theta = float(np.linalg.norm(phi))
    k = hat(phi)
    t2 = theta * theta
    if theta < SMALL_ANGLE:
        b = 0.5 - t2 / 24.0
        c = 1.0 / 6.0 - t2 / 120.0
    else:
        b = (1.0 - np.cos(theta)) / t2
        c = (theta - np.sin(theta)) / (t2 * theta)
    return np.eye(3) + b * k + c * (k @ k)


def left_jacobian_inv(phi: np.ndarray) -> np.ndarray:
    """Inverse of :func:`left_jacobian`, in closed form."""
    phi = np.asarray(phi, dtype=float).reshape(3)
    theta = float(np.linalg.norm(phi))
    k = hat(phi)
    if theta < SMALL_ANGLE:
        d = 1.0 / 12.0 + (theta * theta) / 720.0
    else:
        half = 0.5 * theta
        # cot(theta/2) written via cos/sin to keep it to one trig pair.
        d = (1.0 - half * np.cos(half) / np.sin(half)) / (theta * theta)
    return np.eye(3) - 0.5 * k + d * (k @ k)


def normalize(r: np.ndarray) -> np.ndarray:
    """Project a near-rotation back onto SO(3) (nearest in Frobenius norm).

    Called after propagation so accumulated float error never lets the attitude
    block drift off the manifold.
    """
    u, _, vt = np.linalg.svd(np.asarray(r, dtype=float).reshape(3, 3))
    d = np.sign(np.linalg.det(u @ vt))
    return u @ np.diag([1.0, 1.0, d]) @ vt


def from_euler_rpy(roll: float, pitch: float, yaw: float) -> np.ndarray:
    """Aerospace Z-Y-X: ``R = Rz(yaw) @ Ry(pitch) @ Rx(roll)``."""
    cr, sr = np.cos(roll), np.sin(roll)
    cp, sp = np.cos(pitch), np.sin(pitch)
    cy, sy = np.cos(yaw), np.sin(yaw)
    return np.array(
        [
            [cy * cp, cy * sp * sr - sy * cr, cy * sp * cr + sy * sr],
            [sy * cp, sy * sp * sr + cy * cr, sy * sp * cr - cy * sr],
            [-sp, cp * sr, cp * cr],
        ]
    )


def to_euler_rpy(r: np.ndarray) -> tuple[float, float, float]:
    """Inverse of :func:`from_euler_rpy`. Gimbal-locks at pitch = +-90 deg."""
    r = np.asarray(r, dtype=float).reshape(3, 3)
    pitch = float(np.arcsin(-np.clip(r[2, 0], -1.0, 1.0)))
    if abs(r[2, 0]) < 1.0 - 1e-10:
        roll = float(np.arctan2(r[2, 1], r[2, 2]))
        yaw = float(np.arctan2(r[1, 0], r[0, 0]))
    else:  # gimbal lock: roll and yaw are degenerate, fold everything into yaw
        roll = 0.0
        yaw = float(np.arctan2(-r[0, 1], r[1, 1]))
    return roll, pitch, yaw
