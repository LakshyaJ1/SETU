# Sensor fallback: operation and limits

## What works without connectivity

Delhi/NCR and Bengaluru map rendering, local search, local route previews, raw sensor
recording and saved-trip replay use local data. Internet is not required for these
operations. Turning off Android Location also disables the app's GPS observations;
that is different from turning off Wi-Fi/mobile data.

Accelerometers and gyroscopes do not give an absolute starting latitude/longitude.
For live dead reckoning, initialize with a fresh GPS fix and usable attitude first.
Opening a map or moving a phone after a cold start with Location disabled is not
enough. The app must not silently use an old position or draw a fabricated path.

## Rehearsal on the connected phone

1. Leave internet off, turn **Location on**, and obtain a fresh GPS fix outdoors.
2. Open **Drive → Track my position** and enable **Sensor fallback**. Start
   the recording before leaving the app to change Android settings; a foreground
   recording keeps sensor acquisition alive when the activity is not visible.
3. Keep the phone still briefly, away from magnetic mounts/metal. Wait for
   **Sensor fallback is initialized**. Diagnostics must show increasing paired IMU
   samples, accepted GPS aids and a heading-alignment source.
4. Disable Location briefly, without stopping the recording. If initialized and
   within the uncertainty budget, the source becomes **Inertial estimate**.
   Sensor input drives that prediction; it is not a planned-route animation.
5. Re-enable Location to accept new GPS corrections. **Stop & save journey** keeps
   raw GPS, raw sensors and the selected sensor-estimated path separately.

The present experimental engine still withholds position after **10 seconds
without an accepted GPS fix**, a **150 m model-derived 95% radius**, or an IMU
gap above **100 ms**. These are upper limits, not accuracy guarantees; uncertainty
can stop prediction earlier. This update does not promise indefinite GPS-off
navigation. No limit is raised just to keep a marker moving.

## Experimental GPS-motion alignment

The NCR build also observes Android's game rotation vector, paired acceleration
and gyro samples, and changes in GPS velocity. Several consistent acceleration,
braking and turning intervals can align relative attitude without trusting a
disturbed compass. Constant-speed motion, a stationary phone or GPS-off cold start
cannot establish this alignment. Its uncertainty is an engineering prior, not a
measured guarantee. The UI reports calibration progress before GPS is disabled.
See `17-delhi-ncr-demo.md` for the update and its separate verification record.

## Faults corrected

- A missing rotation-vector fifth value (`-1`) previously blocked native alignment
  even when accelerometer/gyro samples were being paired. The fallback now checks
  calibrated magnetic/gravity observations and stability instead of treating all
  such phones as incapable of a compass-derived initialization.
- Interval-averaged acceleration was rotated using the interval's starting
  attitude. Rotating a stationary handset therefore produced false horizontal
  acceleration. Python and C++ now use midpoint attitude for that mean propagation;
  the zero-translation rotation regression failed before the correction.
- A GPS speed near zero with a supplied speed uncertainty was ignored if course
  was absent. A bounded horizontal near-zero observation now uses that uncertainty
  without inventing a heading, an exact standstill or a zero vertical velocity.
- Live native output was logged but saved trajectories/replay kept only GPS.
  New logs explicitly declare a separate `track_pose` stream, retaining GPS/native
  source and filter radius through save, import, recovery, export and replay.
  Legacy logs continue to use their original GPS stream.
- Replay previously interpolated across missing observations and relabelled every
  position as recorded GPS. Source changes and gaps above three seconds now break
  the drawn path and playback position. Distance does not count these missing spans.
- The UI distinguishes Location being disabled from a fresh GPS search, and gives
  initialization/recovery instructions instead of implying that sensors supply an
  absolute cold-start position.

## Checked compass is not verified heading accuracy

`CompassAlignment` prefers a usable hardware-reported uncertainty. If it is absent,
all three motion/magnetic streams must be fresh (at most 100 ms old). Rotation and
magnetic calibration codes must be at least medium. The measured magnetic field
must agree with local WMM2025 strength within 25% and direction within 15 degrees.
Gravity residual must stay below 0.45 m/s², angular rate below 0.12 rad/s, and
orientation variation below five degrees for two seconds.

The stability check allows at most 100 ms of cross-sensor timestamp skew in either
direction: Android can deliver an older rotation event after a newer accelerometer
or magnetometer event. Events genuinely ahead of the monotonic device clock remain
rejected by `LiveEstimator`. The model prior also includes the bounded skew times
the observed angular rate; delayed callback order is not treated as a sensor outage.

The fallback's heading standard deviation starts at **30 degrees**, increased by
observed field/rotation disagreement, and must still pass the engine's 0.6-radian
gate. That is a conservative engineering **model prior**, not a replacement value
claimed to come from Android and not an empirically calibrated error bound.
Correlated or spatially uniform magnetic interference can pass these tests; the
app remains experimental. Poor *reported* hardware accuracy is not overridden by
the missing-metadata fallback.

The published rotation vector is used for initialization, not repeatedly fused
as an independent measurement of the same gyroscope. No vehicle-forward,
road-snapping or artificial stationarity constraint is imposed on a hand-held
phone. Phone handling, mounting, bias, magnetic conditions and GPS quality remain
important to any complex-path test. Neither this change nor a synthetic turn test
establishes walking/driving accuracy.

## Verification

The regression suite covers missing heading metadata, stale/unreliable/interfered
sensors, cold starts with no GPS, turning paths through a controlled GPS gap,
sensor-input ablations, GPS recovery, the native/Python parity fixture, near-zero
speed without course, and trajectory provenance/gap serialization. Controlled
sensor arrays are not Android mock-location injection or physical ground truth.
The installed build passes 21 JVM, 27 Python estimation and 23 focused phone tests;
its exact APK and results are recorded in `verification/android/sensor-fallback/`.
The current live-phone check obtains GPS with internet off but does not initialize
fusion because magnetometer calibration reports code 0. A calibrated older sensor
recording passes the replay check; that does not replace the still-required live
GPS-off rehearsal. Do not present the current result as validated complex-path
or GPS-denied field accuracy.

Android's definition of the rotation-vector fifth value is documented at
`https://developer.android.com/reference/android/hardware/SensorEvent`:
it is estimated heading accuracy in radians, with `-1` when unavailable. The
runtime checks and model prior above are SETU policy, not Android guarantees.
