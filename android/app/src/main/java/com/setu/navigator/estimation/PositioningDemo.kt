package com.setu.navigator.estimation

import android.content.Context
import com.setu.navigator.data.GeoPoint
import com.setu.navigator.data.Pose
import kotlin.math.cos
import kotlin.math.sin
import kotlin.math.sqrt

data class PositioningFrame(
    val elapsedMs: Long,
    val reference: GeoPoint,
    val lastGps: Pose,
    val gpsAvailable: Boolean,
    val estimate: NativeEstimate,
)

data class PositioningDemo(val frames: List<PositioningFrame>) {
    val durationMs get() = frames.last().elapsedMs
    fun frameAt(elapsedMs: Long) = frames[(elapsedMs / 100).toInt().coerceIn(frames.indices)]
    fun trailAt(elapsedMs: Long) = frames.take((elapsedMs / 100).toInt() + 1).mapNotNull { it.estimate.pose }
}

fun buildPositioningDemo(context: Context, origin: GeoPoint, checkpoint: () -> Unit = {}): PositioningDemo {
    val speed = 6.0
    val turnRate = 0.025
    val startNs = 1_000_000_000L
    val latitude = Math.toRadians(origin.latitude)
    val eccentricitySquared = 6.69437999014e-3
    val denominator = 1 - eccentricitySquared * sin(latitude) * sin(latitude)
    val normalRadius = 6378137.0 / sqrt(denominator)
    val meridianRadius = normalRadius * (1 - eccentricitySquared) / denominator
    fun reference(seconds: Double): GeoPoint {
        val east = speed / turnRate * sin(turnRate * seconds)
        val north = speed / turnRate * (1 - cos(turnRate * seconds))
        return GeoPoint(origin.latitude + Math.toDegrees(north / meridianRadius),
            origin.longitude + Math.toDegrees(east / (normalRadius * cos(latitude))))
    }
    fun gps(seconds: Double) = Pose(reference(seconds), speedMps = speed,
        bearing = 90.0 - Math.toDegrees(turnRate * seconds), accuracyMeters = 3.0,
        timestampNs = startNs + (seconds * 1e9).toLong(), altitudeMeters = 0.0,
        verticalAccuracyMeters = 8.0, speedAccuracyMps = 0.2, bearingAccuracyDegrees = 1.0,
        source = "Simulated GPS", mock = true)
    val acceleration = doubleArrayOf(0.012, speed * turnRate - 0.008, 9.80665)
    val angularRate = doubleArrayOf(0.0, 0.0, turnRate + 0.0001)
    val frames = mutableListOf<PositioningFrame>()
    NativeEngine(NativeEngine.magneticData(context)).use { engine ->
        engine.attitude(startNs, doubleArrayOf(1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0), 0.15)
        engine.imu(startNs, acceleration, angularRate)
        var lastGps = gps(0.0)
        check(engine.gnss(lastGps) == 1) { "The positioning demo could not align its native engine." }
        for (step in 0..2400) {
            if (step % 100 == 0) checkpoint()
            val elapsedMs = step * 10L
            val seconds = elapsedMs / 1000.0
            val gpsAvailable = elapsedMs !in 6000L until 14000L
            if (step > 0) {
                engine.imu(startNs + elapsedMs * 1_000_000, acceleration, angularRate)
                if (gpsAvailable && step % 50 == 0) {
                    lastGps = gps(seconds)
                    engine.gnss(lastGps)
                }
            }
            if (step % 10 == 0) {
                val estimate = decodeNativeEstimate(engine.snapshot(), paired = step.toLong())
                frames.add(PositioningFrame(elapsedMs, reference(seconds), lastGps, gpsAvailable,
                    estimate.copy(pose = estimate.pose?.copy(source = "Simulated sensor fusion"))))
            }
        }
    }
    check(frames.all { it.estimate.pose != null }) { "The positioning demo lost alignment. Open diagnostics and retry." }
    return PositioningDemo(frames)
}
