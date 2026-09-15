# Phone QA, outage testing and beta distribution

Date: 2026-09-15. Device: OnePlus Nord CE3 Lite (CPH2467).

**Development beta, not approved GPS-free navigation.** The tested application
is `dist/android/SETU-qa-beta.apk`, SHA-256
`410ca8d79d42780b3cb1c33c0d569c093e1216b257d9c2ccd10dc56e9a8db62b`.
This follow-up fixes compact map controls and hidden loading feedback, keeps the
screen awake during foreground recording, and improves evaluation and beta
distribution. It does not install a new model or increase fallback limits.

## Reports

- [Complete test report, PDF](verification/android/rigorous-qa/report.pdf)
- [Searchable report and per-test inventory](verification/android/rigorous-qa/report.md)
- [Machine-readable measurements](verification/android/rigorous-qa/report.json)

The report retains the original failing combined run as well as subsequent
isolated results. Passed, failed and skipped tests are counted separately.
The latest complete phone inventory finishes with **77 passed, 7 skipped and
zero failures/errors** across 84 discovered methods. Python finishes with
265 passed and 2 skipped; Android JVM tests pass all 102; lint has zero errors
and 25 existing warnings. All 37 original recordings remain byte-identical.
Raw location-bearing recordings and replay traces remain under the machine's
private `%LOCALAPPDATA%\SETU` directory, not in the public website.

Coverage includes Drive/Record/Trips/Settings, theme and recreation, curved-demo
loss/recovery, sensor subscriptions, stale/invalid GNSS, provider re-enabling,
Delhi-NCR routing and zoom rendering, corrupt map caches and archives,
download cancellation/checksums, model consent and private inference, native
filter behavior, physical recording, collection/export and trip recovery.
These are bounded scenarios on one phone, not an assertion that every possible
device, sensor condition or user journey has been tested.

## What Location-off testing actually establishes

The phone's real Android Location switch was disabled for 90 seconds during a
foreground recording. Fresh paired accelerometer/gyroscope samples continued
at every requested checkpoint: 10, 20, 30, 40, 50 and 90 seconds. Location state
was checked through both the operating system and the application.

No native position was available at those checkpoints: this indoor, stationary
check did not establish an initialized, independently measured moving route.
Its result is **sensor continuity**, not position accuracy. The test restores
Location and recording settings and removes only its own generated fixture.

Position errors below come from a separate experiment: replaying the three
selected real scooter rides through the installed native estimator, withholding
GPS from it during each outage and retaining recorded GPS only for scoring.
The 28 m recording is excluded. There is no learned-speed input in this replay.

## Requested durations

Each case has 120 seconds of GPS warmup followed by exactly `duration × 10`
scoring ticks in the half-open interval `[0, duration)`. A prediction is compared
with the reference at the scoring time, not the older prediction timestamp.

| Outage | Verified within 10 m / all expected updates | Verified success | Available estimates |
| --- | ---: | ---: | ---: |
| 10 s | 285 / 2,600 | 10.96% | 377 |
| 20 s | 183 / 4,800 | 3.81% | 342 |
| 30 s | 408 / 6,900 | 5.91% | 457 |
| 40 s | 232 / 8,000 | 2.90% | 445 |
| 50 s | 130 / 10,000 | 1.30% | 190 |
| 90 s | 91 / 14,400 | 0.63% | 164 |

Missing estimates are failures. Missing comparison references are unknown, not
claimed successes: the percentages are conservative verified lower bounds.
Even availability alone is far below 90%, so the target cannot pass this replay.
Conditional error statistics exclude unavailable outputs and must not be read
as whole-outage accuracy. All three rides share a phone/day, have unconfirmed
mounts and use phone GNSS rather than independent surveyed ground truth.

Different durations have different outage start times and cycle counts. For a
fair duration comparison, the report also evaluates matched prefixes of the same
16 ninety-second outages. All their available predictions occur in the first
10 seconds; every later non-overlapping phase has zero available predictions.
The existing unconfirmed Two-wheeler 10-second fallback guard remains intact.

## Corrections and findings

1. **Replay boundary and timing:** removed the extra recovery-boundary scoring
   tick and compare lagging estimates with the current scoring reference.
   Protocol `setu.phone-outage.v2` prevents confusion with older inclusive runs.
2. **Curved-demo regression assertion:** distance travelled is the sum along the
   curve, not its start/end chord. The travelled-distance and under-5-m synthetic
   position-error requirements remain enforced.
3. **Fixture isolation:** the original 81-test shared-process run had 70 passes,
   seven skips and four failures: two missing Compose-root failures, a map PSS
   budget failure and the obsolete straight-chord assertion. Each method now
   runs in a fresh instrumentation process without clearing user data. Incomplete
   execution or incomplete report inventory is rejected, not labelled success.
4. **Actual app memory soak:** five demo/settings/theme/trips journeys in one
   process passed the unchanged 700 MiB ceiling. The focused run ranged from
   587,855 to 619,599 KiB PSS. This and isolated map checks distinguish fixture
   accumulation from ordinary app reuse, but do not prove every long session
   leak-free. The combined run's 1,854,612 KiB failure remains disclosed.
5. **Report script safety:** the HTML test allows only the existing trusted sweep
   script and still rejects executable script injection in route names.
6. **Beta publishing:** immutable hash-named APKs, verified metadata, copy-integrity
   checking and atomic latest-release updates retain the preceding download if
   validation fails. Missing or mismatched release metadata disables the website
   download rather than presenting an unverified file.
7. **Map usability:** compact zoom controls now sit horizontally above the
   attribution instead of being covered by it. The task sheet reserves map space
   using actual window constraints. Loading feedback is placed in the visible
   map area, not behind the sheet; controls appear when rendering is ready.
8. **Foreground screen wake:** recording keeps the activity's screen on while
   visible and releases that flag when recording stops or the activity leaves
   the foreground. No permanent system screen-timeout change is needed.

## Important background-recording finding

The original `aee9c570...` APK passed the six-checkpoint **foreground** test with
Location off. With Location, Wi-Fi and mobile data all off, a separate background
test stalled for 412,991 ms before manual foreground recovery. Turning Battery
saver off did not resolve it: the repeat stalled for 155,377 ms. The app already
had Android's battery exemption, OnePlus Allow background activity enabled, and
Don't optimise selected.

A normal, non-instrumented recording confirmed this was not just a test-harness
effect: during a 45.71-second background interval, accelerometer and gyroscope
streams had gaps of approximately 15.95 seconds. The saved log retained an end
record. A separate special-use foreground-service experiment also failed and
was reverted; that candidate APK is not the distributed build.

See [coordinate-free background evidence](verification/android/rigorous-qa/background-investigation.json).
The final build's screen-wake behavior is a foreground mitigation, **not a fix
or certification for background capture**. Keep SETU visible for this demo.
User-driven screen locking, switching apps, aggressive device power controls
and extended screen-off recording remain outside the verified guarantee.

## Repeatable checks

Run from the SETU repository. Keep the phone connected and idle; never interrupt
a user's recording. The isolated runner refuses to proceed while the recording
service is active. It runs physical continuity checks but skips experiments that
need a separately supplied moving/controlled-GNSS fixture.

```powershell
python -m tools.run_phone_tests "$env:LOCALAPPDATA\SETU\qa-new-run" `
  --adb "$env:LOCALAPPDATA\Android\Sdk\platform-tools\adb.exe" --serial f87ee0de
python -m pytest -q
.\android\gradlew.bat -p android :app:testDebugUnitTest :app:lintDebug `
  "-PsetuBuildDirectory=$env:LOCALAPPDATA\SETU\android-review-build"
```

Generate the report only after the full isolated inventory has completed:

```powershell
python -m tools.build_phone_qa_report "$env:LOCALAPPDATA\SETU\rigorous-qa\final-replay" `
  docs/verification/android/rigorous-qa `
  --suite "$env:LOCALAPPDATA\SETU\rigorous-qa\baseline-all-device-tests.log" `
  --suite "$env:LOCALAPPDATA\SETU\rigorous-qa\actual-location-off.log" `
  --suite "$env:LOCALAPPDATA\SETU\rigorous-qa\latest-six-duration-replay.log" `
  --suite "$env:LOCALAPPDATA\SETU\rigorous-qa\internet-location-off-recording.log" `
  --suite "$env:LOCALAPPDATA\SETU\rigorous-qa\internet-location-off-no-saver.log" `
  --suite "$env:LOCALAPPDATA\SETU\rigorous-qa\special-use-background.log" `
  --suite-directory "$env:LOCALAPPDATA\SETU\rigorous-qa\latest-isolated" `
  --hardware "$env:LOCALAPPDATA\SETU\rigorous-qa\latest-location-off-durations.json" `
  --checks docs/verification/android/rigorous-qa/checks.json
```

The replay itself is opt-in `ScooterCaptureReviewTest` instrumentation, not an
unattended modification of saved rides. Preserve private source logs and their
hashes when repeating it; do not publish route coordinates as website assets.

## Sibling beta website

`../setu-website` is a static, Android-styled download and testing site. It serves
the actual APK, SHA-256, PDF and coordinate-free results, with prominent limits
and private-data guidance. It has no accounts, trackers or recording uploads.

```powershell
python -m tools.publish_beta dist/android/SETU-qa-beta.apk `
  docs/verification/android/rigorous-qa/apk-verification.json `
  --site ../setu-website --report docs/verification/android/rigorous-qa/report.json `
  --watch 30
```

The watcher checks for changed verified artifacts every 30 seconds while running;
it is not a permanently installed service. In a separate terminal, run
`python -m http.server 4173 --bind 127.0.0.1 --directory ../setu-website`.
Open `http://127.0.0.1:4173`. This is a local site, not a public deployment.
Deploy its generated downloads/reports/metadata to a chosen static host when
ready. Refresh the page for the latest publication.

## Remaining release blockers

Heading initialization and sustained sensor-only estimates remain insufficient.
The phone's changed orientation and compartment storage are not fixed-mount
training examples. The earlier CPU speed model still predicts false motion at
rest and is not installed or permitted to steer the live estimator.

Collect rigid-mount scooter routes on different days, annotate orientation
changes and stops, and obtain an independent position reference before claiming
90% within 10 m. A passing synthetic demo or a finite indoor continuity test
cannot replace this evidence. Use trusted GPS navigation on real journeys.
