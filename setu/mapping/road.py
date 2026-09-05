"""Arc-length parameterised road geometry.

This is the "road manifold" of ``docs/03-approach.md`` 3.1 made concrete: a
directed edge carries heading ``psi(s)`` and curvature ``kappa(s)`` sampled at a
fixed spacing, which is exactly the lookup table the offline map pipeline emits
(``docs/06-tech-stack.md`` 6.6) and exactly what CSA registers against.

One representation serves both the simulator and the estimator. To keep that
from becoming a test that only proves the code agrees with itself, the
simulator drives the *true* geometry while the estimator is handed
:meth:`RoadPath.perturbed`, which injects the metre-level geometry error real
OpenStreetMap centrelines have (``docs/03-approach.md`` 3.10).
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

__all__ = ["RoadPath", "wrap_angle"]


def wrap_angle(a: np.ndarray | float) -> np.ndarray | float:
    """Wrap angle(s) to ``(-pi, pi]``."""
    return (np.asarray(a) + np.pi) % (2.0 * np.pi) - np.pi


def _uniform_grid(total: float, ds: float) -> tuple[np.ndarray, float]:
    """Uniform arc-length grid that includes **both** endpoints exactly.

    ``arange`` would truncate the final partial cell, which silently shortens the
    edge by up to ``ds``. Arc length is the quantity CSA estimates, so an edge
    that misreports its own length by a metre is an error injected straight into
    the measurement it feeds. Instead the spacing is nudged to divide the length
    exactly; the returned spacing is the one actually used.
    """
    n = max(2, int(round(total / ds)) + 1)
    return np.linspace(0.0, total, n), total / (n - 1)


@dataclass(frozen=True)
class RoadPath:
    """A directed road edge sampled uniformly in arc length.

    Attributes
    ----------
    s : (N,) arc length from the edge start, metres, uniformly spaced by ``ds``.
    xy : (N, 2) planar position in the local ENU frame, metres.
    psi : (N,) heading, radians, **unwrapped** so that differencing is safe.
    kappa : (N,) signed curvature, 1/m; positive is a left turn.
    ds : sample spacing, metres.
    edge_id : identifier used by the map matcher and in logs.
    """

    s: np.ndarray
    xy: np.ndarray
    psi: np.ndarray
    kappa: np.ndarray
    ds: float
    edge_id: str = "e0"

    def __post_init__(self) -> None:
        n = self.s.shape[0]
        if self.xy.shape != (n, 2):
            raise ValueError(f"xy must be ({n}, 2), got {self.xy.shape}")
        if self.psi.shape != (n,) or self.kappa.shape != (n,):
            raise ValueError("psi and kappa must be one-dimensional and match s")
        if n < 2:
            raise ValueError("a path needs at least two samples")

    # -- construction -----------------------------------------------------
    @staticmethod
    def from_curvature_profile(
        segments: list[tuple[float, float]],
        *,
        ds: float = 1.0,
        origin: tuple[float, float] = (0.0, 0.0),
        psi0: float = 0.0,
        edge_id: str = "e0",
        integration_ds: float = 0.05,
    ) -> RoadPath:
        """Build a path from ``[(length_m, curvature_1pm), ...]``.

        Curvature is piecewise constant, so each segment is either a straight
        line (``kappa == 0``) or a circular arc of radius ``1 / kappa``. Heading
        and position come from integrating

            psi(s) = psi0 + \\int kappa ds,    xy(s) = xy0 + \\int (cos psi, sin psi) ds

        on a fine grid (``integration_ds``) and resampling to ``ds``. Integrating
        finely and then decimating keeps the closure error of a long arc far
        below the map's own geometry error.
        """
        if not segments:
            raise ValueError("need at least one segment")
        if any(length <= 0 for length, _ in segments):
            raise ValueError("segment lengths must be positive")

        total = float(sum(length for length, _ in segments))
        n_fine = int(np.ceil(total / integration_ds)) + 1
        s_fine = np.linspace(0.0, total, n_fine)

        # Piecewise-constant curvature sampled on the fine grid.
        edges = np.cumsum([0.0] + [length for length, _ in segments])
        kappa_fine = np.empty(n_fine)
        idx = np.clip(np.searchsorted(edges, s_fine, side="right") - 1, 0, len(segments) - 1)
        kappa_values = np.array([k for _, k in segments])
        kappa_fine[:] = kappa_values[idx]

        step = np.diff(s_fine, prepend=s_fine[0])
        psi_fine = psi0 + np.cumsum(kappa_fine * step)
        # Trapezoidal position integration; the heading is smooth so this is
        # second-order accurate and closes a 100 m radius circle to < 1 mm.
        cx, cy = np.cos(psi_fine), np.sin(psi_fine)
        x_fine = origin[0] + np.concatenate([[0.0], np.cumsum(0.5 * (cx[1:] + cx[:-1]) * step[1:])])
        y_fine = origin[1] + np.concatenate([[0.0], np.cumsum(0.5 * (cy[1:] + cy[:-1]) * step[1:])])

        s, actual_ds = _uniform_grid(total, ds)
        psi = np.interp(s, s_fine, psi_fine)
        return RoadPath(
            s=s,
            xy=np.column_stack([np.interp(s, s_fine, x_fine), np.interp(s, s_fine, y_fine)]),
            psi=psi,
            # Curvature is differentiated from the *stored* heading rather than
            # point-sampled from the generating profile. A sampled step function
            # does not integrate back to its own heading, and CSA integrates this
            # table; deriving it here makes the stored triple self-consistent at
            # the stored resolution, which is all a 1 m LUT can honestly claim.
            kappa=np.gradient(psi, actual_ds),
            ds=actual_ds,
            edge_id=edge_id,
        )

    @staticmethod
    def from_polyline(
        xy: np.ndarray,
        *,
        ds: float = 1.0,
        edge_id: str = "e0",
        smooth_window: int = 21,
    ) -> RoadPath:
        """Build a path from an arbitrary polyline (e.g. an OSM way).

        Curvature is differentiated from the resampled heading with a
        Savitzky-Golay filter, matching the offline pipeline in
        ``docs/06-tech-stack.md`` 6.6. Raw finite differences on OSM vertices are
        unusable -- vertex spacing is irregular and curvature comes out as noise.
        """
        from scipy.signal import savgol_filter

        xy = np.asarray(xy, dtype=float)
        if xy.ndim != 2 or xy.shape[1] != 2 or xy.shape[0] < 3:
            raise ValueError("polyline must be (N >= 3, 2)")

        seg = np.linalg.norm(np.diff(xy, axis=0), axis=1)
        s_raw = np.concatenate([[0.0], np.cumsum(seg)])
        total = float(s_raw[-1])
        s, actual_ds = _uniform_grid(total, ds)
        pts = np.column_stack([np.interp(s, s_raw, xy[:, 0]), np.interp(s, s_raw, xy[:, 1])])

        dxy = np.gradient(pts, actual_ds, axis=0)
        psi = np.unwrap(np.arctan2(dxy[:, 1], dxy[:, 0]))
        win = min(smooth_window if smooth_window % 2 else smooth_window + 1, len(s))
        if win >= 5:
            kappa = savgol_filter(psi, win, polyorder=3, deriv=1, delta=actual_ds)
        else:  # too short to smooth; accept the noisier estimate
            kappa = np.gradient(psi, actual_ds)
        return RoadPath(s=s, xy=pts, psi=psi, kappa=kappa, ds=actual_ds, edge_id=edge_id)

    # -- queries ----------------------------------------------------------
    @property
    def length(self) -> float:
        return float(self.s[-1])

    def position_at(self, s: np.ndarray | float) -> np.ndarray:
        """Interpolated position at arc length ``s``; clamped to the edge."""
        s = np.asarray(s, dtype=float)
        return np.stack(
            [np.interp(s, self.s, self.xy[:, 0]), np.interp(s, self.s, self.xy[:, 1])], axis=-1
        )

    def heading_at(self, s: np.ndarray | float) -> np.ndarray:
        """Interpolated (unwrapped) heading at arc length ``s``."""
        return np.interp(np.asarray(s, dtype=float), self.s, self.psi)

    def curvature_at(self, s: np.ndarray | float) -> np.ndarray:
        """Interpolated curvature at arc length ``s``."""
        return np.interp(np.asarray(s, dtype=float), self.s, self.kappa)

    def project(self, point: np.ndarray) -> tuple[float, float]:
        """Nearest point on the path: returns ``(arc_length, signed_cross_track)``.

        Cross-track is positive to the left of the direction of travel, which is
        the sign convention the filter's cross-track constraint expects.
        """
        point = np.asarray(point, dtype=float).reshape(2)
        d = self.xy - point
        i = int(np.argmin(np.einsum("ij,ij->i", d, d)))

        # Refine within the neighbouring segment by projecting onto the local
        # tangent; nearest-vertex alone quantises the answer to ds.
        lo, hi = max(i - 1, 0), min(i + 1, len(self.s) - 1)
        best_s, best_ct, best_d2 = float(self.s[i]), 0.0, float(np.inf)
        for a, b in ((lo, i), (i, hi)):
            if a == b:
                continue
            seg = self.xy[b] - self.xy[a]
            seg_len2 = float(seg @ seg)
            if seg_len2 <= 0.0:
                continue
            t = float(np.clip((point - self.xy[a]) @ seg / seg_len2, 0.0, 1.0))
            foot = self.xy[a] + t * seg
            delta = point - foot
            d2 = float(delta @ delta)
            if d2 < best_d2:
                tangent = seg / np.sqrt(seg_len2)
                best_d2 = d2
                best_s = float(self.s[a] + t * (self.s[b] - self.s[a]))
                best_ct = float(tangent[0] * delta[1] - tangent[1] * delta[0])
        return best_s, best_ct

    # -- derived paths ----------------------------------------------------
    def perturbed(self, sigma_m: float, rng: np.random.Generator, *, correlation_m: float = 60.0
                  ) -> RoadPath:
        """A copy with correlated lateral geometry error, as a real map has.

        OSM centreline error is not white -- it is smooth over tens of metres,
        because whole ways are digitised together. White noise would be trivially
        averaged away by CSA and would flatter the method, so the perturbation is
        a Gaussian-smoothed random field applied along the local normal.
        """
        from scipy.ndimage import gaussian_filter1d

        n = len(self.s)
        raw = rng.normal(size=n)
        smoothed = gaussian_filter1d(raw, sigma=max(correlation_m / self.ds, 1.0), mode="nearest")
        std = float(np.std(smoothed))
        offset = smoothed / std * sigma_m if std > 0 else np.zeros(n)

        normal = np.column_stack([-np.sin(self.psi), np.cos(self.psi)])
        return RoadPath.from_polyline(
            self.xy + normal * offset[:, None], ds=self.ds, edge_id=self.edge_id
        )

    def resampled(self, ds: float) -> RoadPath:
        """The same geometry at a different sample spacing."""
        s, actual_ds = _uniform_grid(self.length, ds)
        return RoadPath(
            s=s,
            xy=self.position_at(s),
            psi=self.heading_at(s),
            kappa=self.curvature_at(s),
            ds=actual_ds,
            edge_id=self.edge_id,
        )
