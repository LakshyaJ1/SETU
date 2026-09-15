package com.setu.navigator.estimation

import android.content.Context
import com.setu.navigator.data.GeoPoint
import com.setu.navigator.data.Pose
import kotlin.math.cos
import kotlin.math.sin
import kotlin.math.sqrt

internal data class DemoMotion(val elapsedMs: Long, val east: Double, val north: Double,
                               val heading: Double, val speed: Double,
                               val acceleration: Double, val turnRate: Double)

internal fun positioningDemoMotion(): List<DemoMotion> {
    data class Control(val seconds: Double, val speed: Double, val turn: Double)
    val controls = listOf(
        Control(0.0, 6.0, 0.0), Control(2.0, 6.0, 0.0),
        Control(3.0, 5.2, .4), Control(5.0, 4.5, .4),
        Control(6.0, 4.5, -.48), Control(8.0, 4.5, -.48),
        Control(9.0, 5.0, .5), Control(11.0, 5.0, .5),
        Control(12.0, 4.5, -.5), Control(14.0, 4.5, -.5),
        Control(15.0, 5.5, .35), Control(17.0, 5.5, .35),
        Control(18.0, 2.5, 0.0), Control(19.0, 0.0, 0.0),
        Control(20.0, 0.0, 0.0), Control(21.0, 3.0, 0.0),
        Control(22.0, 5.0, -.35), Control(24.0, 5.0, -.35),
    )
    val samples = ArrayList<DemoMotion>(2401)
    var segment = 0
    for (step in 0..2400) {
        val seconds = step / 100.0
        while (segment < controls.lastIndex - 1 && seconds > controls[segment + 1].seconds) segment++
        val from = controls[segment]
        val to = controls[segment + 1]
        val duration = to.seconds - from.seconds
        val fraction = ((seconds - from.seconds) / duration).coerceIn(0.0, 1.0)
        val blend = fraction * fraction * (3 - 2 * fraction)
        val speed = from.speed + blend * (to.speed - from.speed)
        val acceleration = 6 * fraction * (1 - fraction) / duration * (to.speed - from.speed)
        val turn = from.turn + blend * (to.turn - from.turn)
        val previous = samples.lastOrNull()
        val heading = if (previous == null) 0.0 else previous.heading + .005 * (previous.turnRate + turn)
        val east = if (previous == null) 0.0 else previous.east +
            .005 * (previous.speed * cos(previous.heading) + speed * cos(heading))
        val north = if (previous == null) 0.0 else previous.north +
            .005 * (previous.speed * sin(previous.heading) + speed * sin(heading))
        samples.add(DemoMotion(step * 10L, east, north, heading, speed, acceleration, turn))
    }
    return samples
}

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
    val motion = positioningDemoMotion()
    val startNs = 1_000_000_000L
    val latitude = Math.toRadians(origin.latitude)
    val eccentricitySquared = 6.69437999014e-3
    val denominator = 1 - eccentricitySquared * sin(latitude) * sin(latitude)
    val normalRadius = 6378137.0 / sqrt(denominator)
    val meridianRadius = normalRadius * (1 - eccentricitySquared) / denominator
    fun reference(sample: DemoMotion): GeoPoint {
        return GeoPoint(origin.latitude + Math.toDegrees(sample.north / meridianRadius),
            origin.longitude + Math.toDegrees(sample.east / (normalRadius * cos(latitude))))
    }
    fun gps(sample: DemoMotion) = Pose(reference(sample), speedMps = sample.speed,
        bearing = (90.0 - Math.toDegrees(sample.heading) + 360.0) % 360.0, accuracyMeters = 3.0,
        timestampNs = startNs + sample.elapsedMs * 1_000_000, altitudeMeters = 0.0,
        verticalAccuracyMeters = 8.0, speedAccuracyMps = 0.2, bearingAccuracyDegrees = 1.0,
        source = "Simulated GPS", mock = true)
    fun acceleration(sample: DemoMotion) =
        doubleArrayOf(sample.acceleration + .012, sample.speed * sample.turnRate - .008, 9.80665)
    fun angularRate(sample: DemoMotion) = doubleArrayOf(0.0, 0.0, sample.turnRate + .0001)
    val frames = mutableListOf<PositioningFrame>()
    NativeEngine(NativeEngine.magneticData(context)).use { engine ->
        engine.attitude(startNs, doubleArrayOf(1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0), 0.15)
        engine.imu(startNs, acceleration(motion.first()), angularRate(motion.first()))
        var lastGps = gps(motion.first())
        check(engine.gnss(lastGps) == 1) { "The positioning demo could not align its native engine." }
        for ((step, sample) in motion.withIndex()) {
            if (step % 100 == 0) checkpoint()
            val elapsedMs = sample.elapsedMs
            val gpsAvailable = elapsedMs !in 6000L until 14000L
            if (step > 0) {
                engine.imu(startNs + elapsedMs * 1_000_000, acceleration(sample), angularRate(sample))
                if (gpsAvailable && step % 50 == 0) {
                    lastGps = gps(sample)
                    engine.gnss(lastGps)
                }
            }
            if (step % 10 == 0) {
                val estimate = decodeNativeEstimate(engine.snapshot(), paired = step.toLong())
                frames.add(PositioningFrame(elapsedMs, reference(sample), lastGps, gpsAvailable,
                    estimate.copy(pose = estimate.pose?.copy(source = "Simulated sensor fusion"))))
            }
        }
    }
    check(frames.all { it.estimate.pose != null }) { "The positioning demo lost alignment. Open diagnostics and retry." }
    return PositioningDemo(frames)
}
