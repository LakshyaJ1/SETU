package com.setu.navigator

import android.hardware.Sensor
import android.os.SystemClock
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import com.setu.navigator.data.GeoPoint
import com.setu.navigator.data.Pose
import com.setu.navigator.data.TripStore
import com.setu.navigator.estimation.LiveEstimator
import com.setu.navigator.estimation.NativeEngine
import com.setu.navigator.estimation.NativeEstimate
import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Assume.assumeTrue
import org.junit.Test
import org.junit.runner.RunWith
import java.io.File
import java.util.Calendar
import java.util.TimeZone
import kotlin.math.*

@RunWith(AndroidJUnit4::class)
class SensorFallbackTest {
    private val context get() = InstrumentationRegistry.getInstrumentation().targetContext
    private val origin = GeoPoint(12.9753, 77.6067)
    private data class Frame(val seconds: Double, val reference: GeoPoint, val estimate: NativeEstimate)

    private fun replay(useGyro: Boolean = true, useAcceleration: Boolean = true,
                       gps: Boolean = true, magneticScale: Double = 1.0): List<Frame> {
        val now = System.currentTimeMillis()
        val calendar = Calendar.getInstance(TimeZone.getTimeZone("UTC")).apply { timeInMillis = now }
        val year = calendar.get(Calendar.YEAR) + (calendar.get(Calendar.DAY_OF_YEAR) - 1).toDouble() / calendar.getActualMaximum(Calendar.DAY_OF_YEAR)
        val field = NativeEngine(NativeEngine.magneticData(context)).use { requireNotNull(it.magneticField(year, origin, 0.0)) }
        val declination = atan2(field[0], field[1])
        val started = SystemClock.elapsedRealtimeNanos() - 30_000_000_000L
        var latest = NativeEstimate()
        val frames = mutableListOf<Frame>()
        var east = 0.0
        var north = 0.0
        val speed = 4.0
        LiveEstimator(context, { latest = it }, {}).use { estimator ->
            for (index in 0..2200) {
                val seconds = index / 100.0
                val heading = if (seconds < 5) 0.0 else 0.45 * sin(seconds - 5)
                val angularRate = if (seconds < 5) 0.0 else 0.45 * cos(seconds - 5)
                if (index > 0) {
                    val middle = seconds - 0.005
                    val middleHeading = if (middle < 5) 0.0 else 0.45 * sin(middle - 5)
                    east += speed * cos(middleHeading) * 0.01
                    north += speed * sin(middleHeading) * 0.01
                }
                val point = GeoPoint(origin.latitude + Math.toDegrees(north / 6378137.0),
                    origin.longitude + Math.toDegrees(east / (6378137.0 * cos(Math.toRadians(origin.latitude)))))
                val timestamp = started + index * 10_000_000L
                estimator.sensor(Sensor.TYPE_ACCELEROMETER, timestamp,
                    floatArrayOf(0f, if (useAcceleration) (speed * angularRate).toFloat() else 0f, 9.80665f), 3)
                estimator.sensor(Sensor.TYPE_GYROSCOPE, timestamp,
                    floatArrayOf(0f, 0f, if (useGyro) angularRate.toFloat() else 0f), 3)
                estimator.sensor(Sensor.TYPE_MAGNETIC_FIELD, timestamp, floatArrayOf(
                    ((cos(heading) * field[0] + sin(heading) * field[1]) * magneticScale).toFloat(),
                    ((-sin(heading) * field[0] + cos(heading) * field[1]) * magneticScale).toFloat(),
                    (field[2] * magneticScale).toFloat()), 3)
                val magneticHeading = heading + declination
                estimator.sensor(Sensor.TYPE_ROTATION_VECTOR, timestamp,
                    floatArrayOf(0f, 0f, sin(magneticHeading / 2).toFloat(), cos(magneticHeading / 2).toFloat(), -1f), 3)
                if (gps && index % 100 == 0 && index !in 600..1399) {
                    estimator.gnss(Pose(point, speed, (90 - Math.toDegrees(heading) + 360) % 360,
                        3.0, timestamp, "Controlled synthetic GPS", altitudeMeters = 0.0,
                        verticalAccuracyMeters = 5.0, speedAccuracyMps = 0.2, bearingAccuracyDegrees = 1.0, mock = true), now)
                }
                if (index % 10 == 0) frames.add(Frame(seconds, point, latest))
            }
        }
        return frames
    }

    @Test
    fun nativePositionsPublishAtTenHertzDuringGpsAndSensorOnlySegments() {
        val frames = replay()
        for (interval in listOf(2.0..4.9, 7.0..13.9, 17.0..21.9)) {
            val timestamps = frames.filter { it.seconds in interval }.mapNotNull { it.estimate.pose?.timestampNs }.distinct()
            assertTrue("Missing position updates in $interval", timestamps.size >= (interval.endInclusive - interval.start) * 9)
            assertTrue(timestamps.zipWithNext().all { (previous, current) -> current - previous in 1..110_000_000L })
        }
    }

    @Test
    fun missingHardwareHeadingAccuracyStillUsesRealSensorPipelineThroughTurns() {
        val frames = replay()
        val outage = frames.filter { it.seconds in 7.2..13.8 }
        assertTrue(outage.all { it.estimate.pose != null })
        assertTrue(outage.all { it.estimate.status == "Inertial estimate" })
        assertTrue(outage.all { it.estimate.headingSource == "Checked compass · estimated uncertainty" })
        assertEquals(1, outage.map { it.estimate.accepted }.distinct().size)
        val maximumError = outage.maxOf { it.reference.distanceTo(requireNotNull(it.estimate.pose).point) }
        assertTrue("Controlled turning error: $maximumError m", maximumError < 3.0)
        assertTrue(frames.last().estimate.accepted > outage.last().estimate.accepted)
        assertTrue(outage.last().estimate.radius95Meters!! > outage.first().estimate.radius95Meters!!)
        val noGyro = replay(useGyro = false).associateBy { it.seconds }
        val noAcceleration = replay(useAcceleration = false).associateBy { it.seconds }
        val gyroDifference = outage.maxOf { frame ->
            frame.estimate.pose!!.point.distanceTo(requireNotNull(noGyro.getValue(frame.seconds).estimate.pose).point)
        }
        val accelerationDifference = outage.maxOf { frame ->
            frame.estimate.pose!!.point.distanceTo(requireNotNull(noAcceleration.getValue(frame.seconds).estimate.pose).point)
        }
        assertTrue("Gyroscope input must affect the predicted turn", gyroDifference > 1.0)
        assertTrue("Accelerometer input must affect the predicted path", accelerationDifference > 1.0)
        val directory = File(context.getExternalFilesDir(null), "verification").apply { mkdirs() }
        File(directory, "sensor-fallback-metrics.json").writeText(JSONObject()
            .put("scenario", "Controlled turning sensor arrays through LiveEstimator and ARM64 JNI; not measured physical accuracy")
            .put("reportedHeadingAccuracy", -1).put("compassModelPriorDegrees", 30)
            .put("gpsWithheldSeconds", 8).put("maximumSyntheticErrorMeters", maximumError)
            .put("gyroAblationDifferenceMeters", gyroDifference)
            .put("accelerationAblationDifferenceMeters", accelerationDifference)
            .put("acceptedGpsDuringGap", 0).put("recoveryAccepted", true).toString(2))
    }

    @Test
    fun coldStartWithoutGpsNeverInventsAnAbsolutePosition() {
        val frames = replay(gps = false)
        assertTrue(frames.all { it.estimate.pose == null && it.estimate.accepted == 0 })
        assertTrue(frames.last().estimate.pairedSamples > 2000)
    }

    @Test
    fun disturbedMagnetometerDoesNotBypassHeadingChecks() {
        val frames = replay(magneticScale = 3.0)
        assertTrue(frames.all { it.estimate.pose == null && it.estimate.accepted == 0 })
        assertTrue(frames.last().estimate.pairedSamples > 2000)
    }

    @Test
    fun gpsMotionCalibratesThroughAccelerationAndTurnsWithoutACompassHeading() {
        val startNs = SystemClock.elapsedRealtimeNanos() - 30_000_000_000L
        val frames = mutableListOf<Frame>()
        val turnRate = 0.12
        var east = 0.0
        var north = 0.0
        var previousEastSpeed = 0.0
        var previousNorthSpeed = 0.0
        var currentSeconds = 0.0
        var reference = origin
        var stateRecords = 0
        LiveEstimator(context, { frames.add(Frame(currentSeconds, reference, it)) }, { record ->
            if (record.optString("type") == "native_state") {
                stateRecords++
                assertFalse(record.has("latitude"))
            }
        }).use { estimator ->
            for (step in 0..2400) {
                val seconds = step / 100.0
                val timestamp = startNs + step * 10_000_000L
                val speed = when { seconds < 4 -> 6.0 + 1.2 * seconds; seconds < 8 -> 10.8 - 0.8 * (seconds - 4); else -> 7.6 }
                val forwardAcceleration = when { seconds < 4 -> 1.2; seconds < 8 -> -0.8; else -> 0.0 }
                val angle = Math.toRadians(70.0) + turnRate * seconds
                val eastSpeed = speed * cos(angle)
                val northSpeed = speed * sin(angle)
                if (step > 0) { east += (previousEastSpeed + eastSpeed) * 0.005; north += (previousNorthSpeed + northSpeed) * 0.005 }
                previousEastSpeed = eastSpeed; previousNorthSpeed = northSpeed
                reference = GeoPoint(origin.latitude + north / 111320.0, origin.longitude + east / (111320.0 * cos(Math.toRadians(origin.latitude))))
                currentSeconds = seconds
                estimator.sensor(Sensor.TYPE_ACCELEROMETER, timestamp, floatArrayOf(forwardAcceleration.toFloat(), (speed * turnRate).toFloat(), 9.80665f), 3)
                estimator.sensor(Sensor.TYPE_GYROSCOPE, timestamp, floatArrayOf(0f, 0f, turnRate.toFloat()), 3)
                val rotation = floatArrayOf(0f, 0f, sin(turnRate * seconds / 2).toFloat(), cos(turnRate * seconds / 2).toFloat(), -1f)
                estimator.sensor(Sensor.TYPE_GAME_ROTATION_VECTOR, timestamp, rotation, 3)
                estimator.sensor(Sensor.TYPE_MAGNETIC_FIELD, timestamp, floatArrayOf(120f, 140f, 160f), 3)
                estimator.sensor(Sensor.TYPE_ROTATION_VECTOR, timestamp, rotation, 3)
                if (step % 100 == 0 && seconds !in 12.0..<20.0) {
                    estimator.gnss(Pose(reference, speed, (90.0 - Math.toDegrees(angle) + 360) % 360,
                        accuracyMeters = 3.0, timestampNs = timestamp, altitudeMeters = 0.0, verticalAccuracyMeters = 8.0,
                        speedAccuracyMps = 0.1, bearingAccuracyDegrees = 1.0, mock = true), System.currentTimeMillis())
                }
            }
        }
        val gap = frames.filter { it.seconds in 13.2..19.8 }
        assertTrue("Motion calibration must initialize before the GPS gap", frames.any { it.seconds < 12 && it.estimate.pose != null })
        assertTrue("Sensor estimates must cover the controlled eight-second gap", gap.all { it.estimate.pose != null })
        assertTrue(gap.all { it.estimate.headingSource == "GPS motion alignment · experimental" })
        assertEquals(1, gap.map { it.estimate.accepted }.distinct().size)
        val error = gap.maxOf { it.reference.distanceTo(requireNotNull(it.estimate.pose).point) }
        assertTrue("Controlled turn error: $error m", error < 5.0)
        assertTrue(frames.last().estimate.accepted > gap.last().estimate.accepted)
        assertTrue(stateRecords >= 20)
        File(File(context.getExternalFilesDir(null), "verification").apply { mkdirs() }, "gps-motion-alignment-metrics.json")
            .writeText(JSONObject().put("scenario", "Synthetic acceleration, braking and turns through LiveEstimator/JNI with disturbed compass; not measured road accuracy")
                .put("gpsWithheldSeconds", 8).put("firstAlignmentSeconds", frames.first { it.estimate.pose != null }.seconds)
                .put("maximumSyntheticErrorMeters", error).put("acceptedGpsDuringGap", 0).put("recoveryAccepted", true).toString(2))
    }

    @Test
    fun capturedPhysicalSensorsCanBeReplayedWithoutLeakingCoordinates() {
        assumeTrue(InstrumentationRegistry.getArguments().getString("replayCapturedSensors") == "true")
        val source = File(context.cacheDir, "fallback-check.setulog")
        val documents = source.bufferedReader().useLines { lines -> lines.map(::JSONObject).toList() }
        val header = documents.first()
        val firstNs = header.getLong("startedAtNs")
        val lastNs = documents.last().getLong("tNs")
        val shiftedStart = SystemClock.elapsedRealtimeNanos() - (lastNs - firstNs) - 2_000_000_000L
        val statuses = mutableMapOf<String, Int>()
        val details = mutableMapOf<String, Int>()
        var nativeSamples = 0
        var inertialSamples = 0
        var paired = 0L
        var firstAlignment: Double? = null
        var withheldGps = 0
        LiveEstimator(context, { estimate ->
            statuses[estimate.status] = (statuses[estimate.status] ?: 0) + 1
            details[estimate.detail] = (details[estimate.detail] ?: 0) + 1
            paired = estimate.pairedSamples
            if (estimate.pose != null) {
                nativeSamples++
                if (firstAlignment == null) firstAlignment = (estimate.pose.timestampNs - shiftedStart) / 1e9
                if (estimate.status == "Inertial estimate") inertialSamples++
            }
        }, {}).use { estimator ->
            documents.drop(1).forEach { document ->
                val elapsed = document.getLong("tNs") - firstNs
                val timestamp = shiftedStart + elapsed
                when (document.optString("type")) {
                    "pose" -> {
                        if (elapsed in 30_000_000_000L..37_999_999_999L) withheldGps++
                        else estimator.gnss(TripStore.decodePose(document).copy(timestampNs = timestamp),
                            header.getLong("startedAtMs") + elapsed / 1_000_000L)
                    }
                    "accelerometer", "gyroscope", "magnetometer", "rotation_vector", "game_rotation_vector" -> {
                        val type = when (document.getString("type")) {
                            "accelerometer" -> Sensor.TYPE_ACCELEROMETER
                            "gyroscope" -> Sensor.TYPE_GYROSCOPE
                            "magnetometer" -> Sensor.TYPE_MAGNETIC_FIELD
                            "game_rotation_vector" -> Sensor.TYPE_GAME_ROTATION_VECTOR
                            else -> Sensor.TYPE_ROTATION_VECTOR
                        }
                        val values = document.getJSONArray("values")
                        estimator.sensor(type, timestamp, FloatArray(values.length()) { values.getDouble(it).toFloat() }, document.getInt("accuracy"))
                    }
                }
            }
        }
        val directory = File(context.getExternalFilesDir(null), "verification").apply { mkdirs() }
        File(directory, "captured-sensor-replay-metrics.json").writeText(JSONObject()
            .put("scenario", "Replay of captured physical sensors with an artificial eight-second GPS omission; not a live outage or surveyed accuracy")
            .put("pairedSamples", paired).put("nativeSamples", nativeSamples).put("inertialSamples", inertialSamples)
            .put("gpsObservationsWithheld", withheldGps).put("firstAlignmentSeconds", firstAlignment ?: JSONObject.NULL)
            .put("statuses", JSONObject(statuses.toMap())).put("details", JSONObject(details.toMap())).toString(2))
        assertTrue("Captured raw IMU must be processed", paired > 1000)
        assertTrue("Captured compass and GPS must initialize: $details", nativeSamples > 0)
        assertTrue("Captured sensors must propagate through the deliberately omitted GPS interval", inertialSamples > 0)
    }
}
