# On-phone recording and real-data training

## What ships

The [verification record](verification/android/collection-pipeline/README.md)
identifies the installed APK, measured phone capture and tests actually run.

The Android client records GPS and all available motion sensors concurrently into
its existing private, recoverable `.setulog` files. This is available on every
supported phone, not hard-coded to the USB test device. No account, server or
internet connection is required for capture, replay or bundle preparation.

In **Record**, select the actual vehicle in Settings, confirm the fixed mount,
name the drive, and start recording before driving. For the current speed model,
use **Car** only when that describes the vehicle. Leave location/GPS enabled
throughout data collection. Internet can be off. Secure the phone and let a
passenger operate the application. Save the drive, then choose **Trips → drive →
Export training bundle**. Review the privacy confirmation and pick a destination.
Keep SETU open while preparing the export. The original recording is unchanged.

GPS is a noisy reference, **not exact ground truth**. IMU sensors do not directly
measure coordinates. They need initialization and heading, then accumulate drift.
More data can improve a model; it cannot make phone-only dead reckoning perfect.

For on-foot trials select **Settings → Activity → Walking**. These recordings now
include platform `step_detector` events and `walkingStepLengthMeters` in collection
metadata. Their separate shadow replay uses the walking estimator, not vehicle
constraints. Walking is intentionally excluded from the vehicle-speed trainer;
do not relabel indoor walks as Car. Changing activity or step length during capture
marks the session as configuration-changed. See the
[walking investigation](23-walking-fallback-investigation.md) for calibration and limits.
Start recording before GPS/heading initialization when collecting a replayable
trial. An already-running estimator may depend on unrecorded earlier alignment;
cold replay correctly withholds if the saved data cannot initialize it. Do not
treat seeded diagnostic replay as independent accuracy validation or training truth.

## Bundle contract

`setu.training-bundle.v1` is a ZIP with exactly these members:

- `raw.setulog`: unchanged, full-rate measurements; not reduced to 1 Hz.
- `aligned.jsonl`: one row per completed second on the recording's monotonic
  clock. Raw GPS reference, GPS-aided native output and independent shadow output
  remain separate. Missing or stale observations are null, never fabricated.
- `manifest.json`: schema, recording metadata, quality counts, session warnings,
  raw/aligned byte lengths and SHA-256 checksums. Checksums detect corruption;
  they are not authentication or evidence of sensor accuracy.

New headers retain a random installation ID (not a hardware identifier), session
UUID, app/OS version, reported vehicle/mount, sensor names/ranges/resolutions,
units, model manifest and initial sharing configuration. New `gnss_reference`
records preserve provider, original measurement timestamp, receive timestamp,
wall time, mock flag and available accuracy fields **before** navigation's
latest-fix suppression. Thus a late GPS fix isn't silently lost for training.
Changing vehicle during recording invalidates the session for supervised training.

Sensor and GPS timestamps use `elapsedRealtimeNanos`, not wall-clock arrival.
The wall-time anchor is for provenance/day grouping. Epoch summaries choose the
latest observation at or before their endpoint, at most 1.5 seconds old, and
retain its actual timestamp/age. They do not claim simultaneous exact coordinates.
Each epoch reports accelerometer/gyro counts, invalid values and maximum gaps.

GPS references require a satellite provider, explicit non-mock origin, reported
position accuracy ≤10 m, speed uncertainty ≤1.5 m/s and speed 0–45 m/s. Epoch IMU
checks require ≥50 samples/second and no gap >50 ms. These are conservative
screening thresholds, not a proof of label correctness. Interrupted sessions,
drops, synthetic data, missing metadata, unconfirmed mounts and unsupported
vehicle labels remain exportable for diagnosis but are excluded by the trainer.
Old recordings retain original export/replay; their missing provenance cannot
be retroactively invented.

## Independent GPS-withheld route comparison

Bundle preparation replays the **recorded sensors** through a separate native
estimator, never the live navigation instance. Each 150-second cycle resets it,
allows good GPS during the first 120 seconds, then withholds GPS for 30 seconds.
This replaces the short 30-second warmup used by earlier diagnostic exports.
The manifest records the actual replay protocol; an export without replay does
not claim to have run one. Short recordings remain exportable but may contain no
complete GPS-withheld interval. Raw GPS/IMU training labels are unchanged.
GPS recording and live navigation are never disabled. This is a replay of real
measurements with a simulated outage, **not a physical GPS-off road validation**.

The shadow uses accelerometer, gyro, compass and available attitude sensors,
without the learned speed model. It is not a pure accelerometer integrator.
Delayed GPS received after the cutoff cannot enter the blackout, even if its
measurement timestamp precedes it. GPS-dependent alignment/calibration only uses
pre-cutoff fixes. References remain stored outside that estimator for comparison.
Recorded monotonic times can be replayed after a phone reboot.

The separate long-warmup phone benchmark scores complete 10/30/60/120/180-second
outages on a fixed 10 Hz grid, including missing outputs. Its results and the
native synthetic stress comparison are documented in
`verification/android/road-stress/README.md`. Archive epoch alignment remains
1 Hz; it must not be mistaken for the full benchmark scoring timeline.

Each shadow sample includes warmup/withheld phase, cutoff, cycle ID, heading
source, GPS acceptance count, covariance radius and either a position or an
explicit unavailable state. When a good GPS reference and the withheld estimate
have the same timestamp, `shadowReferenceErrorMeters` reports separation. Otherwise
the evaluator interpolates between two good GPS fixes bracketing the estimate,
at most 1.5 seconds and 100 metres apart, without extrapolation. The separate
`shadowComparisonReference` records the method and both source timestamps.
This fixes the old 250 ms comparison gate, which silently discarded the selected
rides' predictions because their GPS and output phases differed by about 0.66 s.
Interpolation is for retrospective evaluation only: `gpsReference`, raw logs,
training inputs and the withheld estimator are unchanged. No suitable reference
means null, not zero error. This is separation from noisy phone GPS, not survey
truth or exact synchronization. Native safety limits
can withhold an estimate before the 30-second trial ends. Do not hide that failure
or train on the GPS-aided `native_pose`/`track_pose` as independent IMU truth.

## Dataset preparation

Copy chosen ZIPs to a private workstation. Do not commit personal recordings.
Create a split plan, assigning complete sessions before looking at test results:

```json
[
  {"bundle":"drive-a.zip","group":"driver-a-route-a","split":"train"},
  {"bundle":"drive-b.zip","group":"driver-b-route-b","split":"validation"},
  {"bundle":"drive-c.zip","group":"driver-c-route-c","split":"calibration"},
  {"bundle":"drive-d.zip","group":"driver-d-route-d","split":"test"}
]
```

```powershell
python -m setu.collection private-data/plan.json private-data/dataset-v1
python notebooks/finetune_phone.py private-data/dataset-v1 --check-only
```

For a **separately evaluated scooter candidate**, pass `--vehicle Two-wheeler`
to `python -m setu.collection`. The default remains Car. All sessions must match
the requested activity and have a confirmed fixed mount. Only the warning that
Two-wheeler is outside the *bundled* Car model becomes advisory for this explicit
target; mount, drop, configuration-change and split checks remain blocking.
The dataset and fine-tuning report retain the target activity. This does not
enable the Car model on scooters or install a new model. The three rides in the
[scooter review](24-scooter-data-review.md) are not eligible: their mounts were
unconfirmed, and the same phone/day cannot populate independent splits.

The converter verifies checksums, header/manifest identity, schemas, sensor
timestamps, complete end marker, drop count, vehicle and mount. It produces
400×6 phone-body IMU windows on a 100 Hz grid with a one-second hop. GPS speed
is an explicitly noisy **label**, never an input channel. GPS coordinates are
separate reference arrays. Fused positions/model predictions are not labels.
Window interpolation cannot bridge gaps >50 ms or extrapolate missing IMU;
saturation is rejected. End-speed interpolation requires good bracketing GPS
observations no more than 1.5 s apart, without extrapolation. Each shard has
provenance, acceptance/rejection counts and a checksum in `dataset.json`.

Do not randomly split overlapping windows. Duplicate sessions, shared collection
groups and the same installation/UTC day cannot cross splits. Assign correlated
drivers, vehicles and routes to the same group yourself; software cannot infer
their identity from a sensor log. A single-phone multi-day split does **not**
demonstrate cross-phone generalization. The output directory must be new; a failed
conversion can leave partial shards but never a completed dataset manifest.

## Fine-tuning and promotion

The existing network predicts speed and uncertainty, not absolute coordinates.
Route accuracy also depends on heading, mount alignment and the native estimator;
speed-model fine-tuning alone cannot solve all of those errors.

Use a separate TensorFlow training environment compatible with `setu_model.py`
and the existing checkpoint. TensorFlow is not an Android dependency or a new
base Python dependency. Do not initialize randomly and call it fine-tuning.

```powershell
python notebooks/finetune_phone.py private-data/dataset-v1 --checkpoint path/to/best.weights.h5 --output private-data/candidate-v1 --epochs 10
```

Preflight requires at least 100 quality windows in **each** of train, validation,
calibration and test. This is an execution minimum, not enough evidence for
production accuracy. The script verifies shard hashes/splits again, loads the
existing checkpoint, freezes batch-normalization statistics, fine-tunes the
speed/loss heads with a small learning rate and validation early stopping, then
calibrates uncertainty on the separate calibration split. It reports held-out
GPS-reference MAE/p95, baseline MAE and 3-sigma coverage with provenance hashes.
It writes a candidate checkpoint/model and evaluation report, **never** overwrites
the APK assets or changes deployment approval. No personal data is uploaded.

Production promotion still requires multiple phones/mounts/vehicles, turns,
stops, rough roads, tunnels and long outages; independent wheel-speed/RTK reference
where possible; repeatable blackout trajectory errors and unavailable-rate;
TFLite parity, latency/thermal/battery tests; and reviewed uncertainty/manifest
gates. The current bundled model is Car-only and evaluation-only. This task adds
the collection/training path; it does not claim an already improved model.

## Operational boundaries

This is an implemented local-first pipeline, not a completed production fleet
service. Raw recordings remain app-private until explicit export and can be
deleted from Trips. Exported copies are user-owned and must be deleted separately.
Random installation IDs and coordinates are sensitive. Export destinations may
be cloud-backed Android document providers if the user chooses one.

Exports run on a background dispatcher with cancellation checks and temporary
ZIP staging. Keep the app open; background/process-death export resumption is
not implemented. Retry from the preserved original after interruption. Exports
are limited to six hours / 2 GB raw size and need space for the temporary ZIP
plus destination copy. Capture already reports storage drops and recovers
interrupted logs, but disk-pressure, screen-off, unplugged and long-drive behavior
still need release qualification. There is no automatic retention deletion,
upload, federated/on-phone training or model self-promotion.

## Previous review change count

Before this pipeline task, against pulled commit `8d0c613`: **25 tracked files,
407 insertions and 188 deletions**, excluding the user's `.vscode/settings.json`.
Additionally: **3 new Kotlin test files**, **1 audit document**, and **13 evidence
files** (including their README). The new files were untracked and therefore not
included in the tracked diff line totals. These counts describe files/lines,
not a claimed number of independent bug fixes. Changes remain uncommitted.

After this pipeline delivery, the combined diff against `8d0c613` has **31 modified
tracked files and 33 new files**, of which **19 new files are verification evidence**.
The user's editor settings remain excluded. These are working-tree counts, not commits.
