# Walking and stationary-speed investigation

## Observed, not assumed

Three private recordings were inspected from the connected OnePlus CPH2467
(Nord CE3 Lite). The owner confirmed all three were indoor walking tests, and
the high speed was on Diagnostics. All three files were labelled **Car**, with
an **unconfirmed** mount. Originals were preserved; private copies remain under
`%LOCALAPPDATA%/SETU/fallback-investigation`, not in this repository.

The longest recording contains 18,878 accelerometer and gyro samples each at
about 199.81 Hz, with a largest inter-sample gap of 5.006 ms and no reversed
timestamps. The phone reports an ICM4X6XA accelerometer/gyro, AK0991X magnetometer
and an Oplus platform step detector. This is actual device inventory, not a
claim about every Nord variant or sensor accuracy.

- Recorded GPS speed was zero. Indoors, zero Doppler speed does not establish
  accurate sub-metre position or prove that the user was stationary.
- The old native vehicle solution reached **3.5745 m/s** and continued through
  roughly 42 seconds of GPS loss without vehicle calibration.
- The bundled model produced **11–13 m/s**, maximum **12.9071 m/s**, with **zero
  validity**. These predictions were logged but not fused into navigation.
  Diagnostics nevertheless prominently displayed them as a speed.
- A **30 m/s** reading was not present in these three files. This investigation
  does not dismiss that report or invent evidence for it.
- The largest gyro magnitude was 14.57368 rad/s near the end of the longest run.
  A gyro measures angular **rate**, not total angle. A rapid turn can legitimately
  have a large rate. Adjacent gyro/game-rotation increments were broadly consistent;
  the game rotation is gyro-derived, so this is not independent accuracy validation.

## Changes

**Diagnostics:** zero-validity results remain in raw recordings for research but
are no longer returned as usable speeds to either model display. Vehicle and
walking sensor estimates have distinct labels. Actual vehicle constraint counters
replace the incorrect blanket “Not connected” readout.

**Walking:** choose Settings → Activity → Walking. This disables both local and
remote car-model inference. Android's step detector, gated by Physical activity
permission, drives displacement. Raw accel/gyro, game/absolute rotation, available
GPS and step events continue to be recorded together. No detected steps means no
additional step displacement; no double integration of gravity or car vibration
regression is used to infer walking speed. Speed comes from calibrated step length
and recent step batches; it is unknown until a usable cadence is available and
settles to zero after 1.5–4.5 seconds without an event, depending on batch spacing.
This phone's roughly two-second batches imply about three seconds of stop delay.
False positive or missed platform steps remain possible.

The walking estimator needs a GPS start with reported accuracy ≤20 m and checked
compass alignment. Thereafter relative game rotation carries heading through turns.
The phone must point along travel: flat-ish phones use their top edge; upright
phones use the direction away from the screen at initialization. Relative yaw
continues through ordinary pitch changes, including an upright phone. Rotating
the phone relative to your body or walking sideways/backwards still violates the
travel-direction assumption. Unmatched orientation jumps
or IMU gaps invalidate the solution and require a new GPS anchor. Sensor timestamps,
not delivery time, determine a delayed step's heading. Duplicate, pre-anchor,
excessively late and unaligned steps are rejected. Distinct events in a sensor
burst are counted individually; more than 16 events in four seconds invalidates
the estimate rather than clamping an implausible speed. Burst timestamps cannot
recover the individual footfall times, especially during a turn.

Position is withheld beyond **120 s since GPS**, a **75 m model radius**, or stale
orientation. The radius is a conservative heuristic using GPS accuracy, distance,
heading uncertainty and elapsed time, **not an empirically calibrated 95% bound**.
These ceilings are safeguards, not promised GPS-free duration. Fresh GPS takes
precedence for walking navigation. This feature does not add pedestrian routing.

**Vehicle:** an uncalibrated filter can no longer borrow the calibrated vehicle's
600-second budget. It stops after 10 seconds or a 150 m covariance radius. Motion-
calibrated vehicles retain their previous 600-second / 400 m backstop, which is
not a claim of useful accuracy over that interval. Rapid handset rotation above
6 rad/s invalidates vehicle calibration instead of masquerading as vehicle motion.
Sensor gaps and rapid handling clear mount and vibration calibration. Walking
does not use that vehicle angular-rate threshold. Raw gyro values are never clipped.

## Reproducible checks

- `WalkingTrackerTest`: stationary 30 s; step-derived speed and stopping; 100°
  turn without spurious translation; calibrated out-and-back; historical step
  heading; stale/duplicate events; sensor discontinuity; expiry and GPS priority.
- `NativeEngineTest`: zero-speed stationary fixture through the uncalibrated
  budget; rapid rotation clearing a previously calibrated vehicle mount; existing
  timing, delayed GPS, geographic and magnetic-field tests.
- `WalkingIntegrationTest`: synthetic Android sensor callbacks, withheld output
  without step permission, optional read-only replay of the owner's recordings,
  and opt-in phone capture with step registration and car inference disabled.
- `tools/analyze_recording.py`: coordinate-free diagnostic summaries. The command
  accepts one or more `.setulog` paths and `--output <private-summary.json>`.

Synthetic checks and table-top capture are not measured walking accuracy. The old
logs have no step-detector stream; inventing steps to claim an improved path would
be invalid. New walking trials are required.

## Follow-up: actual walking capture and batched steps

Physical activity permission was subsequently granted through Android's normal UI.
The next saved Walking trial lasts 171.4 seconds and contains 84 platform step
events. Location was off for about 71 seconds. The owner describes a corridor
about 10 m end to end; total traversals and counted physical steps are unknown.
The configured 0.70 m step length is therefore still a default, not a calibration.

The OnePlus reports two to four distinct step events within roughly a millisecond,
typically every two seconds. The first walking implementation discarded these
events with its per-step 250 ms gate: **17 positioned, 67 rejected**. Its 1.5-second
stop rule also made every recorded numeric walking speed zero. Later in the trial,
a fixed forward-axis projection became vertical and erased heading/GPS alignment.

The updated tracker counts distinct burst events, derives cadence from batch
spacing, and carries world-vertical relative yaw through normal phone pitch.
The Drive status also no longer says Calibrating merely because an initialized
Walking estimate intentionally gives fresh GPS priority. Sensor discontinuities,
implausible event floods and uncertainty/age limits still withhold output.

On-device **initialized tracker replay** now positions **84/84 recorded events**,
rejects none, peaks at **1.3988 m/s**, and finishes at **0 m/s**. It publishes a
position in **618 of 710** GPS-off output intervals; withheld intervals are not
counted as success. This is not an accuracy percentage or a count of verified
physical steps. The replay seeds the recording's first native bearing with a
0.6 rad uncertainty because compass initialization occurred before recording.
A cold full-estimator replay did not initialize from this file alone; the
initialized replay does **not** validate compass calibration or reference-free
position accuracy. It does not modify the original recording or production
initialization requirements.

The now-permitted 30-second physical capture confirms active step registration,
continuous raw IMU and no car-model inference in Walking. An initial still-phone
capture could not initialize because of magnetic interference; absence of a pose
is not a zero-speed measurement. After the owner moved the phone away from
interference, a second capture initialized normally and recorded 278 native poses,
all at 0 m/s, with no detected steps. The Drive badge correctly showed Tracking.
An additional live test disabled Location after normal initialization and passed
60 consecutive checks over 12 seconds: fresh walking poses, 0 m/s, no position
drift or new GPS aids. Location was restored afterward. This validates stationary
GPS-off operation, not measured moving-path accuracy.
See [follow-up build evidence](verification/android/walking-batches/README.md).

## Measurable next trial

1. Select Walking, allow Physical activity, and enable sensor fallback. Keep GPS
   on until Diagnostics shows a walking estimate. If heading does not align, move
   away from metal/outdoors rather than forcing an unchecked compass indoors.
2. Measure 10 m, count actual steps, and save **step length = 10 / step count** in
   Settings (supported range 0.3–1.2 m). Do this before the test recording.
3. Record a separate held-out 10 m walk, 100° turn, out-and-back and a 10 s stationary
   period. Keep phone orientation relative to your body unchanged. Record observed
   step counts, marked endpoints and elapsed times. Do not operate it while driving.
4. Collect with GPS on for training references; export the training bundle for
   separate withheld-GPS replay. A later short live GPS-off trial verifies operation,
   not absolute accuracy. Keep SETU open/recording when switching Location off.
   Start recording before the GPS/compass initialization interval so replay has
   its inputs; a recording started after alignment cannot reconstruct earlier
   unrecorded sensor state.
5. Evaluate endpoint and per-segment error in metres, distance error percentage,
   heading error in degrees, missed/false steps, stationary drift and time with
   valid output. Count withheld intervals as unavailable, not successful predictions.

“90–95% accuracy” is not a defined navigation metric. A suitable short-walk target
could be “95% of independent trials finish within 1 m over 10 m, with no stationary
drift above 0.5 m,” including an availability target. Neither this phone nor this
build has demonstrated that target. Indoor GPS and a 30° compass prior cannot
verify it; surveyed markers/video or a better independent reference are needed.
No model was retrained on these three mislabelled indoor runs.
