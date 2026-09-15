# Timestamped native GNSS/IMU engine

## Implemented path

Android `SensorHub` runs a `LiveEstimator` on its sensor HandlerThread. Its
bounded `ImuSynchronizer` interpolates accelerometer values to gyroscope
timestamps only when two acceleration samples bracket that timestamp and are
no more than 50 ms apart. Each queue holds at most 128 samples. Duplicate,
backwards, non-finite and unbracketed samples are counted rather than invented.
This is timestamp alignment, not the proposed FIR or sensor-clock-offset estimator.

Paired IMU reaches the native `SetuEngine`, which propagates the existing
16-state RI-EKF in phone-body / local ENU coordinates. GPS callbacks retain
their measurement timestamp and presence fields. The live adapter, not the
engine's caller-supplied clock, rejects future Android timestamps. Native GPS
more than 250 ms ahead of its current IMU is additionally rejected.

Native output is published at up to 5 Hz. Opting in to **Use native positioning**
in Diagnostics selects it for the map, route origin and guidance position when
it is no more than 300 ms old. Otherwise the application falls back to its GPS
observation, whose own freshness/provenance rules remain visible. Default-off is
an experimental safety boundary, not a claim of validated driving accuracy.

## Initialization and frames

- Requires a paired IMU sample, a GPS fix with horizontal accuracy no older than
  250 ms, and a rotation-vector orientation with usable heading uncertainty
  no greater than 0.6 radians, also within 250 ms.
- Android's rotation vector supplies phone-to-magnetic-ENU orientation. Native
  WMM2025 declination corrects it to true ENU. A short angular-rate correction
  aligns the seed to the IMU time; orientation uncertainty is increased with
  the alignment interval. The published rotation sensor is used for the seed,
  not repeatedly fused as an independent gyroscope observation.
- WMM2025 is valid for decimal years `[2025,2030)` here. Invalid dates/heights,
  near-pole inputs and a horizontal field below 2,000 nT cannot seed heading.
  Missing sensor accuracy does not become known north. A heading sample is not
  proof of a rigid vehicle mount. The engine separately estimates vehicle axes
  from GNSS-aided motion and gates forward/lateral constraints on mount agreement;
  vertical and stationary constraints have their own input checks. Native SVO,
  CTS, NHC and ZUPT are experimental, not field-validated measurements.
- Hardware-reported heading uncertainty remains preferred. A missing fifth
  rotation-vector value, including Android's `-1` sentinel, now enters a separate
  checked-compass initialization path rather than permanently blocking fusion.
  It requires calibrated, fresh accelerometer/gyro/magnetometer observations,
  two seconds of little motion, agreement with the local WMM2025 field strength
  and direction, and agreement with gravity. A high calibration code alone is
  insufficient. Poor hardware-reported accuracy is not replaced by this fallback.
- The checked-compass path uses a **model prior of at least 30 degrees**, increased
  by observed field/rotation disagreement, subject to the same 0.6-radian gate.
  This is explicitly not a device-reported accuracy or a proven absolute-error
  bound: correlated magnetic disturbance can escape these checks. Its provenance
  appears in Diagnostics and `native_pose` records. See `docs/16-sensor-fallback.md`.
- GeographicLib 2.5 implements WGS84 local Cartesian conversion. No ellipsoid
  is hand-implemented. Optional altitude is ellipsoid height; it is not MSL.
  Without initial altitude and vertical uncertainty, altitude output remains
  unknown and initial vertical-position standard deviation is 100 m.
- GPS horizontal accuracy is interpreted as the reported 68% radius under an
  isotropic horizontal Gaussian assumption: sigma = radius / sqrt(-2 log .32),
  with a 2 m floor. This assumption is explicit, not a GNSS trust model.
- Initial velocity uses speed/course only when their uncertainties are present;
  otherwise zero is a broad initial prior (10 m/s standard deviation), not a
  measured stop. Initial horizontal position uncertainty includes the GPS/IMU
  age using a 30 m/s timing bound. No stationarity claim or ZUPT is manufactured.
- A measured near-zero speed with `speed + 2 × speedAccuracy <= 1 m/s` also permits
  a bounded horizontal zero-velocity observation without course; Android commonly
  omits course at a stop. Its standard deviation is at least 0.5 m/s and includes
  the measured speed and uncertainty. This is not an IMU-only standstill detector
  and does not impose zero vertical speed. A supplied velocity starts with at
  least 1 m/s initial standard deviation rather than the unknown-velocity prior.
- Horizontal velocity updates do not impose zero vertical speed. A conservative
  isotropic deviation combines speed and angular-course uncertainty, with a
  0.5 m/s floor. Course uncertainty of 45 degrees or more disables that update.

## Delayed fixes and recovery

The engine owns a preallocated 512-frame history and retains at most two seconds.
An in-order delayed GPS fix within that history rewinds to the latest eligible
filter checkpoint, propagates to the actual measurement timestamp, applies the
position gate/correction and any valid altitude/horizontal-velocity updates, then
repropagates subsequent IMU. An additional correction checkpoint preserves the
previous GPS update even when consecutive GPS timestamps fall inside one IMU
interval. Pending slightly-future fixes wait for their IMU timestamp; they do
not reset the filter. Older-than-history or out-of-order GPS is rejected.

GNSS position gating uses the kernel's existing NIS threshold. A gated fix cannot
mutate the accepted trajectory. Accepted/gated/rejected counts and delayed
repropagation counts are exposed. These counts do not represent a learned trust
score. Subordinate altitude/velocity gates are not separately displayed yet.

An IMU gap above 100 ms or an invalid integration sample clears the usable
estimate and waits for fresh initialization inputs; the gap is never clipped.
An uncalibrated vehicle estimate is withheld after 10 seconds without an accepted
fix or when its computed horizontal 95% radius exceeds 150 m. Only motion-calibrated
Car profiles with constraints enabled retain the 600-second / 400 m backstop. Angular rates above 6 rad/s
invalidate the vehicle solution rather than clipping the measurement. Sensor gaps,
invalid samples and rapid handling clear mount, vibration scale and heading calibration.

Android disables these Car constraints for Two-wheeler and other non-Car profiles
through `setu_engine_constraints`. In that profile, valid gyro pulses above 6 rad/s
are propagated rather than misclassified as a Car mount change; the general
finite/range and timing checks still apply. Mount inference, NHC, turn-speed,
vibration-speed and learned-speed updates are disabled, and the 10-second / 150 m
ceiling remains. A leaning scooter must not inherit a calibrated Car's assumptions
or outage budget. This is bounded experimental inertial propagation, not a validated
scooter odometer. Walking remains a separate step-based estimator.
These are emergency withholding limits, not a validated duration or accuracy guarantee. A session stop closes its
native handle; a later foreground/capture session initializes again.

The 95% radius comes from the largest eigenvalue of the physical horizontal
position covariance (including the invariant attitude-position projection),
scaled by the two-dimensional chi-square 95% quantile. It is **model-derived and
not empirically calibrated**. Raw Android GPS accuracy and this radius are kept
in separate fields and described separately in Diagnostics.

## C/JNI contract

Delayed-GNSS repropagation retains the per-frame NHC, ZUPT, CTS/SVO and learned
speed observations, including their original axes and uncertainty. It reapplies
them after propagation instead of silently dropping those updates. Observation
generation/calibration is not retroactively rerun; four observations per frame
bound storage. Update counters count live accepted updates, not replay operations.
Learned speed rejects future, repeated and older-than-500-ms timestamps. The
Android provider must separately authorize deployment and pass validity gates.

Calls for one engine must be serialized. Kotlin owns and synchronizes its native
handle; double close is harmless and calls after close fail. Construction needs
a directory containing the packaged, upstream `wmm2025.wmm` and `.wmm.cof` files.
JNI validates array lengths before native reads.

`setu_engine_gnss` accepts ten doubles in order: latitude, longitude, ellipsoid
height, horizontal accuracy radius, vertical accuracy, speed, course degrees,
speed accuracy, course accuracy degrees, mock flag. Optional values are NaN;
mandatory coordinates and horizontal accuracy must be finite and in range.
Timestamps enter as signed 64-bit monotonic nanoseconds. Return -1 is invalid,
0 is queued/rejected/gated, and 1 indicates accepted processing; consult counters
and health rather than interpreting every 0 as a gate.

`setu_engine_poll` returns 31 doubles. The first 20 are: status, timestamp seconds, latitude,
longitude, optional altitude, horizontal speed, optional course, 95% radius,
accepted-GPS age seconds, mock flag, accepted count, gated count, rejected count,
delayed corrections, resets, last position NIS, east velocity, north velocity,
east displacement, north displacement. Status codes are 0 waiting for GPS/IMU,
1 waiting for heading, 2 GPS-aided, 3 inertial, 4 sensor gap, 5 withheld, 6 phone moved. Unavailable
position fields are NaN. Timestamp seconds are for published UI/log output;
input ordering and rewind operations retain integer nanoseconds internally.

Indices 20–30 are ZUPT count, NHC count, turn-speed count, mount agreement,
spectral-update count, spectral scale, mount-forward X/Y/Z, learned-speed update
count and mount-valid flag. Recompile C callers against `SETU_ESTIMATE_SIZE`;
allocating the old 20/30-double buffer is unsafe. JNI allocates from the header.

Android Walking mode bypasses this vehicle filter. It uses platform step events,
a calibrated step length, checked compass initialization and relative rotation;
see `docs/23-walking-fallback-investigation.md`. It does not apply vehicle constraints
or learned car speeds to a person walking.

Raw GPS `pose` records remain unchanged as observations. `rotation_vector` and
separately named `native_pose` records are added during capture; native output
includes `experimental: true`, provenance and radius. It must not be relabelled
as GPS ground truth. New recordings declare `trajectoryStream: track_pose` and
retain the selected GPS/native path separately, including source and filter
radius. Save/import/export/recovery and replay preserve this path. Legacy logs
without that header still replay their GPS stream; they are not silently upgraded
to fused evidence. Replay and distance do not bridge gaps above three seconds or
source changes. Replay is recorded output, not a retrospective estimator rerun.
Once an accepted mock fix contributes to a session, native output stays marked
mock until a full reinitialization; a later non-mock fix cannot erase its influence.

The strapdown mean now rotates interval-averaged acceleration with the interval's
midpoint attitude, not its initial attitude. The previous combination turned
gravity into spurious horizontal acceleration during handset rotation. Python
and C++ share the correction, with an in-place rotation regression and regenerated
294-action cross-language parity fixture. This numerical fix does not remove
sensor bias, magnetic interference or motion-model mismatch.

## Verification and remaining work

`NativeEngineTest` exercises on-time versus delayed corrections, geographic
displacement, missing inputs, pending fixes, gaps, NIS rejection, outage withholding,
horizontal-only velocity and handle lifetime. WMM declination is checked against
20 applicable low-altitude cases from NOAA's published WMM2025 test values.
`ImuSynchronizerTest` covers pairing, bounded missing streams, heading rotation
sign and source fallback. Runtime results and actual screenshots belong in the
Android evidence index; these tests alone do not establish full integration.

Remaining: learned measurements (owned by the teammate), mount calibration,
signal frontends, road-constrained hypotheses, general asynchronous measurement
fusion, clock-offset estimation, long-distance local-frame management, full
confidence calibration, recorder-format parity and physical-drive validation.
The current worker also performs logging; it is not a certified allocation-free
real-time sensor thread. Do not call this the complete architecture or a validated
navigation safety system.
