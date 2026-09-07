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
        if (timestamp - lastPublish >= 200_000_000L) {
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

    fun sensor(type: Int, timestamp: Long, values: FloatArray, accuracy: Int) {
        if (timestamp <= 0 || timestamp > SystemClock.elapsedRealtimeNanos() || values.any { !it.isFinite() }) return
        when (type) {
            Sensor.TYPE_ACCELEROMETER -> {
                val sample = values.take(3).map(Float::toDouble).toDoubleArray()
                compass.acceleration(timestamp, sample)
                synchronizer.acceleration(timestamp, sample)
            }
            Sensor.TYPE_GYROSCOPE -> {
                val sample = values.take(3).map(Float::toDouble).toDoubleArray()
                compass.gyroscope(timestamp, sample)
                synchronizer.gyroscope(timestamp, sample)
            }
            Sensor.TYPE_MAGNETIC_FIELD -> compass.magnetometer(timestamp, values.take(3).map(Float::toDouble).toDoubleArray(), accuracy)
            Sensor.TYPE_GAME_ROTATION_VECTOR -> {
                if (values.size < 3) return
                val matrix = FloatArray(9)
                SensorManager.getRotationMatrixFromVector(matrix, values)
                motion.rotation(timestamp, DoubleArray(9) { matrix[it].toDouble() })
                applyMotionAlignment(timestamp)
            }
            Sensor.TYPE_ROTATION_VECTOR -> {
                headingAccuracyAvailable = values.size >= 5 && values[4] >= 0
                if (!declination.isFinite() || values.size < 3) return
                val matrix = FloatArray(9)
                SensorManager.getRotationMatrixFromVector(matrix, values)
                val trueRotation = trueNorthRotation(DoubleArray(9) { matrix[it].toDouble() }, declination)
                val alignment = compass.evaluate(timestamp, trueRotation, values.getOrNull(4)?.toDouble(), accuracy) ?: return
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

    override fun close() = engine.close()
}

internal fun trueNorthRotation(magnetic: DoubleArray, declination: Double): DoubleArray {
    require(magnetic.size == 9 && magnetic.all(Double::isFinite) && declination.isFinite())
    val cosine = cos(declination)
    val sine = sin(declination)
    return DoubleArray(9) { index ->
        when (index / 3) {
            0 -> cosine * magnetic[index] + sine * magnetic[index + 3]
            1 -> -sine * magnetic[index - 3] + cosine * magnetic[index]
            else -> magnetic[index]
        }
    }
}

internal fun decodeNativeEstimate(values: DoubleArray, paired: Long = 0, dropped: Long = 0,
                                  headingAccuracyAvailable: Boolean? = null): NativeEstimate {
    require(values.size == 20)
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
    val pose = if (available) Pose(GeoPoint(values[2], values[3]), values[5], values[6].takeIf(Double::isFinite),
        timestampNs = (values[1] * 1e9).toLong(), source = source, altitudeMeters = values[4].takeIf(Double::isFinite),
        mock = values[9].takeIf(Double::isFinite)?.let { it == 1.0 }, filterRadius95Meters = values[7]) else null
    return NativeEstimate(status, if (missingHeadingAccuracy) {
        "This phone does not report compass uncertainty. Live fusion cannot align safely; GPS tracking, recording and the simulated positioning demo remain available."
    } else when (mode) {
        1 -> "Needs a recent rotation-vector heading with reported accuracy. No vehicle-forward constraint is assumed."
        4 -> "An IMU gap exceeded 100 ms. Waiting for fresh GPS and heading rather than integrating across it."
        5 -> "More than 10 s without an accepted fix, or a 95% radius above 150 m. GPS remains the fallback."
        2, 3 -> "Experimental phone-frame RI-EKF. WGS84 / WMM2025; no learned speed, road matching or mount constraints."
        else -> "Needs synchronized accelerometer/gyro and GPS with a reported accuracy."
    }, pose, values[7].takeIf { available }, values[8].takeIf { available },
        values[10].toInt(), values[11].toInt(), values[12].toInt(), values[13].toInt(), values[14].toInt(), paired, dropped)
}
