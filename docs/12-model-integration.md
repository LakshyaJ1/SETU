# Android / model-team handoff

## Ownership and current boundary

The model teammate owns weights, feature extraction, trained uncertainty and
model evaluation. Android owns permissions, timestamped acquisition, local logs,
UI state and the provider boundary in
`android/app/src/main/java/com/setu/navigator/model/ModelProvider.kt`.

No trained model or fabricated prediction ships in the APK. The supplied HTTPS
endpoint now advertises an experimental CNN-GRU speed provider. Its health reason
explicitly states that phone axes and sigma are unverified, validity is always
zero, and predictions must not drive navigation. The app preserves that warning.
The local contract server still deliberately returns **unavailable**.

Android now streams real, timestamp-paired accelerometer/gyroscope windows to the
configured provider only after explicit sharing consent and only while recording.
Results are displayed and logged as **evaluation-only**, never substituted for a
position or fused into the native filter. Validity zero cannot become zero speed
or an accepted observation. Calibrated model-to-core fusion and on-device inference
remain required production work, not consequences of a green health check.

## Transport

`ModelProvider` is the application interface. An on-device implementation should
replace the development HTTP adapter without moving estimation into Compose.
HTTP is a team-development convenience, not a mandatory runtime/cloud dependency.
Release endpoints require HTTPS. Debug builds additionally allow HTTP on
localhost, 127.0.0.1 and the Android emulator's host alias 10.0.2.2.

Connections time out after five seconds. Redirects are not followed. Credentials
in the URL are rejected. A connection check does not send sensor data.

The default endpoint is `https://setu-proj-sih.duckdns.org`. Changing it revokes
sharing consent. A legacy stored sharing flag does not count as approval for the
new upload behavior; a versioned consent is required. Stopping a recording or
revoking consent cancels the session and prevents late results from being logged.
No saved recording is uploaded. An in-flight request already delivered to the
server cannot be recalled; the consent dialog states that boundary.

The live collector retains four continuous seconds of raw phone-body SI samples,
uses their measured rate, caps a window at 2,048 samples, and resets across paired
sample gaps above 50 ms. It emits at most once per second. Exactly one request is
in flight; only the latest waiting window is kept. Windows older than 500 ms are
not sent, responses older than two seconds are withheld, and transport failures
back off without stopping GPS or local recording. This remote transport is not
the offline production inference path required by REQ-F2/F9.

## GET /v1/health

```json
{
  "schema": "setu.model.v1",
  "status": "unavailable",
  "model": "No model installed",
  "capabilities": []
}
```

Use `ready` only when a real model can serve its advertised capabilities. The app
must not equate readiness with validated navigation accuracy.

## POST /v1/measurements

Input is a timestamp-ordered window of 1-2048 samples, raw phone-body axes, SI
units. Acceleration includes gravity. The provider owns its documented feature
conditioning; channel order must not change silently. Monotonic timestamps are
signed 64-bit nanoseconds, not wall-clock milliseconds.

```json
{
  "schema": "setu.model.v1",
  "rateHz": 200.0,
  "vehicle": "Car",
  "samples": [
    {"tNs": 1000000000, "accelerationMps2": [0.0, 0.0, 9.81], "angularRateRps": [0.0, 0.0, 0.0]}
  ]
}
```

No GPS coordinates, CAN truth or unavailable GNSS measurements belong in this
phone-only inference request. Training-only supervision must stay outside it.

A successful speed measurement has `schema`, `tNs`, `speedMps`, `sigmaMps` and
`validity`. The adapter rejects non-finite values, speed outside 0-100 m/s,
non-positive sigma, validity outside 0-1 and timestamps outside the input window.
The core must additionally gate stale responses against its current time and
innovation, not merely accept a valid JSON response.

Unavailable is a first-class response:

```json
{"schema":"setu.model.v1","status":"unavailable","reason":"No model loaded"}
```

`ModelResult` preserves an unavailable response's reason separately from an
optional measurement. Health reasons and zero validity remain visible in the UI.
Never send a zero-speed prediction to represent absence. Future measurement
types need a schema revision and explicit capability advertisement.

## Run the model-free handoff server

```powershell
python tools/model_contract_server.py --port 8765
```

In a debug emulator build, enter `http://10.0.2.2:8765` under Settings > Model
integration. A successful check should report **Model unavailable**, not inference
success. The server binds only to the host loopback address.

## Android recording format: implementation note

The initial Android recorder writes UTF-8 JSON Lines with a `.setulog` extension.
The first record declares `schema: setu.log.v1`, SI units, monotonic clock, source
device, start time and synthetic provenance. Subsequent records are accelerometer,
gyroscope, magnetometer, barometer, GNSS raw epochs or poses. Each record retains
the source timestamp; replay must order streams explicitly.

This is **not yet the protobuf container proposed in docs/05-system-design.md**.
Do not feed it to a protobuf reader or claim format parity. The delivery ledger
must keep that integration gap visible until the final format is reconciled.
Exports contain the original log; imports are capped at 100 MB and validated.

### GPS measurement presence

New `pose` records carry `measurementVersion: 1`. Optional `speedMps`, `bearing`
(course over ground in degrees), `accuracyMeters`, `altitudeMeters` (WGS84
ellipsoid, not mean sea level), `verticalAccuracyMeters`, `speedAccuracyMps`,
and `bearingAccuracyDegrees` are numbers or explicit JSON null. Android's
corresponding `has…` flags determine presence. Measured zero speed/course/altitude
remains zero; absent values do not become a stationary, northbound, sea-level or
perfectly accurate observation. Accuracy fields remain Android-reported estimates,
not automatically the per-axis covariance expected by the native filter.

`mock` records Android's mock-provider flag (boolean; null for unknown provenance).
It is an origin flag, not proof that non-mock positions are trustworthy. New GPS
callbacks with invalid coordinates, future/zero timestamps, or timestamps no newer
than the latest accepted position are excluded from the live position/log stream.
This rejects delayed fixes; it does not implement delayed-measurement fusion.

Versionless legacy records remain readable. Their zero speed, bearing and accuracy
values are ambiguous because the old recorder substituted zero for missing fields,
so decoding conservatively treats those zeros as unknown. Nonzero valid values
survive. Original imported/exported bytes are not rewritten; only decoded metadata
uses the safer interpretation. Metadata numbers must be finite and in range, and
unsupported measurement versions are rejected rather than silently interpreted.

The live freshness window is three seconds, measured on the monotonic clock;
future timestamps are never fresh. Stale positions remain visibly labelled as
last-known, without a directional arrow or current accuracy area. Diagnostics
shows observation age and missing values explicitly. This is data-integrity
handling, not evidence of live native fusion or blackout navigation.

The optional non-ML native stream now consumes these observations. It publishes
separately named `native_pose` records, leaving raw GPS `pose` records intact and
adding `experimental`, `radius95Meters`, `gpsAgeSeconds` and provenance fields.
`rotation_vector` records retain Android's values and accuracy for seed analysis.
These are not AI inference results or reference ground truth. Details and the
remaining model-consumption boundary are in `core/STREAMING.md`.

With model sharing enabled, new `model_measurement` records carry receive time in
`tNs`, the source measurement time separately in `measurementTimestampNs`, model
name, status, speed, reported sigma, validity, and latency. Missing predictions
have null values, not fabricated zeros. `navigationApplied` is false for this
research integration. These records never become the trip's trajectory stream.
They survive raw export/import, with the same privacy protections as the log.

When the latest GPS position is outside the included Bengaluru map, destination
browsing still produces an explicitly labelled MG Road preview. Drive start is
disabled and independently guarded in the view model; a preview never silently
becomes navigation from an unsupported origin. The coverage bound is the existing
bundled-region bound, not a claim that all roads inside it are routable.
