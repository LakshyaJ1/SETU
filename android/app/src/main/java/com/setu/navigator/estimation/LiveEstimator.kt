package com.setu.navigator.estimation

import android.content.Context
import android.hardware.Sensor
import android.hardware.SensorManager
import android.os.SystemClock
import com.setu.navigator.data.GeoPoint
import com.setu.navigator.data.Pose
import com.setu.navigator.data.TripStore
import org.json.JSONObject
import java.util.Calendar
import java.util.TimeZone
import kotlin.math.cos
import kotlin.math.sin

data class NativeEstimate(
    val status: String = "Starting native engine",
    val detail: String = "Waiting for aligned IMU, a recent GPS fix and a usable heading.",
    val pose: Pose? = null,
    val radius95Meters: Double? = null,
    val gpsAgeSeconds: Double? = null,
    val accepted: Int = 0,
    val gated: Int = 0,
    val rejected: Int = 0,
    val delayedCorrections: Int = 0,
    val resets: Int = 0,
    val pairedSamples: Long = 0,
    val pairingDrops: Long = 0,
    val headingSource: String? = null,
    val calibrationHint: String? = null,
    // Dead-reckoning constraint activity, so the diagnostics screen can show that the GNSS-denied
    // path is actually engaging rather than leaving it to be inferred.
    val zupts: Int = 0,
    val nhcs: Int = 0,
    val turnSpeedUpdates: Int = 0,
    val spectralUpdates: Int = 0,
    val spectralScale: Double? = null,
) {
    fun currentPose(nowNs: Long): Pose? = pose?.takeIf { nowNs >= it.timestampNs && nowNs - it.timestampNs <= 300_000_000L }
}

fun navigationPose(gps: Pose?, estimate: NativeEstimate, enabled: Boolean, nowNs: Long): Pose? =
    if (enabled) estimate.currentPose(nowNs) ?: gps else gps

class LiveEstimator(context: Context, private val publish: (NativeEstimate) -> Unit,
                    private val record: (JSONObject) -> Unit) : AutoCloseable {
    private val engine = NativeEngine(NativeEngine.magneticData(context))
    private var declination = Double.NaN
    private var headingAccuracyAvailable: Boolean? = null
    private val compass = CompassAlignment()
    private val motion = MotionAlignment()
    private var headingSource: String? = null
    private var pendingHeadingSource: String? = null
    private var hadPose = false
    private var lastStateRecord = 0L
    private var pairedSamples = 0L
    private var lastPublish = 0L
    private val synchronizer: ImuSynchronizer = ImuSynchronizer { timestamp, acceleration, gyro ->
        motion.imu(timestamp, acceleration, gyro)
        applyMotionAlignment(timestamp)
        engine.imu(timestamp, acceleration, gyro)
        pairedSamples++
        if (timestamp - lastPublish >= 100_000_000L) {
            lastPublish = timestamp
            val snapshot = engine.snapshot()
            var estimate = decodeNativeEstimate(snapshot, pairedSamples, synchronizerDrops(), headingAccuracyAvailable)
            if (estimate.pose != null && !hadPose) headingSource = pendingHeadingSource
            hadPose = estimate.pose != null
            estimate = estimate.copy(headingSource = if (hadPose) headingSource else pendingHeadingSource)
            if (snapshot[0].toInt() in 0..1) {
                estimate = estimate.copy(status = "Calibrating sensors", detail = "${compass.detail} ${motion.detail}", calibrationHint = compass.detail)
            }
            if (estimate.pose != null && headingSource == "Checked compass · estimated uncertainty") {
                estimate = estimate.copy(detail = "Compass-aligned sensor prediction with estimated uncertainty. No road matching or field-accuracy guarantee. GPS outages are bounded to 10 seconds or a 150 m filter radius.")
            }
            publish(estimate)
            if (timestamp - lastStateRecord >= 1_000_000_000L) {
                lastStateRecord = timestamp
                record(JSONObject().put("type", "native_state").put("tNs", timestamp)
                    .put("status", estimate.status).put("detail", estimate.detail)
                    .put("pairedSamples", pairedSamples).put("acceptedGps", estimate.accepted)
                    .put("pairingDrops", estimate.pairingDrops)
                    .put("headingSource", estimate.headingSource ?: JSONObject.NULL)
                    .put("hasEstimate", estimate.pose != null))
            }
            estimate.pose?.let { pose ->
                record(TripStore.encodePose(pose).put("type", "native_pose")
                    .put("radius95Meters", estimate.radius95Meters)
                    .put("gpsAgeSeconds", estimate.gpsAgeSeconds).put("status", estimate.status)
                    .put("headingSource", headingSource ?: JSONObject.NULL).put("experimental", true))
            }
        }
    }

    private fun synchronizerDrops(): Long = synchronizer.rejected

    private fun applyMotionAlignment(timestamp: Long): Boolean {
        val alignment = motion.alignment(timestamp) ?: return false
        if (engine.attitude(alignment.timestamp, alignment.rotation, alignment.sigmaRadians) != 1) return false
        pendingHeadingSource = "GPS motion alignment · experimental"
        return true
    }

    // The sensor callbacks are single-threaded on the sensor HandlerThread and every consumer
    // (ImuSynchronizer, CompassAlignment, MotionAlignment, the JNI bridge) copies what it keeps, so
    // these scratch buffers replace four array allocations per callback.
    private val vectorScratch = DoubleArray(3)
    private val matrixScratch = FloatArray(9)
    private val rotationScratch = DoubleArray(9)
    private val trueRotationScratch = DoubleArray(9)

    private fun copy(values: FloatArray): DoubleArray {
        vectorScratch[0] = values[0].toDouble()
        vectorScratch[1] = values[1].toDouble()
        vectorScratch[2] = values[2].toDouble()
        return vectorScratch
    }

    private fun rotationMatrix(values: FloatArray): DoubleArray {
        SensorManager.getRotationMatrixFromVector(matrixScratch, values)
        for (index in 0 until 9) rotationScratch[index] = matrixScratch[index].toDouble()
        return rotationScratch
    }

    fun sensor(type: Int, timestamp: Long, values: FloatArray, accuracy: Int) {
        if (timestamp <= 0 || timestamp > SystemClock.elapsedRealtimeNanos() || values.any { !it.isFinite() }) return
        when (type) {
            Sensor.TYPE_ACCELEROMETER -> {
                if (values.size < 3) return
                val sample = copy(values)
                compass.acceleration(timestamp, sample)
                synchronizer.acceleration(timestamp, sample)
            }
            Sensor.TYPE_GYROSCOPE -> {
                if (values.size < 3) return
                val sample = copy(values)
                compass.gyroscope(timestamp, sample)
                synchronizer.gyroscope(timestamp, sample)
            }
            Sensor.TYPE_MAGNETIC_FIELD -> {
                if (values.size < 3) return
                compass.magnetometer(timestamp, copy(values), accuracy)
            }
            Sensor.TYPE_GAME_ROTATION_VECTOR -> {
                if (values.size < 3) return
                motion.rotation(timestamp, rotationMatrix(values))
                applyMotionAlignment(timestamp)
            }
            Sensor.TYPE_ROTATION_VECTOR -> {
                headingAccuracyAvailable = values.size >= 5 && values[4] >= 0
                if (!declination.isFinite() || values.size < 3) return
                val trueRotation = trueNorthRotation(rotationMatrix(values), declination, trueRotationScratch)
                val reportedSigma = if (values.size >= 5) values[4].toDouble() else null
                val alignment = compass.evaluate(timestamp, trueRotation, reportedSigma, accuracy) ?: return
                if (!applyMotionAlignment(timestamp) && engine.attitude(timestamp, trueRotation, alignment.sigmaRadians) == 1) pendingHeadingSource = alignment.source
            }
        }
    }

    fun gnss(pose: Pose, wallTimeMs: Long) {
        val calendar = Calendar.getInstance(TimeZone.getTimeZone("UTC")).apply { timeInMillis = wallTimeMs }
        val year = calendar.get(Calendar.YEAR) + (calendar.get(Calendar.DAY_OF_YEAR) - 1).toDouble() / calendar.getActualMaximum(Calendar.DAY_OF_YEAR)
        declination = engine.declination(year, pose.point, pose.altitudeMeters ?: 0.0)
        engine.magneticField(year, pose.point, pose.altitudeMeters ?: 0.0)?.let(compass::reference)
        motion.gnss(pose)
        applyMotionAlignment(pose.timestampNs)
        engine.gnss(pose)
    }

    /**
     * Forward speed from the on-device model.
     *
     * The measurement is produced on a background thread by the inference session, but the engine
     * is only safe to touch from the sensor thread, so it is posted there rather than applied
     * inline. A speed that cannot be applied is dropped, not queued: by the time a queue drained it
     * would describe a moment the filter has already left.
     */
    fun speed(timestampNs: Long, speedMps: Double, sigmaMps: Double): Int =
        engine.speed(timestampNs, speedMps, sigmaMps)

    override fun close() = engine.close()
}

internal fun trueNorthRotation(magnetic: DoubleArray, declination: Double): DoubleArray =
    trueNorthRotation(magnetic, declination, DoubleArray(9))

/** Writes the true-north rotation into [destination], which may not alias [magnetic]. */
internal fun trueNorthRotation(magnetic: DoubleArray, declination: Double, destination: DoubleArray): DoubleArray {
    require(magnetic.size == 9 && magnetic.all(Double::isFinite) && declination.isFinite() && destination.size == 9)
    val cosine = cos(declination)
    val sine = sin(declination)
    for (index in 0 until 9) {
        destination[index] = when (index / 3) {
            0 -> cosine * magnetic[index] + sine * magnetic[index + 3]
            1 -> -sine * magnetic[index - 3] + cosine * magnetic[index]
            else -> magnetic[index]
        }
    }
    return destination
}

internal fun decodeNativeEstimate(values: DoubleArray, paired: Long = 0, dropped: Long = 0,
                                  headingAccuracyAvailable: Boolean? = null): NativeEstimate {
    // Greater-or-equal, not equal: the native estimate array grows as the engine reports more, and
    // pinning it to an exact length meant adding the dead-reckoning counters crashed every sensor
    // callback with "Failed requirement" before the first frame was drawn. Older fields keep their
    // indices, so reading a prefix stays correct.
    require(values.size >= 20) { "native estimate is ${values.size} values, expected at least 20" }
    val mode = values[0].toInt()
    val available = mode in 2..3 && listOf(1, 2, 3, 5, 7, 8).all { values[it].isFinite() }
    val missingHeadingAccuracy = mode in 0..1 && headingAccuracyAvailable == false
    val status = if (missingHeadingAccuracy) "Heading accuracy unavailable" else when (mode) {
        1 -> "Waiting for heading"
        2 -> "GPS + IMU estimate"
        3 -> "Inertial estimate"
        4 -> "Sensor gap · realigning"
        5 -> "Estimate withheld"
        else -> "Waiting for GPS + IMU"
    }
    val source = if (mode == 3) "Native inertial" else "Native GPS + IMU"
    fun counter(index: Int) = if (values.size > index) values[index].takeIf(Double::isFinite)?.toInt() ?: 0 else 0
    val pose = if (available) Pose(GeoPoint(values[2], values[3]), values[5], values[6].takeIf(Double::isFinite),
        timestampNs = (values[1] * 1e9).toLong(), source = source, altitudeMeters = values[4].takeIf(Double::isFinite),
        mock = values[9].takeIf(Double::isFinite)?.let { it == 1.0 }, filterRadius95Meters = values[7]) else null
    return NativeEstimate(status, if (missingHeadingAccuracy) {
        "This phone does not report compass uncertainty. Live fusion cannot align safely; GPS tracking, recording and the simulated positioning demo remain available."
    } else when (mode) {
        1 -> "Needs a recent rotation-vector heading with reported accuracy. No vehicle-forward constraint is assumed."
        4 -> "An IMU gap exceeded 100 ms. Waiting for fresh GPS and heading rather than integrating across it."
        5 -> "The 95% radius passed 400 m, or there has been no fix for a very long time. GPS remains the fallback."
        3 -> "Dead reckoning: vehicle axes estimated from motion, with non-holonomic, zero-velocity, turn-rate and axle-vibration speed constraints. Along-track distance is held by the vibration line; heading drifts over a long blackout. No road matching."
        2 -> "Phone-frame RI-EKF fusing GPS with IMU. WGS84 / WMM2025. Vehicle axes and axle-vibration scale are calibrated while GPS is available."
        else -> "Needs synchronized accelerometer/gyro and GPS with a reported accuracy."
    }, pose, values[7].takeIf { available }, values[8].takeIf { available },
        values[10].toInt(), values[11].toInt(), values[12].toInt(), values[13].toInt(), values[14].toInt(), paired, dropped,
        zupts = counter(20), nhcs = counter(21), turnSpeedUpdates = counter(22),
        spectralUpdates = counter(24),
        spectralScale = if (values.size > 25) values[25].takeIf { it.isFinite() && it > 0 } else null)
}
