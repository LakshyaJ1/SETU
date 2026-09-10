# Compiled routing preview verification

## Build identity

- APK: `dist/android/SETU-routing-preview.apk`, 202,214,737 bytes.
- SHA-256: `080c738b059da3da653f1d05c86e39fe31e5a9357349ae190ac3121b7e835cd3`.
- Branch: `demo-mvp/position-tracking`; base commit: `ab84894a4ee5cf31716673bc4b70d26ee53e8ffe`, plus uncommitted changes.
- Debug signature and 16 KiB ZIP alignment pass; the installed emulator and phone APK hashes match.
- The stable MVP and earlier model-integration APKs are not replaced.

## Changes covered

The full NCR graph uses checksummed, atomically extracted, read-only mapped arrays
instead of reparsing its 253 MB JSON document for every app process. The drawing
tiles and geographic coverage are unchanged. The graph retains 3,185,592 nodes and
7,255,057 directed edges; its format and reproducible compiler commands are in
`../../../19-compiled-road-graphs.md`.

Routing tries the closest segments first, then bounded nearby connected-road
alternatives if needed. This fixes the included Bengaluru destination that snapped
to an isolated spur. Access gaps remain separate from driving geometry. One-way
directions remain enforced; this does not implement turn restrictions or full
vehicle-access rules. The Bengaluru regression test now explicitly selects its
bundled fixture regardless of the user's active map preference.

The APK also contains the earlier opt-in model-evaluation integration. It does
not enable validity-zero research predictions as navigation measurements.

## Automated results

- 47 JVM tests pass, including mapped-buffer corruption/cancellation and route alternatives.
- 50 Android tests pass on the API 35 emulator; one captured-physical-sensor replay test is skipped because its private recording fixture is absent. The runner's 51-test total includes that skip.
- Android coverage includes all included Bengaluru destinations, full NCR routes, Python/Android graph parity, corrupt-cache recovery, map import, six real tile-rendering zoom/theme/disposal cycles, model protocol/consent, native estimation, GNSS handling and trip storage.
- 34 focused Python map/compiler tests pass; two optional tests are skipped. Ruff check/format pass for the four changed Python files.
- Android lint: zero errors, 16 warnings. The whole Python suite was not rerun; the earlier unrelated HTML-report baseline failure is not claimed fixed.

The initially tested incremental APK contained 56,224,480 bytes of obsolete ZIP
space. Recreating only the package removed that overhead. All 219 archive entries
were byte-identical, and both Android suites ran again on the final compact APK.

## Full NCR measurements

From `compiled-graph-metrics.json`, one emulator run, not a phone benchmark:

| Operation | Elapsed time |
| --- | --- |
| Empty private cache: extraction, checksum and structural validation | 10.905 s |
| Existing private cache: checksum, mapping and structural validation | 2.717 s |
| Shahdara-area to MAIT route after loading | 7.720 s |

The route is 25,796.29 metres. First preparation and route computation are still
visible work, not instant navigation. OS file caches were not flushed. The test
also re-extracts a deliberately corrupted cached graph and compares route points.
Its final 703,257 KiB PSS sample retains multiple mapped graph instances across
cache recovery; it excludes the map renderer and is not a peak or production
memory budget. Renderer-cycle measurements are recorded separately.

## Manual scope and limits

Final-build captures show local destination search, the blue planned route and
offline map rendering with emulator Wi-Fi and mobile data disabled. Replay is
explicitly synthetic. The emulator's location is outside the NCR map, and the
preview correctly refuses to start a real drive there. No GPS coordinate or
recorded trip was uploaded, and these checks create no live drive recording.

The CPH2467 phone reconnected during packaging. The final APK was installed as an
update without clearing data. Its full NCR map and blue synthetic replay route
rendered in the existing dark/large-text preferences, including after returning
from Settings. All 20 existing `.setulog` files retain their pre-update SHA-256
hashes; the replay was closed and no recording service was left running. Wi-Fi
remained off, mobile data on and location on: phone radio settings were not changed.
The radio-off checks are emulator evidence, not a claim of a phone blackout trial.

Captures `02` and `05` show the transient map-preparation state immediately after
a tab return; they are not finished-render evidence. Capture `06` shows the phone's
map and route after readiness. Capture `04` also shows a completed physical-device
render of the synthetic route. No physical instrumentation or real drive was run.

These checks do not establish GPS-off driving accuracy, real-road entrance
suitability, whole-India coverage or production readiness. Offline model artifacts,
calibrated fusion, spatial indexing, turn/access restrictions and field acceptance
remain open in `../../../18-production-delivery.md`.

`build-evidence.json` binds the artifact hashes and counts to the included logs,
metrics and unaltered screenshot sidecars. Device-clock values in captures are
metadata, not authoritative build dates.
