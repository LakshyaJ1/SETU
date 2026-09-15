# Deadline demo and local training — 2026-09-15

The user requested a curvier presentation demo and local training if it could
finish within 20–25 minutes. Neither request changes the agreed 90%-within-10-m
GPS-free positioning target or permits an unvalidated model to steer navigation.

## Completed CPU training

The host has Intel UHD integrated graphics and approximately 16 GB RAM, not an
NVIDIA CUDA GPU. A four-thread TensorFlow CPU run completed in **407.9 seconds
(6.8 minutes)**, including bundle conversion, three whole-ride-held-out fits and
a separate all-rides checkpoint. Each fit ran 40 epochs. An earlier eight-epoch
pilot established that the full experiment fit the time budget.

Only the three selected scooter rides are used: 1,124 accepted windows from the
9.007 km ride, 430 from the 2.387 km ride and 571 from the 3.423 km ride. The 28 m
recording is excluded. Inputs are causal four-second, 100 Hz, six-channel IMU
windows; quality-filtered GPS speed supplies labels, not network inputs.

| Whole ride held out | Speed MAE, m/s | Training-median MAE, m/s | Error p90, m/s | Predicted speed at rest p90, m/s |
| --- | ---: | ---: | ---: | ---: |
| 9.007 km | 2.383 | 2.019 | 6.259 | 1.734 |
| 2.387 km | 1.724 | 2.701 | 4.892 | 0.303 |
| 3.423 km | 0.844 | 1.361 | 1.889 | 2.911 |

The existing network architecture was trained from random weights: this is not
fine-tuning an available pretrained checkpoint. Held-out rides never contribute
windows to their respective training folds. However, all sessions share a phone
and day, mounts remain unconfirmed, and the longest ride retains its reported
late orientation change. These are exploratory development results, not unseen
field validation. The combined checkpoint has no independent evaluation.

The model improves over the simple speed baseline on two rides but still predicts
motion at rest. **It is not installed or fused into navigation.** No TFLite parity,
phone latency, uncertainty calibration or GPS-free position-accuracy approval is
claimed. The bundled Android model remains unchanged. Kaggle authentication is
still unavailable; this experiment ran locally without uploading private data.

Checkpoint:
`%LOCALAPPDATA%\SETU\phone-speed-research-20260915-40epochs\all-rides-candidate.weights.h5`.
The adjacent `report.json` and per-fold predictions/checkpoints retain the private
results. Coordinate-free evidence and checkpoint hashes are in
`verification/android/road-stress/cpu-training.json`; `../metrics.pdf` includes
the comparison.

`notebooks/research_phone_speed.py` implements the time-capped diagnostic path.
It preserves unconfirmed-mount provenance rather than rewriting it. The default
collection converter still rejects these recordings for production training,
and `notebooks/finetune_phone.py` explicitly refuses diagnostic datasets. The
four-independent-split production gates remain unchanged.

## Curvier native-engine demo

`PositioningDemo` now generates alternating left/right bends, deceleration into
corners, a full stop and acceleration away. The 24-second demonstration retains
the 6–14-second synthetic GPS gap and existing playback/phase controls. Both the
reference path and synthetic accelerometer/gyro inputs derive from the same
trajectory; the blue estimate still comes from the native engine, not a painted
copy of the reference. This is an illustrative input sequence, not road geometry
or a 120-second-warmup accuracy benchmark.

JVM tests check deterministic sampling, alternating turns, bounded speed and
acceleration, absence of teleporting, and IMU/reference kinematic consistency.
Visual phone inspection also exposed a pre-existing issue: after Activity
recreation, status text survived but the map could hide the route. The rendering
regression now requires the reference and estimated paths inside the visible map
viewport after recreation and theme changes, rather than checking labels alone.
Reference routes use green; ordinary planned driving routes remain blue.

## Installed development build and checks

APK: `../dist/android/SETU-curvy-demo.apk` (212,472,310 bytes).
SHA-256: `aee9c5706879a44790b62d4347df75e6bbe3366e08c1d564e6d4fa437a208d5b`.
The installed OnePlus APK matches, signature verification and 16 KiB ZIP
alignment pass, and all 37 original recordings remain byte-identical.

- 102 JVM tests and 49 focused Python tests pass. Ruff passes; Android lint has
  zero errors and 25 warnings. Python reports one ReportLab deprecation warning.
- The demo rendered-feature test passes in 48.641 seconds. It also passes when
  included with the other phone regressions.
- The separate 25-test phone regression run passes in 138.392 seconds.
- **The combined 26-test run is not green:** its map-disposal memory assertion
  measures 864,934 KiB process PSS against a 716,800 KiB ceiling. The other 25
  tests pass. An earlier intermediate build also failed this combined check at
  752,599 KiB. The limit was not raised and neither failure is discarded.

The full app also warms a roughly 238 MB memory-mapped routing graph; process PSS
is not a renderer-only measurement. This may contribute to the difference between
isolated and combined tests, but does not establish that the remaining memory
growth is harmless or resolved. No crash occurred in these runs. Memory under
extended mixed workflows remains an open investigation, not a passing release gate.
See `verification/android/road-stress/curvy-apk-verification.json` and its logs.

## Native turn-speed experiment not promoted

A bank-/bias-aware coordinated-turn speed prototype passed 162 closed-form
physics cases and ten guards, including arbitrary mounts, both turn directions,
grade, roll and vertical shocks. In the complete paired 675-trial native matrix,
however, its pseudo-speed filter integration regressed joint success in **23 of
45 Car conditions**, improving none. CV and unconstrained IMU were unchanged.

The production engine integration was reverted to its preceding version; the
candidate remains a standalone test model in `core/test/turn_speed_candidate.h`.
This is evidence that correct isolated kinematics does not establish correct
fusion. `verification/android/road-stress/turn-speed-v1/` preserves the negative
comparison. No navigation safety horizon was increased and no scooter mount was
invented to obtain a better score.

The 90% GPS-free target, independent field validation, approved model promotion
and subsequent final-release website remain incomplete.
