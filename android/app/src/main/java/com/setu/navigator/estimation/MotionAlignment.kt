package com.setu.navigator.estimation

import com.setu.navigator.data.Pose
import java.util.ArrayDeque
import kotlin.math.*

class MotionAlignment {
    data class Alignment(val timestamp: Long, val rotation: DoubleArray, val sigmaRadians: Double)
    private data class Frame(val timestamp: Long, val east: Double, val north: Double)
    private data class Fix(val pose: Pose, val frame: Frame, val velocity: DoubleArray, val sigma: Double)
    private data class Check(val yaw: Double, val variance: Double, val direction: Double, val timestamp: Long)
    private val frames = ArrayDeque<Frame>()
    private val checks = ArrayDeque<Check>()
    private var rotation: DoubleArray? = null
    private var rotationNs = 0L
    private var angularSpeed = 0.0
    private var previousAcceleration: DoubleArray? = null
    private var base: Fix? = null
    private var pendingGps: Pose? = null
    private var alignedYaw: Double? = null
    private var alignedSigma = 0.0
    private var alignedNs = 0L
    var detail = "With the phone fixed in place, keep GPS on during normal acceleration, braking and turns."
        private set

    fun rotation(timestamp: Long, matrix: DoubleArray) {
        if (timestamp <= rotationNs || matrix.size != 9 || matrix.any { !it.isFinite() }) return
        val previous = rotation
        if (rotationNs != 0L && previous != null) {
            val interval = (timestamp - rotationNs) / 1e9
            val change = acos(((matrix.indices.sumOf { matrix[it] * previous[it] } - 1) / 2).coerceIn(-1.0, 1.0))
            if (interval > 0.1 || change > angularSpeed * interval + 0.08) reset()
        }
        rotation = matrix.copyOf()
        rotationNs = timestamp
    }

    fun imu(timestamp: Long, acceleration: DoubleArray, gyro: DoubleArray) {
        val matrix = rotation ?: return
        if (acceleration.size != 3 || acceleration.any { !it.isFinite() } || gyro.size != 3 || gyro.any { !it.isFinite() } || abs(timestamp - rotationNs) > 100_000_000L) return
        angularSpeed = sqrt(gyro.sumOf { it * it })
        val current = DoubleArray(2) { row -> (0..2).sumOf { matrix[row * 3 + it] * acceleration[it] } }
        val previous = frames.peekLast()
        if (previous != null && timestamp <= previous.timestamp) return
        if (previous != null && timestamp - previous.timestamp > 100_000_000L) reset()
        val last = frames.peekLast()
        val duration = if (last == null) 0.0 else (timestamp - last.timestamp) / 1e9
        val older = previousAcceleration ?: current
        frames.addLast(Frame(timestamp, (last?.east ?: 0.0) + (older[0] + current[0]) * 0.5 * duration,
            (last?.north ?: 0.0) + (older[1] + current[1]) * 0.5 * duration))
        previousAcceleration = current
        while (frames.isNotEmpty() && timestamp - frames.first.timestamp > 12_000_000_000L) frames.removeFirst()
        pendingGps?.takeIf { it.timestampNs <= timestamp }?.let { pendingGps = null; observe(it) }
    }

    fun gnss(pose: Pose) {
        if (pose.timestampNs <= 0 || pose.timestampNs <= (base?.pose?.timestampNs ?: 0)) return
        if (frames.peekLast()?.timestamp?.let { pose.timestampNs <= it } == true) observe(pose)
        else pendingGps = pose
    }

    private fun observe(pose: Pose) {
        val speed = pose.speedMps?.takeIf { it.isFinite() && it in 0.0..70.0 } ?: return
        val speedSigma = pose.speedAccuracyMps?.takeIf { it.isFinite() && it in 0.0..1.0 } ?: return
        val stopped = speed + 2 * speedSigma <= 0.8
        val course = if (stopped) 0.0 else pose.bearing?.takeIf { it.isFinite() && it in 0.0..<360.0 } ?: return
        val courseSigma = if (stopped) 0.0 else pose.bearingAccuracyDegrees?.takeIf { it.isFinite() && it in 0.0..8.0 } ?: return
        val frame = frameAt(pose.timestampNs) ?: return
        val bearing = Math.toRadians(course)
        val velocity = if (stopped) doubleArrayOf(0.0, 0.0) else doubleArrayOf(speed * sin(bearing), speed * cos(bearing))
        val sigma = if (stopped) maxOf(0.2, speed + 2 * speedSigma) else hypot(maxOf(0.1, speedSigma), speed * Math.toRadians(courseSigma))
        val fix = Fix(pose, frame, velocity, sigma)
        val previous = base
        if (previous == null) { base = fix; return }
        val duration = (pose.timestampNs - previous.pose.timestampNs) / 1e9
        if (duration < 2.0) return
        base = fix
        if (duration > 4.0 || pose.mock != previous.pose.mock) { checks.clear(); return }
        val inertialEast = frame.east - previous.frame.east
        val inertialNorth = frame.north - previous.frame.north
        val gpsEast = velocity[0] - previous.velocity[0]
        val gpsNorth = velocity[1] - previous.velocity[1]
        val inertialChange = hypot(inertialEast, inertialNorth)
        val gpsChange = hypot(gpsEast, gpsNorth)
        if (inertialChange < 2.0 || gpsChange < 2.0) {
            detail = "GPS motion alignment needs changes of velocity; a stationary fix or constant speed is not enough."
            return
        }
        val variance = (hypot(sigma, previous.sigma) / gpsChange).pow(2) + (0.25 * duration / inertialChange).pow(2)
        if (inertialChange / gpsChange !in 0.65..1.35 || variance > 0.16) {
            checks.clear()
            detail = "GPS and phone motion disagree. Keep the phone fixed and GPS on."
            return
        }
        val yaw = atan2(inertialEast * gpsNorth - inertialNorth * gpsEast, inertialEast * gpsEast + inertialNorth * gpsNorth)
        if (checks.any { abs(wrapped(yaw - it.yaw)) > Math.toRadians(20.0) }) {
            checks.clear()
            alignedYaw = null
        }
        while (checks.isNotEmpty() && pose.timestampNs - checks.first.timestamp > 20_000_000_000L) checks.removeFirst()
        checks.addLast(Check(yaw, variance, atan2(inertialNorth, inertialEast), pose.timestampNs))
        while (checks.size > 3) checks.removeFirst()
        if (checks.size < 3 || checks.none { abs(wrapped(it.direction - checks.first.direction)) >= Math.toRadians(35.0) }) {
            detail = "GPS motion alignment: ${checks.size}/3 checks; needs acceleration/braking changes or turns."
            return
        }
        val weight = checks.sumOf { 1.0 / it.variance.coerceAtLeast(0.001) }
        val mean = atan2(checks.sumOf { sin(it.yaw) / it.variance.coerceAtLeast(0.001) },
            checks.sumOf { cos(it.yaw) / it.variance.coerceAtLeast(0.001) })
        val scatter = checks.sumOf { wrapped(it.yaw - mean).pow(2) } / checks.size
        val uncertainty = sqrt(Math.toRadians(15.0).pow(2) + 1.0 / weight + scatter)
        if (uncertainty > 0.5) return
        alignedYaw = mean
        alignedSigma = uncertainty
        alignedNs = pose.timestampNs
        detail = "GPS motion alignment passed its consistency checks; uncertainty is an experimental model estimate."
    }

    fun alignment(timestamp: Long): Alignment? {
        val yaw = alignedYaw ?: return null
        val matrix = rotation ?: return null
        if (timestamp < alignedNs || abs(timestamp - rotationNs) > 100_000_000L) return null
        val sigma = hypot(alignedSigma, (timestamp - alignedNs) / 1e9 * 0.003)
        if (sigma > 0.6) return null
        val cosine = cos(yaw)
        val sine = sin(yaw)
        val aligned = DoubleArray(9) { index -> when (index / 3) {
            0 -> cosine * matrix[index] - sine * matrix[index + 3]
            1 -> sine * matrix[index - 3] + cosine * matrix[index]
            else -> matrix[index]
        } }
        return Alignment(rotationNs, aligned, sigma)
    }

    private fun frameAt(timestamp: Long): Frame? {
        var previous: Frame? = null
        for (frame in frames) {
            if (frame.timestamp == timestamp) return frame
            if (frame.timestamp > timestamp) {
                val before = previous ?: return null
                if (frame.timestamp - before.timestamp > 100_000_000L) return null
                val fraction = (timestamp - before.timestamp).toDouble() / (frame.timestamp - before.timestamp)
                return Frame(timestamp, before.east + fraction * (frame.east - before.east), before.north + fraction * (frame.north - before.north))
            }
            previous = frame
        }
        return null
    }

    private fun reset() {
        frames.clear(); checks.clear(); previousAcceleration = null; base = null; pendingGps = null; alignedYaw = null
        detail = "GPS motion alignment needs a fresh continuous sensor window. Keep GPS on."
    }
    private fun wrapped(angle: Double) = atan2(sin(angle), cos(angle))
}
