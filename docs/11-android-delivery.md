# Android delivery and verification

## Scope

Build the complete Android product described in the application documents. The
AI/ML models are owned by another teammate; versioned integration contracts and
unavailable/error states are included here. The Python reference and portable
native integration remain part of the larger integrated application, not silently
replaced by a UI mockup.

## Completion ledger

Nothing in this table is marked complete by a plan or by a successful compilation.
Each row needs runtime evidence, and every visible completed capability needs an
actual emulator/device screenshot requested by the user.

| Requirement | Current verification |
|---|---|
| Native Android project and reproducible build | Debug APK builds and installs on API 35; local unit/device checks pass. Reproduction: `android/README.md`. |
| Map-first Material UI, light/dark, system insets | Actual map, 200% text and landscape captures in the evidence index. A neutral system-button strip fixes the observed dark three-button contrast issue. The wider device/accessibility matrix remains open. |
| Permissions, sensor capabilities and honest availability | No-permission UI and actual emulator sensor rates observed. GPS optional fields, uncertainty and mock provenance survive acquisition/storage; missing, measured-zero and stale states are checked in `verification/25-*`, `26-*`, `27-*`. These three captures use explicitly labelled injected test locations. Full denial/revocation and physical-device matrix pending. |
| Destination selection, route preview and guidance | Local search/preview and six destination routes tested. GPS outside the included area falls back to a labelled MG Road preview and cannot start guidance (`verification/28-outside-area-preview.png`, injected test location). All-road routing, turn restrictions, guidance lifecycle and field safety remain open. |
| Offline region lifecycle and map attribution | Included Bengaluru plus validated `.setumap` import, explicit selection, revision retention, removal and direct URL/SHA-256 download are exercised. Eight store tests and a UI workflow use a clearly synthetic verification grid (`verification/32-*` through `36-*`); the manual loopback download is in `manual/37-*` and `38-*`. Region switching updates search, road graph, preview origin and attribution. No additional real city or production HTTPS publisher is claimed. Hosted catalogue, broad glyph/format coverage, abandoned-staging recovery and full routing rules remain open. Contract: `docs/13-offline-map-packs.md`. |
| Foreground sensor/GNSS capture and stop notification | Actual emulator capture, background notification and Stop & save exercised; screenshots `manual/12-*` and `manual/13-*`. Physical long-drive checks pending. |
| Local trip persistence, details, export/import and deletion | On-device storage tests pass, including malformed input and interrupted-record recovery. Document-picker export and retained reimport match the original SHA-256. Reimport inspected after emulator restart: `manual/22-imported-trip.png`. Broader lifecycle hardening continues. |
| Timestamped replay, pause, scrub and provenance | Synthetic replay paused and seeked to 50% in device test (`verification/04-synthetic-replay.png`); saved GPS replay paused and inspected (`manual/23-recorded-replay.png`). This is not native-estimator replay or full lifecycle coverage. |
| Diagnostics and degraded/missing-hardware states | Actual emulator readings and unavailable AI channels shown; screenshot `verification/05-diagnostics.png`. Hardware fault matrix pending. |
| Versioned AI/ML provider boundary and error handling | Typed provider and v1 HTTP contract implemented. Model-free server checked in-app (`manual/16-model-unavailable.png`); inference-to-core connection remains pending. |
| Portable non-ML core / Android integration | The C++20/Eigen kernel now has a timestamped GNSS/IMU engine: GeographicLib WGS84, WMM2025 heading correction, bounded delayed-GPS repropagation and gap/uncertainty withholding. Actual emulator sensor callbacks reach it; explicit native-map opt-in and separate native_pose recording pass a UI/storage workflow (`verification/29-*`, `30-*`, `31-*`). Seven native-engine tests include 20 NOAA magnetic reference examples. The original 294-action Python fixture still covers its eight measurement families; a separate test covers added horizontal velocity. Mount constraints, signal frontends, road hypotheses, full architecture and physical validation remain open. |
| Automated unit and on-device workflow checks | Nine JVM checks, thirty-three device checks and three Python map-packaging checks pass. The device suite runs with Wi-Fi/data disabled; loopback download tests are explicitly local. Lint has zero errors and 16 warnings. The latest emulator run uses a 720 × 1600 / 280 dpi rendering override after earlier platform crashes; this is not a claim that those crashes are fixed. Logs and APK-linked metadata are in the evidence directory. This is not full product coverage. |
| Verified screenshots of each implemented flow | Twenty-four automated captures match the installed-APK SHA-256, alongside current manual map-download, document-provider import and 200% map-form text checks (`manual/37-*` through `41-*`), plus earlier capture/export/model/large-text/landscape evidence. A blank preview observed after scrolling is corrected with texture-backed map composition and checked in `verification/35-map-pack-removed.png`; this is not a whole-device performance claim. Index: `docs/verification/android/README.md`. Remaining flows need further captures. |

Evidence paths in this table are relative to `docs/verification/android/` unless
otherwise stated. These are bounded development checks; no row establishes that
the complete integrated application is finished. The initial live native path is
implemented and exercised, but full non-ML signal processing, mount calibration,
road-constrained estimation, model measurement consumption, broader offline
routing/catalogue/format support, recording-format reconciliation and physical-device validation
remain required work. The experimental engine's exact boundary is in
`core/STREAMING.md`; it is not a substitute for the complete architecture.

## Reference validation

The SVO frontend no longer receives acceleration derived from unmasked GNSS
velocities. It uses its IMU spectrum and physical transition bounds instead.
Two regression tests failed before this correction and pass afterwards, including
a check that changing unavailable GNSS velocities cannot change the tested
solution. All ten pipeline checks pass. The full Python suite has 170 passing
tests and one existing report/template mismatch: the HTML template includes an
inline animation script while its test forbids script tags. That unrelated report
code and assertion are unchanged. Evidence: `docs/verification/reference/README.md`.

Historical benchmark tables have not been regenerated. Neither these tests nor
the Android screenshots establish physical-device blackout accuracy.

## Visual contract

The selected native surface is a journey console: geographic map first, compact
status above, task-specific sheet below, familiar labelled navigation. The map
and route carry identity; Material controls carry operation. The signature moment
is following a timestamped journey without losing context. Synthetic replay is
labelled throughout. Impeccable surface seed: `7bec0a71`, grounded structure 3.

## Evidence rules

Save unaltered `adb exec-out screencap -p` or `adb shell screencap` captures and
record the build, device and interaction that produced each. Visually inspect
each screenshot. Also record relevant test output and runtime logs. A screenshot
cannot prove background rate, model inference, privacy or navigation accuracy.
