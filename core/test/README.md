# GNSS-denied dead-reckoning benchmark

`dr_bench.cpp` runs the shipping engine against synthetic drives with known ground truth, cuts GNSS
partway through, and reports what REQ-P1/P2/P3 actually ask for.

It is built **for the phone, not the host**. The requirement numbers have to hold for the arm64
binary the app ships, and the host toolchain on this machine (MinGW GCC 6.3) cannot compile C++20
anyway.

## What it simulates

Every run gets a **random, unknown phone mount** — any yaw, up to 0.45 rad of pitch and roll. The
engine is told nothing about it and has to work the vehicle axes out for itself. On top of the
trajectory:

- MEMS white noise, a turn-on bias and a bias random walk on both accelerometer and gyroscope
- road and engine vibration whose amplitude grows with speed, with the axle line at `v / (2 pi R)`
- 1 Hz GNSS with realistic accuracy until the blackout, then nothing
- a phone attitude at 10 Hz with noise, standing in for the fused rotation vector

The vibration is not decoration. A smooth constant-velocity cruise with no vibration is, to an
accelerometer, *exactly* a vehicle standing still — that is Galilean invariance — so a simulator
without it cannot exercise the stop detector honestly.

## Build

```sh
SDK="$LOCALAPPDATA/Android/Sdk/cmake/3.22.1/bin"
"$SDK/cmake.exe" -S core -B build/dr-bench -G Ninja \
  -DCMAKE_MAKE_PROGRAM="$SDK/ninja.exe" \
  -DCMAKE_TOOLCHAIN_FILE=$NDK/build/cmake/android.toolchain.cmake \
  -DANDROID_ABI=arm64-v8a -DANDROID_PLATFORM=android-26 -DSETU_BUILD_TESTS=ON
"$SDK/cmake.exe" --build build/dr-bench --target setu_dr_bench
```

## Run

The engine loads the world magnetic model at construction, so push the geophysics assets too.

```sh
adb shell mkdir -p /data/local/tmp/setu-geophysics
adb push android/app/src/main/assets/geophysics/wmm2025.wmm     /data/local/tmp/setu-geophysics/
adb push android/app/src/main/assets/geophysics/wmm2025.wmm.cof /data/local/tmp/setu-geophysics/
adb push build/dr-bench/setu_dr_bench /data/local/tmp/
adb shell chmod 755 /data/local/tmp/setu_dr_bench

adb shell /data/local/tmp/setu_dr_bench /data/local/tmp/setu-geophysics 12
```

The second argument is the repeat count; results are reported as medians and p90 across repeats.

### Environment switches

| Variable | Effect |
|---|---|
| `SETU_NO_DR=1` | disables the dead-reckoning constraints, giving the GNSS-only baseline to compare against |
| `SETU_TRACE=1` | prints a 2 s trace of status, fix counts, estimated vs true latitude, speed and constraint counters |

`SETU_NO_DR` drives `setu_engine_constraints()`, a real API on the engine, so the comparison
exercises the same binary rather than a rebuild with different code.

## Reading the output

Per profile the benchmark prints the along-track and cross-track split of the final error. That
split is the diagnostic that matters: NHC and ZUPT bound **cross-track** drift, so if the total is
dominated by **along-track** the missing ingredient is a forward-speed observation, not more tuning
of the constraints. As of 2026-09-14 that is exactly what it shows — see `CHECKPOINT.md` §4b.
