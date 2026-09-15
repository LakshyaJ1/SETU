# Android collection-pipeline verification

Verified on the USB-connected CPH2467, Android API 35, on 2026-09-14.

## Delivered build

- APK: `dist/android/SETU-training-pipeline.apk` (ignored build artifact).
- SHA-256: `fa8e7ce77a7e218ee1f8efa6c605098e1f8b8a071d73f098043890904a1adb94`.
- Size: 212,471,734 bytes. Debug signed; version `0.1.0`, code 1.
- The installed phone `base.apk` hash matches this artifact.
- APK v2 signature verification and 16 KiB ZIP alignment checks pass.
- The previous `SETU-reviewed-preview.apk` remains available separately.

## Checks

- Build, 76 JVM tests and Android lint pass. Lint reports 25 warnings, no errors;
  the added `UseKtx` suggestion concerns an explicit checked preference commit.
- All 11 Python collection/conversion/preflight tests pass; Ruff passes on the
  three new Python files. No TensorFlow training job was run on personal data.
- `delivery-device.log`: 22 passing tests, one fixture-dependent skip. The runner
  prints `OK (23 tests)`, which includes the skipped captured-sensor replay.
- `final-client.log`: four further passing checks with the final test source.
  These exercise the actual ViewModel export operation, recording lifecycle,
  GPS-withheld replay independence, replay across boot-relative clock changes,
  missing-heading behavior, mount checkbox and export-consent UI. The ViewModel
  test writes to an app-private file URI; document-provider interruption/resumption
  and arbitrary cloud-provider behavior are not qualified by this test.
- The controlled trajectory test changes only post-cutoff GPS coordinates;
  the shadow trajectory stays byte-for-byte identical, GPS acceptance does not
  increase during withholding, and sensor-driven positions continue to change.
  This is a synthetic algorithm check, not measured on-road accuracy.

## Physical capture and conversion

The final 16-second capture contains **8,964 records, zero reported drops**, four
quality-paired one-second epochs and a complete end marker. It used the actual
phone sensors and Android location callbacks, not a mock location provider.
The application exported raw data, aligned epochs and a manifest through its
ViewModel. Raw bytes in the ZIP match the saved original.

The Python converter verified this exact ZIP and produced **three 400×6 windows**.
Five candidate windows lacked bracketing GPS and five failed GPS quality checks;
they were rejected rather than manufactured. An earlier indoor capture had zero
usable GPS labels and correctly produced zero windows. The brief stationary
hardware test is not a driving dataset or enough data to fine-tune a model.

All **22 pre-existing raw recordings** retain their original hashes. Test-owned
trips were removed. Test settings are restored in `finally`; no global mock
provider, automatic upload or model promotion was enabled. The raw verification
ZIP remains private on the phone and in `%LOCALAPPDATA%/SETU`, outside this repo.
Only aggregate metrics, test logs and a non-location UI capture are included here.

## Reproduce

Set `JAVA_HOME` to the Android Studio JBR and `ANDROID_HOME` to the installed SDK.
Use a build directory outside the OneDrive source tree:

```powershell
.\android\gradlew.bat -p android "-PsetuBuildDirectory=$env:LOCALAPPDATA\SETU\android-review-build" :app:assembleDebug :app:assembleDebugAndroidTest :app:testDebugUnitTest :app:lintDebug
python -m pytest tests/test_collection.py -q
python -m ruff check setu/collection.py tests/test_collection.py notebooks/finetune_phone.py
adb shell am instrument -w -r -e class com.setu.navigator.TrainingCollectionTest,com.setu.navigator.TrainingCollectionUiTest com.setu.navigator.test/androidx.test.runner.AndroidJUnitRunner
```

Do not run instrumentation during a user's recording. Physical accuracy,
long-duration/unplugged/background collection and production model promotion
remain separate qualifications. See `docs/22-phone-training-pipeline.md` for the
workflow, data contract, privacy and limitations.
