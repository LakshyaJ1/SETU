# Portable non-ML estimation

This is the C++20 / Eigen 3.4 port of `setu/estimation/riekf.py`, exposed through
`include/setu_filter.h` and packaged into the Android JNI library. The timestamped
`include/setu_engine.h` layer now adds GNSS/IMU streaming, bounded delayed-fix
repropagation, WGS84 coordinates and health output. It remains **a partial
implementation of the complete architecture**, not validated blackout navigation.
See `STREAMING.md` for the implementation contract and its current boundaries.

There are no AI/ML weights, fabricated model outputs, or vehicle-forward mount
assumptions in this library. WMM2025 is a published geophysical coefficient set,
not an AI model. GPS remains the default map source. Diagnostics offers explicit
experimental native-positioning opt-in, with GPS fallback when no current native
estimate is available.

## Contract

- Right-invariant error on SE_2(3); tangent ordering: attitude, velocity, position,
  gyro bias, accelerometer bias, SVO scale (3 + 3 + 3 + 3 + 3 + 1).
- SI units; local east/north/up navigation frame, gravity `(0, 0, -9.80665)`.
  Rotation is a row-major, proper orthonormal **body-to-navigation** matrix.
  A phone body frame is not automatically a calibrated vehicle frame.
- Accelerometer input includes gravity, as Android `TYPE_ACCELEROMETER` does.
  Gyroscope input is radians/second. Samples are at the end of an interval;
  consecutive inputs are trapezoid-averaged like the Python reference.
- A propagation interval must be finite, positive and at most 250 ms. Gaps need
  explicit session handling, not silently clipped time. Noise scale is in `(0,100]`;
  acceleration and angular-rate norms are bounded at 200 m/s² and 100 rad/s.
- Reset deviations are attitude, velocity, position, gyro bias, accelerometer
  bias and SVO scale. Noise defaults and the per-dimension NIS gate match the
  Python `FilterConfig`; the other configuration fields are not exposed yet.
- Position, velocity, forward speed, NHC, ZUPT, SVO frequency, horizontal position
  altitude and horizontal-velocity updates are implemented. **NHC/forward-speed/SVO require a known
  vehicle-forward frame**; zero velocity requires an independent stationary
  decision. A callable update is not evidence that its physical source exists.
- `setu_filter_update` returns `1` accepted, `0` gated, `-1` invalid. Other integer
  functions return `1` success, `-1` invalid. Invalid and gated updates do not
  mutate filter state. All measurement deviations must be finite and positive.
  NHC/ZUPT take dimension-sized zero vectors; their target is always zero.
- Snapshot is 279 doubles: row-major rotation (9), velocity (3), position (3),
  gyro bias (3), accelerometer bias (3), scale (1), elapsed seconds (1), row-major
  16×16 covariance (256). This is a kernel interface, not geographic `SetuPose`.
- Each instance requires serialized calls. Kotlin owns the handle and synchronizes
  access/close; the C API leaves ownership and threading to its caller. There is
  no JNI callback from the kernel and no model or network dependency.

## Build and parity

Android builds this target through `app/src/main/cpp/CMakeLists.txt` for arm64-v8a
and x86_64. NDK r28c and CMake 3.22.1 are pinned. The native shared library is linked
for 16 KiB page alignment; device/page-size compatibility still needs its matrix.

Eigen is downloaded from the upstream 3.4.0 archive with a pinned SHA-256, uses
fixed-size matrices and `EIGEN_MPL2_ONLY`, and is not modified. Its MPL2 license is
included in Android assets at `licenses/Eigen-MPL2.txt`. First configure needs
network access; subsequent builds reuse the verified source cache.

From the repository root:

```powershell
python -m tools.build_native_fixture --check
.\android\gradlew.bat -p android :app:connectedDebugAndroidTest
```

Regenerate deliberately with `python -m tools.build_native_fixture` when the
reference changes, then rerun device parity tests. The checked-in fixture records
reference source hashes, all 279 state values at checkpoints, every measurement
family, accepted/gated outcomes and NIS. Native invalid-input/closed-handle tests
are independent of that fixture. A synthetic integration check is also available
in Android Diagnostics and is explicitly labelled as synthetic.

## Still required

The streaming layer does not complete the FIR/time-offset estimator, vehicle
mount calibration, NHC/ZUPT decision logic, SVO/CTS/CSA frontends, particle road
matching, arbitrary delayed/multi-source measurements, model-output consumption,
format reconciliation, calibrated uncertainty, real-time scheduling or physical
validation. Its two-second rewind is deterministic GNSS repropagation, not the
architecture's general stochastic-cloning implementation. These remain real
requirements; an opt-in implementation is not their replacement.
