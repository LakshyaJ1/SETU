package com.setu.navigator.estimation

import android.content.Context
import android.hardware.Sensor
import android.hardware.SensorManager
import android.os.SystemClock
import com.setu.navigator.data.GeoPoint
import com.setu.navigator.data.Pose
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
) {
    fun currentPose(nowNs: Long): Pose? = pose?.takeIf { nowNs >= it.timestampNs && nowNs - it.timestampNs <= 300_000_000L }
}

fun navigationPose(gps: Pose?, estimate: NativeEstimate, enabled: Boolean, nowNs: Long): Pose? =
    if (enabled) estimate.currentPose(nowNs) ?: gps else gps

class LiveEstimator(context: Context, private val publish: (NativeEstimate) -> Unit,
                    private val record: (JSONObject) -> Unit) : AutoCloseable {
    private val engine = NativeEngine(NativeEngine.magneticData(context))
    private var declination = Double.NaN
    private var pairedSamples = 0L
    private var lastPublish = 0L
    private val synchronizer: ImuSynchronizer = ImuSynchronizer { timestamp, acceleration, gyro ->
        engine.imu(timestamp, acceleration, gyro)
        pairedSamples++
        if (timestamp - lastPublish >= 200_000_000L) {
            lastPublish = timestamp
            val estimate = decodeNativeEstimate(engine.snapshot(), pairedSamples, synchronizerDrops())
            publish(estimate)
            estimate.pose?.let { pose ->
                record(JSONObject().put("type", "native_pose").put("tNs", pose.timestampNs)
                    .put("latitude", pose.point.latitude).put("longitude", pose.point.longitude)
                    .put("speedMps", pose.speedMps).put("radius95Meters", estimate.radius95Meters)
                    .put("gpsAgeSeconds", estimate.gpsAgeSeconds).put("status", estimate.status)
                    .put("mock", pose.mock ?: JSONObject.NULL).put("experimental", true))
            }
        }
    }

    private fun synchronizerDrops(): Long = synchronizer.rejected

    fun sensor(type: Int, timestamp: Long, values: FloatArray, accuracy: Int) {
        if (timestamp <= 0 || timestamp > SystemClock.elapsedRealtimeNanos() || values.any { !it.isFinite() }) return
        when (type) {
            Sensor.TYPE_ACCELEROMETER -> synchronizer.acceleration(timestamp, values.take(3).map(Float::toDouble).toDoubleArray())
            Sensor.TYPE_GYROSCOPE -> synchronizer.gyroscope(timestamp, values.take(3).map(Float::toDouble).toDoubleArray())
            Sensor.TYPE_ROTATION_VECTOR -> {
                if (!declination.isFinite() || values.size < 5 || values[4] < 0 || accuracy < SensorManager.SENSOR_STATUS_ACCURACY_MEDIUM) return
                val matrix = FloatArray(9)
                SensorManager.getRotationMatrixFromVector(matrix, values)
                engine.attitude(timestamp, trueNorthRotation(DoubleArray(9) { matrix[it].toDouble() }, declination),
                    maxOf(0.15, values[4].toDouble()))
            }
        }
    }

    fun gnss(pose: Pose, wallTimeMs: Long) {
        val calendar = Calendar.getInstance(TimeZone.getTimeZone("UTC")).apply { timeInMillis = wallTimeMs }
        val year = calendar.get(Calendar.YEAR) + (calendar.get(Calendar.DAY_OF_YEAR) - 1).toDouble() / calendar.getActualMaximum(Calendar.DAY_OF_YEAR)
        declination = engine.declination(year, pose.point, pose.altitudeMeters ?: 0.0)
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

internal fun decodeNativeEstimate(values: DoubleArray, paired: Long = 0, dropped: Long = 0): NativeEstimate {
    require(values.size == 20)
    val mode = values[0].toInt()
    val available = mode in 2..3 && listOf(1, 2, 3, 5, 7, 8).all { values[it].isFinite() }
    val status = when (mode) {
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
    return NativeEstimate(status, when (mode) {
        1 -> "Needs a recent rotation-vector heading with reported accuracy. No vehicle-forward constraint is assumed."
        4 -> "An IMU gap exceeded 100 ms. Waiting for fresh GPS and heading rather than integrating across it."
        5 -> "More than 10 s without an accepted fix, or a 95% radius above 150 m. GPS remains the fallback."
        2, 3 -> "Experimental phone-frame RI-EKF. WGS84 / WMM2025; no learned speed, road matching or mount constraints."
        else -> "Needs synchronized accelerometer/gyro and GPS with a reported accuracy."
    }, pose, values[7].takeIf { available }, values[8].takeIf { available },
        values[10].toInt(), values[11].toInt(), values[12].toInt(), values[13].toInt(), values[14].toInt(), paired, dropped)
}
