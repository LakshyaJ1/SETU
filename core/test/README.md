# Native road-stress benchmark

This runs the shipping arm64 engine against **synthetic** phone motion with known
truth. It tests failure mechanisms, not the prevalence of potholes in India, the
Android sensor/heading pipeline, learned-model accuracy or physical road readiness.
The accepted product target is 90% of GPS-free positions within 10 m, counting
unavailable outputs as failures. Existing stricter release gates still apply.

## Why the old scores are retired

The earlier fixture used clockwise navigation heading with a positive ENU gyro Z;
those describe opposite turns. It measured endpoint displacement rather than
travelled distance, warmed up for only 30–40 seconds, and supplied a perfect
speed-locked axle vibration line. Noise-free GPS coordinates were labelled with
uncertainty but not actually perturbed. Its results are not release evidence.

The replacement derives angular velocity from successive proper rotation
matrices, differentiates the actual phone trajectory for specific force, measures
path length, adds noisy GPS observations and uses a 120-second warmup. GNSS and
absolute attitude aiding are both withheld during scored intervals. Warmup
attitude is an idealized orientation aid; it does not validate app initialization.
No learned speed, road matching, wheel odometry or future truth is fed to the engine.

## Scenarios

| Index | Scenario |
| --- | --- |
| 0 | Rest after GPS-aided motion |
| 1 | Smooth constant-speed cruise; no assumed vibration/rest distinction |
| 2 | Acceleration, deceleration, turns and actual stops |
| 3 | Broad-band roughness plus a 23 Hz harmonic independent of road speed |
| 4 | Turns plus smooth vertical pothole-like dips and attitude disturbance |
| 5 | Two-wheeler lean combined with roughness and pothole-like dips |
| 6 | Severe dips that clip sensors at recorded CPH2467 sensor ranges |
| 7 | Rough road and an explicit 200 ms IMU dropout |
| 8 | A continuous phone reorientation during the outage |

Ordinary/severe synthetic dips are 3.5/8 cm over 250/80 ms. These are stress
parameters, **not measured suspension motion or representative Indian-road
statistics**. Sensor ranges are 156.9064 m/s² and 34.90656 rad/s, from the connected
phone's recorded sensor descriptors; no location data is embedded in the fixture.
Bias, random walk, white noise and a random fixed initial mount vary with seed.
Yaw and lean transitions are rate-limited rather than instantaneous jumps.

## Build and run

Use the Android NDK and CMake with `SETU_BUILD_TESTS=ON`, `ANDROID_ABI=arm64-v8a`,
`ANDROID_PLATFORM=android-26`, `ANDROID_STL=c++_static` and a Release build. This
links the same `setu_core` sources and numeric flags as the APK. Example PowerShell:

```powershell
$sdk = "$env:LOCALAPPDATA/Android/Sdk"
$cmake = "$sdk/cmake/3.22.1/bin"
$build = "$env:LOCALAPPDATA/SETU/road-stress-build"
& "$cmake/cmake.exe" -S core -B $build -G Ninja "-DCMAKE_MAKE_PROGRAM=$cmake/ninja.exe" "-DCMAKE_TOOLCHAIN_FILE=$sdk/ndk/28.2.13676358/build/cmake/android.toolchain.cmake" -DANDROID_ABI=arm64-v8a -DANDROID_PLATFORM=android-26 -DANDROID_STL=c++_static -DCMAKE_BUILD_TYPE=Release -DSETU_BUILD_TESTS=ON
& "$cmake/cmake.exe" --build $build --target setu_dr_bench --parallel 2
```

Push `setu_dr_bench` and the packaged `wmm2025.wmm`/`wmm2025.wmm.cof` to a dedicated
directory under `/data/local/tmp` on the authorized phone, make the binary
executable, and run its `--self-test` first. Do not interrupt an active recording.
Check battery/temperature; a full sweep is CPU-intensive and is not a driving task.

```
setu_dr_bench GEOPHYSICS_DIRECTORY REPEATS ALGORITHM DURATION PROFILE
```

- Repeats: 1–20; default five fixed seeds (`0xBEEF + repeat*7919`).
- Algorithm: `cv` last-GPS constant velocity, `imu` GPS-calibrated unconstrained
  native IMU, or `car` native Car constraints. The last is an out-of-domain negative
  control on leaning-scooter cases, not a valid scooter configuration.
- Duration: 10, 30, 60, 120 or 180 seconds; `0` runs all.
- Profile: table index; `-1` runs all.
- `SETU_TRACE=1` adds every scored 10 Hz sample as JSONL. Otherwise only protocol,
  per-run and per-condition summaries are written. Redirect output to an artifact.
- Legacy `SETU_NO_DR=1` selects `imu` only if no explicit algorithm is supplied.
  This is not a GNSS-only baseline: inertial propagation is still active.

## Scoring and limitations

The inclusive timeline contains `10 * duration + 1` output opportunities. Every
opportunity counts; stale/unavailable outputs are not dropped. Conditional error
percentiles are explicitly labelled and never used as the joint accuracy rate.
Missing endpoint error is null, not the last available error. Percentiles use
nearest rank; aggregate endpoint calculations treat missing endpoints as infinity.
Stationary distance is not divided into an invented drift percentage.

Exit `0` means the selected **benchmark** conditions meet joint 90%/10 m, retain
an endpoint, and meet the 10% drift check (5 m endpoint for rest). Exit `1` means
a benchmark condition failed; exit `2` means configuration/execution failed.
These checks do not implement every product gate: short-distance field gates,
independent-data confidence intervals, recovery, Android initialization, model
coverage, latency and battery remain separate. `releaseApproved` is always false.
Never widen engine safety horizons merely to make this test report availability.

Run all algorithms on identical profiles/seeds before comparing them. Do not
choose/tune on a held-out field test or present a smooth-road win as pothole
validation. Real GPS-withheld recording replay and independent mounted field
trials remain mandatory under `docs/25-navigation-release-goal.md`.
