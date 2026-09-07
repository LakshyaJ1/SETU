# Reference-pipeline validation

Review date: September 7, 2026. These are Python reference checks, separate from
the Android APK/runtime captures in `../android/`. No AI/ML model was introduced.

## Corrected data leak

The SVO frontend previously received a longitudinal-acceleration prior derived
from every GNSS velocity, including unavailable epochs. Removing that input
leaves the existing IMU-only spectrum and physically bounded ridge transitions;
it does not replace the missing observations with synthetic GNSS measurements.

Two new regressions fail against the earlier pipeline and pass with the fix:

- The spectral frontend receives the original IMU stream with no GNSS-derived
  acceleration or speed hint.
- Altering only unavailable GNSS velocities leaves both the estimated position
  and velocity arrays exactly unchanged in the tested isolated configuration
  (CTS/CSA disabled, short warm-up). This is data-flow isolation, not an accuracy
  benchmark or a proof about every possible pipeline configuration.

## Results

- Focused regressions: two passed; `gnss-leak-before.log` records the earlier failures.
- Existing-plus-new pipeline class: ten passed.
- Full reference suite: 171 collected, 170 passed, one failed.
- Native Python/C++ fixture remains current: two cases, 294 actions. The kernel
  math files did not change with this pipeline correction.

The full-suite failure is
`TestReport.test_renders_valid_standalone_html`. The unchanged
`setu/report/page.py` includes `SWEEP_SCRIPT`; the unchanged assertion expects no
`<script` tag. Both are present in the baseline commit. This report/template
policy mismatch is recorded, not hidden by changing the test or unrelated HTML.

The historical simulator table in the root README has not been regenerated.
Passing a threshold test does not retroactively validate its exact old numbers,
and none of these runs establishes on-road or GNSS-denied Android performance.

## Reproduce

From the repository root, with the Python project dependencies and pytest installed:

```powershell
$env:OPENBLAS_NUM_THREADS = '1'
$env:OMP_NUM_THREADS = '1'
python -m pytest -q tests/test_eval_and_report.py::TestPipeline
python -m pytest -q
python -m tools.build_native_fixture --check
```
