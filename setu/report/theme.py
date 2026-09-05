"""Visual tokens for the SETU report.

The world is a **dark instrument panel**, chosen from the use scene rather than
from category habit: an engineer reading experiment output, and a subject that
is literally the absence of signal. Traces read against a dark ground the way
they do on any telemetry instrument, and the dark is earned by the topic rather
than applied as a default.

The categorical series palette is not a matter of taste -- it was run through the
dataviz validator against this exact surface and passes every check:

    lightness band   all inside L 0.48-0.67
    chroma floor     all >= 0.1
    CVD separation   worst adjacent dE 9.2 (protan), 13.5 (tritan)
    normal vision    worst adjacent dE 17.5
    contrast         all >= 3:1 against #0D1319

Two earlier candidates failed and are recorded here so nobody re-derives them:
a green/amber/red set put the amber and red too close in hue (normal-vision dE
12-14, unreadable for anyone), and brighter versions of all three sat above the
lightness band, which would have given the three series unequal visual weight.
The red is therefore pushed to crimson, away from the amber.
"""

from __future__ import annotations

__all__ = ["TOKENS", "SERIES", "CSS_VARIABLES"]

# -- surfaces and ink ---------------------------------------------------------
TOKENS: dict[str, str] = {
    # Ground is a desaturated blue-black, never pure black: pure black kills the
    # sense of depth and makes every shadow invisible.
    "ground": "#0D1319",
    "panel": "#141C25",
    "panel_raised": "#1A242F",
    "rule": "#26323F",
    "rule_strong": "#33424F",
    # Ink is tinted from the surface hue rather than gray, per the craft floor.
    "ink": "#E8EEF4",
    "ink_secondary": "#A9BAC9",
    "ink_muted": "#71889B",
    "ink_faint": "#4A5C6D",
    "accent": "#28A876",
    "accent_bright": "#3FCB92",
    "warn": "#C08A1F",
    "bad": "#D6455F",
    "focus": "#4DA8E8",
}

# -- categorical series, in fixed order (never cycled) ------------------------
SERIES: dict[str, dict[str, str]] = {
    "SETU": {
        "color": "#28A876",
        "label": "SETU",
        "detail": "spectral odometer + coordinated turn + curvature registration",
        "dash": "",
        "width": "2.6",
    },
    "B2_ins_nhc_zupt": {
        "color": "#C08A1F",
        "label": "B2 · INS + NHC + ZUPT",
        "detail": "the honest classical baseline, well tuned",
        "dash": "7 4",
        "width": "2",
    },
    "B1_ins": {
        "color": "#D6455F",
        "label": "B1 · pure inertial",
        "detail": "strapdown only, the divergence the design exists to avoid",
        "dash": "2 4",
        "width": "2",
    },
    "B4_speed_only": {
        "color": "#4DA8E8",
        "label": "B4 · speed aiding, no map",
        "detail": "isolates what registration contributes",
        "dash": "5 3",
        "width": "2",
    },
}


CSS_VARIABLES = "\n".join(f"      --{k.replace('_', '-')}: {v};" for k, v in TOKENS.items())
