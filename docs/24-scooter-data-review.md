# Scooter recordings: findings and implementation

## Scope and data provenance

Only the latest three rides longer than one kilometre are used for this review.
The fourth, approximately 28 m, is excluded. The original recordings are not
relabelled, trimmed, corrected or overwritten. Coordinate-bearing logs and
exports stay outside the repository in private local storage.

| Recording ID | Recorded distance | Duration | User's placement description |
| --- | ---: | ---: | --- |
| `673f47d7-f578-446d-84c7-d87b9c33470d` | 9.007 km | 31.17 min | Orientation changed during the last approximately 2–3 km; exact time unknown |
| `605053b4-542f-4cbc-9c83-6b646fdaca07` | 2.387 km | 10.60 min | Phone in the scooter storage compartment |
| `3c2fc68f-15c8-4e69-8839-1252724c1a22` | 3.423 km | 17.85 min | Phone remained in one position |

All three headers say **Two-wheeler, mount unconfirmed**. Remaining in one position
does not establish secure attachment; a storage compartment is not automatically
a rigid mount. The scooter model was not supplied. These descriptions are
annotations, not retroactive changes to the recorded provenance.

The CPH2467 / OnePlus Nord CE3 Lite supplied continuous approximately 199.8 Hz IMU,
about 5 ms maximum sample gaps, clean end markers and zero recorder drops in these
rides. GPS stayed enabled. These are GPS-on data collections, not physical
GPS-off scooter trials. A working gyro is not itself an absolute heading or speed
sensor, and Android GPS is a noisy reference rather than survey ground truth.

## Reproduced defects and changes

1. **Scooters inherited Car constraints.** The activity switch previously compared
   only walking step length; switching Car to Two-wheeler did not recreate the
   estimator. The selected activity now selects and resets the native profile.
   Non-Car profiles do not apply Car mount estimation, non-holonomic, coordinated
   turn, vibration-speed or learned-speed constraints. Their outage ceiling stays
   at 10 seconds / 150 m modelled radius, even if Car calibration existed earlier.
2. **Short scooter vibration pulses repeatedly erased alignment.** The raw logs
   contain gyro pulses over the Car handling threshold of 6 rad/s, including the
   ride described as unchanged placement. The Car-specific reset is no longer
   applied to scooters. Raw values are not clipped; general finite/range and gap
   checks remain. Relative-attitude consistency now uses accumulated gyro angle,
   not only the last instantaneous rate after a pulse. Unexplained rotation jumps
   still reset alignment. This does not prove all pulses are harmless or identify
   the exact phone-handling interval in the 9 km ride.
3. **The bundled Car-only model was pointlessly started for scooters.** It correctly
   refused predictions, but still allocated a session/windows and logged unavailable
   results. Activity support is now checked before starting the local session;
   collection metadata reports it inactive. GPS and IMU recording continue.
4. **Native availability was confused with GPS readiness.** Good fresh GPS is
   preferred over the unvalidated non-Car native estimate for navigation. The Drive
   badge says GPS tracking when GPS is working but inertial alignment is not ready.
   Home-screen copy no longer promises validated tunnel navigation; the outage
   preview is explicitly labelled as a simulation rather than an accuracy test.
5. **Replay comparisons disappeared because clocks were phase-offset.** Available
   predictions were about 0.66 s from the epoch's latest GPS fix, beyond the old
   250 ms comparison cutoff. Evaluation now uses quality-checked bracketing fixes
   at the actual estimate timestamp, without extrapolation or feedback into the
   withheld estimator. Raw observations and training labels are unchanged.
6. **The trainer had no explicit scooter target.** Conversion now supports
   `--vehicle Two-wheeler` for a separate research candidate without relabelling
   recordings or bypassing mount, quality and independent-split checks. The app
   warns before recording that an unconfirmed mount is excluded from training.

GPS-motion heading alignment still needs three consistent, sufficiently excited
velocity-change checks. GPS course uncertainty up to 20 degrees is admitted to
the weighted calculation, not accepted as an exact heading; propagated variance,
direction diversity, agreement and final uncertainty gates still apply. Compass
checks are not weakened to hide interference from a scooter or storage compartment.

## What the measurements do and do not establish

The original live logs mostly report calibration rather than a native position:
the 2.387 km ride has no native poses; the other two have only short usable periods.
No numeric scooter speed was produced by the bundled Car-only learned model.
The dominant failure is heading initialization/retention, not absent IMU data.

Independent replay resets every 60 seconds, aids with GPS for 30 seconds and
withholds for 30 seconds. This deliberately measures cold initialization as well
as outage availability; it is not a replay seeded with privileged heading.
Correcting inappropriate resets does **not** establish reliable availability.
See the [verification ledger](verification/android/scooter-review/README.md) for
before/after counts, measured separation and exact test/build results.

These three same-phone/day, unconfirmed-mount sessions cannot form independent
training, validation, uncertainty-calibration and test sets. **No model is trained
or promoted from them.** The data are useful for diagnosis and regression replay;
they must not be silently presented as high-quality supervised training data.
There is no supported claim of 90–95% accuracy, a completed GPS-free commute, or a
production-ready scooter fallback. Ten seconds is a maximum permitted horizon,
not a promise that the estimator initializes or remains accurate for ten seconds.

## Next collection and use

1. Select Two-wheeler. Secure the phone in one non-magnetic mount before departure.
   Confirm the mount only when it is actually fixed. Do not hold or operate it
   while riding; stop safely or ask a passenger to operate the app.
2. Keep GPS on throughout collection. Start recording before initialization; wait
   stationary away from magnetic interference so the saved log includes alignment.
   Missing heading does not prevent raw training collection, but does prevent a
   valid initialized sensor-only demonstration. Do not manoeuvre just to satisfy
   a calibration indicator in traffic.
3. Record ordinary starts, stops, varied speeds, surfaces and turns. If the phone
   needs repositioning, stop safely, end the recording, reposition and start a
   new one. Record the vehicle, placement and any handling in accompanying notes.
4. Save at home, then use **Trips → drive → Export training bundle**. Keep SETU
   open during export. Keep originals and exports private; exporting does not
   train the model or automatically upload anything.
5. Collect independent sessions over multiple days, devices/mounts and routes.
   Assign correlated groups before inspecting test results. Run the explicit
   scooter converter and fine-tuning preflight described in the
   [pipeline guide](22-phone-training-pipeline.md). Review withheld availability,
   trajectory errors and uncertainty, not just average GPS speed error.

Until controlled, reference-backed trials pass, use GPS navigation. Do not rely
on experimental fallback for road safety or test GPS loss while operating a scooter.
