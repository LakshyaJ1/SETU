package com.setu.navigator

import android.content.Intent
import android.hardware.Sensor
import android.hardware.SensorManager
import android.os.SystemClock
import androidx.test.core.app.ActivityScenario
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import com.setu.navigator.data.GeoPoint
import com.setu.navigator.data.Pose
import com.setu.navigator.data.RecordingService
import com.setu.navigator.data.TripStore
import com.setu.navigator.estimation.LiveEstimator
import com.setu.navigator.estimation.ImuSynchronizer
import com.setu.navigator.estimation.NativeEstimate
import com.setu.navigator.estimation.WalkingTracker
import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Assume.assumeTrue
import org.junit.Test
import org.junit.runner.RunWith
import java.io.File
import kotlin.math.cos
import kotlin.math.sin

@RunWith(AndroidJUnit4::class)
class WalkingIntegrationTest {
    private val instrumentation = InstrumentationRegistry.getInstrumentation()
    private val context = instrumentation.targetContext

    @Test fun syntheticPlatformCallbacksUseStepsAndWithholdWithoutPermission() {
        for (available in listOf(true, false)) {
            var estimate = NativeEstimate()
            var timestamp = 1_000_000_000L
            val origin = GeoPoint(28.7, 77.2)
            LiveEstimator(context, { estimate = it }, {}, { Long.MAX_VALUE }, .7, { available }).use { estimator ->
                estimator.gnss(Pose(origin, 0.0, accuracyMeters = 3.0, timestampNs = timestamp, mock = true), 1_789_387_200_000L)
                repeat(1500) { index ->
                    timestamp += 20_000_000L
                    estimator.sensor(Sensor.TYPE_ACCELEROMETER, timestamp, floatArrayOf(0f, 0f, 9.80665f), 3)
                    estimator.sensor(Sensor.TYPE_GYROSCOPE, timestamp, FloatArray(3), 3)
                    estimator.sensor(Sensor.TYPE_GAME_ROTATION_VECTOR, timestamp, floatArrayOf(0f, 0f, 0f, 1f), 3)
                    estimator.sensor(Sensor.TYPE_ROTATION_VECTOR, timestamp, floatArrayOf(0f, 0f, 0f, 1f, .2f), 3)
                    if (index == 300 || index == 325) estimator.sensor(Sensor.TYPE_STEP_DETECTOR, timestamp, floatArrayOf(1f), 3)
                }
                assertEquals(0, estimator.speed(timestamp, 30.0, 1.0))
                if (available) {
                    assertEquals("Walking step estimate", estimate.status)
                    assertEquals(2L, estimate.walkingSteps)
                    assertEquals(0.0, estimate.pose!!.speedMps!!, 0.0)
                    assertEquals(1.4, origin.distanceTo(estimate.pose!!.point), .02)
                    assertTrue(estimate.pose!!.mock == true)
                } else {
                    assertEquals("Walking sensor unavailable", estimate.status)
                    assertNull(estimate.pose)
                }
            }
        }
    }

    @Test fun replayPrivateWalkingRecordingsChecksTheUncalibratedCeiling() {
        val names = InstrumentationRegistry.getArguments().getString("recordingIds")
        assumeTrue("Opt in with existing recording IDs; originals are read only.", names != null)
        val reports = org.json.JSONArray()
        for (id in checkNotNull(names).split(',')) {
            require(id.matches(Regex("[a-f0-9-]{36}")))
            val source = File(context.filesDir, "trips/$id.setulog")
            var outputs = 0
            var maximumSpeed = 0.0
            var maximumAge = 0.0
            var withheld = 0
            var rawModelMaximum = 0.0
            val types = mapOf("accelerometer" to Sensor.TYPE_ACCELEROMETER, "gyroscope" to Sensor.TYPE_GYROSCOPE,
                "magnetometer" to Sensor.TYPE_MAGNETIC_FIELD, "rotation_vector" to Sensor.TYPE_ROTATION_VECTOR,
                "game_rotation_vector" to Sensor.TYPE_GAME_ROTATION_VECTOR)
            LiveEstimator(context, { estimate ->
                if (estimate.status == "Estimate withheld") withheld++
                estimate.pose?.let {
                    outputs++
                    assertFalse("Walking log falsely calibrated as a vehicle", estimate.vehicleCalibrated)
                    assertTrue(checkNotNull(estimate.gpsAgeSeconds) <= 10.0)
                    maximumAge = maxOf(maximumAge, checkNotNull(estimate.gpsAgeSeconds))
                    maximumSpeed = maxOf(maximumSpeed, it.speedMps ?: 0.0)
                }
            }, {}, { Long.MAX_VALUE }).use { estimator ->
                source.useLines { lines -> lines.drop(1).forEach { line ->
                    val record = JSONObject(line)
                    val type = record.optString("type")
                    types[type]?.let { sensor ->
                        val values = record.getJSONArray("values")
                        estimator.sensor(sensor, record.getLong("tNs"), FloatArray(values.length()) { values.getDouble(it).toFloat() }, record.optInt("accuracy"))
                    }
                    if (type == "pose" && record.optDouble("accuracyMeters", 1000.0) <= 35.0)
                        estimator.gnss(TripStore.decodePose(record), record.getLong("wallTimeMs"))
                    if (type == "model_measurement" && !record.isNull("speedMps")) {
                        assertFalse(record.optBoolean("navigationApplied"))
                        assertEquals(0.0, record.getDouble("validity"), 0.0)
                        rawModelMaximum = maxOf(rawModelMaximum, record.getDouble("speedMps"))
                    }
                } }
            }
            reports.put(JSONObject().put("recording", id).put("availableOutputs", outputs).put("withheldOutputs", withheld)
                .put("maximumNativeSpeedMps", maximumSpeed).put("maximumGpsAgeSeconds", maximumAge)
                .put("originalUnvalidatedModelMaximumMps", rawModelMaximum))
        }
        File(context.getExternalFilesDir(null), "verification").apply { mkdirs() }
            .resolve("walking-recording-replay.json").writeText(reports.toString(2))
    }

    @Test fun physicalWalkingProfileRecordsImuWithoutRunningCarModel() = verifyWalkingCapture(false)

    @Test fun physicalWalkingEstimateSurvivesGpsOffAtRest() {
        assumeTrue(InstrumentationRegistry.getArguments().getString("walkingBlackout") == "true")
        verifyWalkingCapture(true)
    }

    private fun verifyWalkingCapture(blackout: Boolean) {
        assumeTrue(InstrumentationRegistry.getArguments().getString("physicalHardware") == "true")
        val repository = (context.applicationContext as SetuApplication).repository
        check(!repository.recording.value)
        check(repository.hub.hasStepPermission())
        if (blackout) check(repository.hub.isLocationEnabled())
        val saved = repository.settings.value
        val existing = repository.tripStore.all().map { it.id }.toSet()
        var ownsRecording = false
        var restoreLocation = false
        var gpsOffChecks = 0
        val name = "USB walking sensor verification"
        ActivityScenario.launch(MainActivity::class.java).use { scenario ->
            try {
                scenario.onActivity {
                    it.window.addFlags(android.view.WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
                    repository.updateSettings(saved.copy(vehicle = "Walking", modelSharingAllowed = false, nativePositioning = true))
                    repository.hub.start()
                    it.startForegroundService(Intent(it, RecordingService::class.java).setAction("START").putExtra("name", name))
                    ownsRecording = true
                }
                waitUntil { repository.recording.value && repository.hub.sensors.value.achievedHz > 50 }
                assertTrue(repository.hub.sensors.value.stepDetectorActive)
                if (blackout) {
                    waitUntil { repository.hub.nativeEstimate.value.currentPose(SystemClock.elapsedRealtimeNanos()) != null }
                    restoreLocation = true
                    instrumentation.uiAutomation.executeShellCommand("cmd location set-location-enabled false").close()
                    waitUntil { !repository.hub.isLocationEnabled() }
                    SystemClock.sleep(2000)
                    val anchor = repository.hub.nativeEstimate.value
                    val point = checkNotNull(anchor.currentPose(SystemClock.elapsedRealtimeNanos())).point
                    var previousTimestamp = checkNotNull(anchor.pose).timestampNs
                    repeat(60) {
                        SystemClock.sleep(200)
                        val current = repository.hub.nativeEstimate.value
                        val pose = checkNotNull(current.currentPose(SystemClock.elapsedRealtimeNanos()))
                        assertEquals("Walking step estimate", pose.source)
                        assertEquals(0.0, checkNotNull(pose.speedMps), 0.0)
                        assertEquals(point, pose.point)
                        assertEquals(anchor.accepted, current.accepted)
                        assertEquals(anchor.walkingSteps, current.walkingSteps)
                        assertTrue(pose.timestampNs > previousTimestamp)
                        previousTimestamp = pose.timestampNs
                        gpsOffChecks++
                    }
                    assertTrue(checkNotNull(repository.hub.nativeEstimate.value.gpsAgeSeconds) >= 12)
                } else SystemClock.sleep(30_000)
                assertNull(repository.hub.modelSession)
                context.startService(Intent(context, RecordingService::class.java).setAction("STOP"))
                waitUntil { !repository.recording.value }
                val trip = repository.tripStore.all().single { it.id !in existing && it.name == name }
                val counts = mutableMapOf<String, Int>()
                var peak = 0.0
                repository.tripStore.logFile(trip.id).useLines { lines ->
                    val records = lines.iterator()
                    val collection = JSONObject(records.next()).getJSONObject("collection")
                    assertEquals("Walking", collection.getString("vehicle"))
                    assertFalse(collection.getBoolean("localModelEnabled"))
                    records.forEach { line ->
                        val record = JSONObject(line)
                        val type = record.getString("type")
                        counts[type] = (counts[type] ?: 0) + 1
                        assertNotEquals("model_measurement", type)
                        if (type == "native_pose" && !record.isNull("speedMps")) peak = maxOf(peak, record.getDouble("speedMps"))
                    }
                }
                assertTrue((counts["accelerometer"] ?: 0) > 1000)
                assertTrue((counts["gyroscope"] ?: 0) > 1000)
                assertTrue(peak <= saved.walkingStepLengthMeters / .25)
                File(context.getExternalFilesDir(null), "verification").apply { mkdirs() }
                    .resolve(if (blackout) "walking-blackout.json" else "walking-hardware.json")
                    .writeText(JSONObject().put("counts", JSONObject(counts as Map<*, *>))
                        .put("peakStepSpeedMps", if ((counts["native_pose"] ?: 0) > 0) peak else JSONObject.NULL)
                        .put("gpsOffStationaryChecks", gpsOffChecks)
                        .put("stepDetectorRegistered", true).put("carModelRunning", false)
                        .put("physicalWalkingAccuracyMeasured", false).toString(2))
            } finally {
                if (restoreLocation) instrumentation.uiAutomation.executeShellCommand("cmd location set-location-enabled true").close()
                if (ownsRecording && repository.recording.value) {
                    context.startService(Intent(context, RecordingService::class.java).setAction("STOP"))
                    waitUntil { !repository.recording.value }
                }
                repository.tripStore.all().filter { it.id !in existing && it.name == name }.forEach(repository.tripStore::delete)
                repository.refreshTrips()
                repository.updateSettings(saved)
            }
        }
    }

    @Test fun replayCapturedStepBatchesWithRecordedInitialHeading() {
        val id = InstrumentationRegistry.getArguments().getString("walkingRecordingId")
        assumeTrue("Opt in with a captured walking recording ID.", id != null)
        require(checkNotNull(id).matches(Regex("[a-f0-9-]{36}")))
        val source = File(context.filesDir, "trips/$id.setulog")
        var observedSteps = 0L
        var positionedSteps = 0L
        var rejectedSteps = 0L
        var gpsOn = true
        var gpsOffOutputs = 0
        var gpsOffAvailable = 0
        var peakSpeed = 0.0
        var finalSpeed: Double? = null
        val initial = source.useLines { lines -> lines.map(::JSONObject).first { it.optString("type") == "native_pose" } }
        val bearing = Math.toRadians(initial.getDouble("bearing"))
        val initialRotation = doubleArrayOf(cos(bearing), sin(bearing), 0.0, -sin(bearing), cos(bearing), 0.0, 0.0, 0.0, 1.0)
        var aligned = false
        var lastPublish = 0L
        source.bufferedReader().use { reader ->
            val header = JSONObject(checkNotNull(reader.readLine()))
            val metadata = header.getJSONObject("collection")
            assertEquals("Walking", metadata.getString("vehicle"))
            val tracker = WalkingTracker(metadata.getDouble("walkingStepLengthMeters"))
            val synchronizer = ImuSynchronizer { timestamp, _, gyro ->
                tracker.imu(timestamp, gyro)
                if (timestamp - lastPublish < 100_000_000L) return@ImuSynchronizer
                lastPublish = timestamp
                val estimate = tracker.estimate(timestamp)
                positionedSteps = maxOf(positionedSteps, estimate.walkingSteps)
                rejectedSteps = maxOf(rejectedSteps, estimate.rejectedSteps)
                if (!gpsOn) { gpsOffOutputs++; if (estimate.pose != null) gpsOffAvailable++ }
                estimate.pose?.speedMps?.let { peakSpeed = maxOf(peakSpeed, it); finalSpeed = it }
            }
            reader.lineSequence().forEach { line ->
                val record = JSONObject(line)
                val type = record.getString("type")
                assertNotEquals("collection_change", type)
                val timestamp = record.optLong("tNs")
                when (type) {
                    "location_state" -> gpsOn = record.getBoolean("enabled")
                    "step_detector" -> { observedSteps++; tracker.step(timestamp) }
                    "accelerometer", "gyroscope" -> {
                        val values = record.getJSONArray("values")
                        val vector = DoubleArray(3) { values.getDouble(it) }
                        if (type == "accelerometer") synchronizer.acceleration(timestamp, vector)
                        else synchronizer.gyroscope(timestamp, vector)
                    }
                    "game_rotation_vector" -> {
                        val values = record.getJSONArray("values")
                        val matrix = FloatArray(9)
                        SensorManager.getRotationMatrixFromVector(matrix, FloatArray(values.length()) { values.getDouble(it).toFloat() })
                        tracker.rotation(timestamp, DoubleArray(9) { matrix[it].toDouble() })
                        if (!aligned && timestamp >= initial.getLong("tNs")) {
                            assertTrue(timestamp - initial.getLong("tNs") < 100_000_000L)
                            tracker.align(timestamp, initialRotation, .6)
                            aligned = true
                        }
                    }
                    "pose" -> tracker.gnss(TripStore.decodePose(record))
                }
            }
        }
        File(context.getExternalFilesDir(null), "verification").apply { mkdirs() }
            .resolve("walking-batch-replay.json").writeText(JSONObject().put("observedSteps", observedSteps)
                .put("positionedSteps", positionedSteps).put("rejectedSteps", rejectedSteps)
                .put("gpsOffOutputs", gpsOffOutputs).put("gpsOffAvailable", gpsOffAvailable)
                .put("peakSpeedMps", peakSpeed).put("finalSpeedMps", finalSpeed ?: JSONObject.NULL)
                .put("initialHeadingSource", "Recorded initial native bearing; calibration predates this recording")
                .put("initialHeadingSigmaRadians", .6).put("compassInitializationValidated", false)
                .put("groundTruthAccuracyMeasured", false).toString(2))
        assertTrue(observedSteps > 0)
        assertEquals(observedSteps, positionedSteps)
        assertEquals(0L, rejectedSteps)
        assertTrue(gpsOffAvailable > 0)
        assertTrue(peakSpeed in .3..2.8)
        assertEquals(0.0, checkNotNull(finalSpeed), 0.0)
    }

    private fun waitUntil(condition: () -> Boolean) {
        val deadline = SystemClock.elapsedRealtime() + 20_000
        while (!condition()) {
            check(SystemClock.elapsedRealtime() < deadline) { "Timed out waiting for the recording service." }
            SystemClock.sleep(100)
        }
    }
}
