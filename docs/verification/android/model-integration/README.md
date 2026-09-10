# Model integration preview verification

## Artifact and scope

- APK: `dist/android/SETU-model-integration-preview.apk` (155,517,282 bytes).
- SHA-256: `48253e32b47456cee853d0a211ff9b78668675354a338c162f26c62a62750a87`.
- Source base: `ab84894a4ee5cf31716673bc4b70d26ee53e8ffe`, with uncommitted changes.
- Installed and checked on the API 35 emulator, not the disconnected physical phone.
- The previous `dist/android/SETU-demo-mvp.apk` remains unchanged.

This increment implements live model evaluation, not production learned navigation.
The complete release scope remains in `../../../18-production-delivery.md`.

## Implemented behavior

Explicit sharing consent starts live IMU requests only while recording. A four-second
bounded window preserves raw phone-body axes, gravity, SI units and monotonic time.
Only the newest waiting window is retained and only one inference is in flight.
Stale inputs/results, unsupported capabilities, malformed responses, network failure
and cancellation are handled without substituting zero speed or stopping recording.
Endpoint changes revoke consent; old stored flags do not silently authorize uploads.

Results and provider warnings are visible under Model integration and diagnostics.
`model_measurement` log records are separate from the trajectory and explicitly
carry `navigationApplied: false`. The server's current validity-zero outputs are
research data, not a measurement accepted by the position estimator.

## Final checks

| Check | Result |
| --- | --- |
| App/test APK assembly | Passed |
| JVM tests | 41 passed, zero failures |
| Android focused regression suite | 26 passed in 1.633 seconds |
| Lint | Zero errors, 16 warnings |
| APK signature and 16 KiB ZIP alignment | Passed |
| Real endpoint health from Android | Ready with experimental/validity-zero warning displayed |
| Live virtual-sensor inference | 170 research records; all validity zero and excluded from navigation |
| Foreground-service backgrounding | Recorded model results increased from 161 to 166 over five seconds |
| Sharing revocation while recording | Model record count remained 170 for the next five seconds |
| Offline behavior | Connection error shown; sharing off; app remains usable |

The 26 Android tests cover `ModelProviderTest`, `ModelConsentTest`,
`NativeEngineTest`, `NativeFilterTest`, `TripStoreTest`, and `PositioningDemoTest`.
They are not the full map/UI/device-farm test suite. Consent tests use isolated
preferences and storage; live manual checks create explicitly named emulator test
recordings, then stop recording and disable sharing. Wi-Fi and mobile data on the
emulator are restored to their initially disabled state. The physical phone and its
recordings are untouched by this increment.

The broader Python baseline has **191 passing, 1 failing and 2 skipped tests**.
The failure is the existing HTML report test rejecting an inline animation script
(`tests/test_eval_and_report.py::TestReport::test_renders_valid_standalone_html`).
No Python implementation or test was changed here. The separate previously observed
Bengaluru routing regression is also not fixed by this increment.

## Evidence

- `build-evidence.json`: APK identity, verification counts and scope.
- `android-tests.log`, `jvm-tests.xml`, `lint-results.xml`, `build.log`.
- `python-baseline.log`: full reference-suite outcome, including the failure.
- `live-evaluation.json`: final-APK background and revocation checks.
- `06-final-server-connected`, `07-final-consent`, `08-final-live-evaluation`, and
  `09-final-sharing-revoked`: screenshots plus installed-APK hash sidecars.
- `endpoint-health.json`: provider readiness with its calibration warning.
- `endpoint-synthetic-response.json`: response to an explicitly synthetic 801-sample
  window at 200 Hz, from 1,000,000,000 through 5,000,000,000 ns; acceleration
  `[0, 0, 9.80665]`, angular rate `[0, 0, 0]`, vehicle `Car`.
- `endpoint-short-window-response.json`: unavailable reason for the 512-sample
  synthetic window. No phone/user location was sent in either probe.

Raw emulator recordings stay in app storage and are not published here. Device-clock
capture metadata is not an authoritative build date. Virtual sensors and synthetic
payloads establish integration behavior only, never physical speed/position accuracy.

## Required model-team handoff

Provide the deployable local model/checkpoint, exact preprocessing and axis contract,
supported sampling rates and vehicles, expected input/output fixtures, model/version
identity, uncertainty calibration and validity rules. The public API exposes health
and inference, not a downloadable offline model. Until those artifacts and the
native fusion/evaluation work are complete, this is not an offline AI navigation
release and does not validate a GPS-free Kirti Mandir-to-MAIT journey.

## Endpoint inspection

Commands used: `webcmd web fetch` for the supplied root, followed by bounded `curl`
GETs for `openapi.json` and `v1/health` and two synthetic POSTs to `v1/measurements`.
The supplied root returns 404; the advertised v1 API paths work. No browser fallback
was needed. All remote requests target the user-supplied host; no saved trips or GPS
coordinates are uploaded. Source base: `https://setu-proj-sih.duckdns.org`.
