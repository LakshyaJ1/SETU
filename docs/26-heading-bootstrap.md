# GPS-motion heading bootstrap — 2026-09-15

**Development improvement, not navigation release approval.** The agreed target
remains at least 90% of expected GPS-free 10 Hz updates within 10 m of independent
reference across 10/30/60/120/180-second outages, including missing predictions
as failures. This change does not meet that target or replace the stricter gates.

## Finding

The existing motion-alignment initializer required three individually strong,
consistent 2–4-second velocity changes. In the 3.423 km ride, the offline diagnostic
found 109 eligible interval pairs, only two with both GPS and inertial velocity
changes above 2 m/s, and no interval passing all individual checks. Gentle motion
therefore often provided no initialization, even with 120 seconds of GPS warmup.

GPS callback latency did not explain the failure: the three recordings had median
latency of approximately 30–33 ms, p90 approximately 43 ms and maximum at most
123 ms; none exceeded 250 ms. Increasing individual intervals to six seconds also
failed to provide consistent checks in the fixed-position ride.

`tools/analyze_motion_alignment.py` provides a coordinate-free, causal diagnostic
of the velocity-change observations. Its interpolation and callback assembly are
not identical to Android execution; the physical-phone replay is authoritative.
Raw recordings and temporary analysis arrays remain under local AppData, not in
the repository or an uploaded training dataset.

## Implemented change

`MotionAlignment` retains the existing strong three-check path and adds a bounded
pooled initializer:

- Collect at most 30 interval pairs over the most recent 60 seconds of GPS-aided
  motion; divide velocity changes by their interval durations.
- Fit a two-dimensional relative rotation and constant horizontal acceleration
  offset using weighted, centred velocity-change rates. Weight combines reported
  GPS velocity uncertainty and a 0.15 m/s² inertial noise floor.
- Require heading sigma at most 0.5 radians, offset magnitude at most 0.35 m/s²,
  inertial/GPS excitation ratio within 0.65–1.35 and normalized residual at most 4.
- Require at least ten pairs and heading agreement within 20 degrees between two
  temporal halves, each containing at least five pairs. Constant velocity cannot
  identify a heading; unobservable fits are rejected.
- Clear pooled history on sensor/frame discontinuity, GPS gaps above four seconds
  or a change of mock-source status. A source-status change also clears heading.

The fitted offset is a nuisance parameter used only for heading initialization.
It is not a rewritten sensor measurement, an EKF bias correction or a new learned
model. The 15-degree uncertainty floor and subsequent heading-drift allowance
remain. These are experimental uncertainty models: neighbouring velocity changes
share GPS endpoints, and temporal halves are not independent field experiments.
They do not establish calibrated confidence or an accuracy guarantee.

The native 10-second / 150-metre uncertainty-radius guard is unchanged. Walking
continues to use its separate step-based tracker. Car-only constraints and the
Car-only evaluation speed model remain excluded from Two-wheeler operation.

## Matched physical-phone replay

The authorized OnePlus CPH2467 replayed the same three original recordings, with
120-second GPS warmup, withheld GPS, and a fixed 10 Hz scoring timeline. All 15
ride/outage combinations completed in 371.789 seconds. `reportLabel=pooled` keeps
these outputs separate from the earlier `v2` baseline.

| Ride | Outage | Expected | Available before → after | Within 10 m before → after |
| --- | ---: | ---: | ---: | ---: |
| 9.007 km | 10 s | 1,414 | 93 → 186 | 93 → 156 |
| 9.007 km | 30 s | 3,612 | 93 → 273 | 93 → 254 |
| 9.007 km | 60 s | 6,010 | 0 → 184 | 0 → 125 |
| 9.007 km | 120 s | 8,407 | 0 → 93 | 0 → 44 |
| 9.007 km | 180 s | 10,806 | 0 → 92 | 0 → 92 |
| 2.387 km | 10 s | 404 | 0 → 97 | 0 → 97 |
| 2.387 km | 30 s | 1,204 | 0 → 92 | 0 → 92 |
| 2.387 km | 60 s | 1,803 | 0 → 92 | 0 → 92 |
| 2.387 km | 120 s | 2,402 | 0 → 95 | 0 → 95 |
| 2.387 km | 180 s | 3,602 | 0 → 0 | 0 → 0 |
| 3.423 km | 10 s | 808 | 0 → 94 | 0 → 32 |
| 3.423 km | 30 s | 2,107 | 0 → 92 | 0 → 62 |
| 3.423 km | 60 s | 3,005 | 0 → 0 | 0 → 0 |
| 3.423 km | 120 s | 4,804 | 0 → 0 | 0 → 0 |
| 3.423 km | 180 s | 5,403 | 0 → 92 | 0 → 62 |

Twelve of fifteen conditions now contain predictions, versus two before. This
condition count is **not** an accuracy percentage. The 120/180-second rows contain
only short fragments, not continuous long-outage prediction. Newly available
predictions can still be inaccurate: the fixed-position ride's 10-second case
has conditional p90 separation of approximately 16.52 m.

`tools/compare_phone_replays.py` compares matching samples, not just totals. It
requires identical source hashes, protocols, counts, reference availability and
timestamps. All 186 formerly available/successful updates remain, with exactly
unchanged common-sample errors. No old successful point became inaccurate or
missing. Regression tests ensure a net improvement cannot conceal individual
lost successes, a changed timeline or a truncated trace.

Only quality-checked, bracketing GPS-provider observations form the withheld
reference. Poor or missing reference makes an update unscorable; it is never
credited as success. Known successes over all expected updates are conservative
diagnostic counts, not survey accuracy. Each outage duration has its own fixed
cycle grid and therefore different initialization periods.

These recordings informed development. They are not unseen validation sessions.
The 9 km ride retains the reported late orientation change, the 2.387 km ride
retains its scooter-storage provenance, and the 3.423 km ride retains fixed
position without inventing rigid-mount confirmation. The 28 m recording remains
excluded. All 37 original logs are still byte-identical; no recordings were deleted.

## Build and checks

- Installed debug APK: `../dist/android/SETU-heading-bootstrap.apk`.
- SHA-256: `6908ea59f2efe142d8fd61eb786e465a87bbd5fcfce3b41f3181c1cb488a6b64`.
- 100 JVM tests pass, including gentle biased motion, unobservable/excess-bias
  rejection and pooled-history reset checks.
- 25 final-build phone regressions pass in 140.491 seconds: collection/leakage,
  native engine, maps/routes, Walking, model consent/eligibility and Location
  off/on lifecycle. APK signature, installed hash and 16 KiB ZIP alignment pass.
- 41 focused Python tests pass; one ReportLab deprecation warning. Android lint
  succeeds with zero errors and 25 warnings; changed Python tools pass Ruff.
- The eight-page `../metrics.pdf` includes the matched comparison. New pages are
  visually inspected and all text bounds checked. The existing full-suite HTML
  report test failure remains separate; no full-suite-green claim is made.

Machine-readable comparison, APK metadata and test logs are under
`verification/android/road-stress/`. The earlier evaluation APK and baseline
measurements remain intact. The native synthetic benchmark still describes the
unchanged kernel; it does not test this Android heading initializer.

## Remaining release work

Long-outage drift, speed observability, scooter/mount assumptions, independent
field validation and proper model promotion remain unresolved. Kaggle MCP still
returns an authentication failure; no GPU training job or replacement model was
produced. A final navigation APK and the subsequent beta website must not be
declared complete from this limited initialization improvement.
