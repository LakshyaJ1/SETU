"""Signal conditioning: the spectral front-end SVO reads."""

from .spectral import (
    RidgeTrack,
    SpectrogramResult,
    harmonic_sum,
    parabolic_refine,
    stft_magnitude,
    track_ridge,
)

__all__ = [
    "SpectrogramResult",
    "RidgeTrack",
    "stft_magnitude",
    "harmonic_sum",
    "track_ridge",
    "parabolic_refine",
]
