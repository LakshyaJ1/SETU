package com.setu.navigator.estimation

import com.setu.navigator.data.GeoPoint
import com.setu.navigator.data.Pose
import kotlin.math.*

class WalkingTracker(private val stepLengthMeters: Double) {
    private data class Heading(val timestamp: Long, val radians: Double)
    private var gps: Pose? = null
    private var point: GeoPoint? = null
    private var game: DoubleArray? = null
    private var gameNs = 0L
    private var headingRadians: Double? = null
    private var headingSigma = Double.NaN
    private var lastImuNs = 0L
    private var angleBudget = 0.0
    private var lastStepNs = 0L
    private var lastSeenStepNs = 0L
    private var lastBatchNs = 0L
    private var batchSize = 0
    private val recentSteps = ArrayDeque<Long>()
    private var distanceSinceGps = 0.0
    private var acceptedGps = 0
    private var usedMockFix = false
    private val headings = ArrayDeque<Heading>()
    private val intervals = ArrayDeque<Double>()
    var steps = 0L
        private set
    var rejectedSteps = 0L
        private set
    private var detail = "Keep GPS on. Hold the phone still, then keep its top pointing along your path."

    init { require(stepLengthMeters.isFinite() && stepLengthMeters in 0.3..1.2) }

    fun gnss(observation: Pose) {
        if (observation.timestampNs <= maxOf(gps?.timestampNs ?: 0, lastStepNs) || observation.accuracyMeters?.let { it in 0.0..20.0 } != true) return
        gps = observation
        usedMockFix = usedMockFix || observation.mock == true
        point = observation.point
        distanceSinceGps = 0.0
        acceptedGps++
    }

    fun imu(timestamp: Long, gyro: DoubleArray) {
        if (timestamp <= lastImuNs) return
        val interval = (timestamp - lastImuNs) / 1e9
        if (gyro.size != 3 || gyro.any { !it.isFinite() || abs(it) > 35.0 } || (lastImuNs != 0L && interval > .1)) {
            realign("Sensor discontinuity. Stop briefly with GPS on to realign.")
        } else if (lastImuNs != 0L) angleBudget += sqrt(gyro.sumOf { it * it }) * interval
        lastImuNs = timestamp
    }

    fun rotation(timestamp: Long, matrix: DoubleArray) {
        if (timestamp <= gameNs || !validRotation(matrix)) return
        val previous = game
        if (previous != null) {
            val delta = DoubleArray(9) { index ->
                (0..2).sumOf { axis -> matrix[(index / 3) * 3 + axis] * previous[(index % 3) * 3 + axis] }
            }
            val trace = delta[0] + delta[4] + delta[8]
            val change = acos(((trace - 1) / 2).coerceIn(-1.0, 1.0))
            if (timestamp - gameNs > 100_000_000L || change > angleBudget + .15) {
                realign("Orientation jumped without matching gyro motion. Keep GPS on and hold still to realign.")
            } else {
                val yaw = 2 * atan2(delta[3] - delta[1], 1 + trace)
                headingRadians = headingRadians?.let { atan2(sin(it - yaw), cos(it - yaw)) }
            }
        }
        game = matrix.copyOf()
        gameNs = timestamp
        angleBudget = 0.0
        updateHeading(timestamp)
    }

    fun align(timestamp: Long, trueRotation: DoubleArray, sigma: Double) {
        if (game == null) return
        if (abs(timestamp - gameNs) > 100_000_000L || !validRotation(trueRotation) || !sigma.isFinite() || sigma !in 0.0..0.6) return
        if (headingRadians != null) return
        val horizontalTop = hypot(trueRotation[1], trueRotation[4])
        headingRadians = if (horizontalTop >= .5) atan2(trueRotation[1], trueRotation[4])
            else atan2(-trueRotation[2], -trueRotation[5])
        headingSigma = maxOf(sigma, Math.toRadians(10.0))
        updateHeading(gameNs)
        detail = "Step-based estimate. Keep the phone pointed along travel; calibrate step length over a measured walk."
    }

    private fun updateHeading(timestamp: Long) {
        val heading = headingRadians ?: return
        if (headings.lastOrNull()?.timestamp == timestamp) headings.removeLast()
        headings.addLast(Heading(timestamp, heading))
        while (headings.isNotEmpty() && timestamp - headings.first().timestamp > 3_000_000_000L) headings.removeFirst()
    }

    fun step(timestamp: Long): Boolean {
        if (timestamp <= lastSeenStepNs || lastImuNs - timestamp > 2_000_000_000L) { rejectedSteps++; return false }
        lastSeenStepNs = timestamp
        val observation = gps
        if (observation == null || timestamp <= observation.timestampNs || timestamp - observation.timestampNs > 120_000_000_000L || headingRadians == null) {
            rejectedSteps++; return false
        }
        val heading = headings.lastOrNull { it.timestamp <= timestamp }
        if (heading == null || timestamp - heading.timestamp > 100_000_000L) { rejectedSteps++; return false }
        while (recentSteps.isNotEmpty() && timestamp - recentSteps.first() >= 4_000_000_000L) recentSteps.removeFirst()
        if (recentSteps.size >= 16) {
            rejectedSteps++
            realign("Step event rate is implausible for walking. Get fresh GPS and check the step detector.")
            return false
        }
        val current = point ?: return false
        val latitude = current.latitude + Math.toDegrees(stepLengthMeters * cos(heading.radians) / 6378137.0)
        val cosine = cos(Math.toRadians(current.latitude))
        if (abs(cosine) < .01) { rejectedSteps++; return false }
        val longitude = current.longitude + Math.toDegrees(stepLengthMeters * sin(heading.radians) / (6378137.0 * cosine))
        if (latitude !in -90.0..90.0 || longitude !in -180.0..180.0) { rejectedSteps++; return false }
        point = GeoPoint(latitude, longitude)
        if (lastStepNs == 0L || timestamp - lastStepNs >= 250_000_000L) {
            val interval = (timestamp - lastBatchNs) / 1e9
            if (lastBatchNs != 0L && interval in .25..3.0) intervals.addLast(interval) else intervals.clear()
            while (intervals.size > 4) intervals.removeFirst()
            lastBatchNs = timestamp
            batchSize = 0
        }
        batchSize++
        recentSteps.addLast(timestamp)
        lastStepNs = timestamp
        distanceSinceGps += stepLengthMeters
        steps++
        return true
    }

    fun estimate(timestamp: Long, paired: Long = 0, drops: Long = 0): NativeEstimate {
        val observation = gps
        val age = observation?.let { (timestamp - it.timestampNs) / 1e9 }
        val radius = observation?.accuracyMeters?.let {
            2 * it + distanceSinceGps * (0.2 + 2 * sin(headingSigma.coerceAtMost(.6))) + maxOf(0.0, age ?: 0.0) * .05
        }
        val heading = headings.lastOrNull { it.timestamp <= timestamp }
        val ready = observation != null && point != null && heading != null && age != null && age in 0.0..120.0 &&
            timestamp - heading.timestamp in 0..100_000_000L && radius != null && radius.isFinite() && radius <= 75.0
        val interval = intervals.takeIf { it.isNotEmpty() }?.sorted()?.let { it[it.size / 2] }
        val stopDelay = maxOf(1.5, (interval ?: 0.0) * 1.5).coerceAtMost(4.5)
        val speed = if (lastStepNs == 0L || timestamp - lastStepNs > (stopDelay * 1e9).toLong()) 0.0
            else if (timestamp < lastStepNs) null
            else interval?.let { batchSize / it }?.takeIf { it <= 4.0 }?.let { stepLengthMeters * it }
        val pose = if (ready) Pose(checkNotNull(point), speed,
            heading?.radians?.let { (Math.toDegrees(it) + 360) % 360 },
            timestampNs = timestamp, source = "Walking step estimate", mock = if (usedMockFix) true else observation.mock, filterRadius95Meters = radius) else null
        return NativeEstimate(status = when {
            ready -> "Walking step estimate"
            observation == null -> "Walking needs a GPS start"
            age != null && (age > 120 || (radius?.let { it > 75 } == true)) -> "Estimate withheld"
            else -> "Walking needs heading alignment"
        }, detail = if (ready) "$detail Some phones report steps in batches; speed may lag and settle within 1.5–4.5 seconds."
            else if (observation == null) "$detail Get a GPS fix within 20 m reported accuracy before the walking trial."
            else "${detail} Re-enable GPS if the estimate has expired.", pose = pose,
            radius95Meters = radius?.takeIf { ready }, gpsAgeSeconds = age, accepted = acceptedGps,
            pairedSamples = paired, pairingDrops = drops, headingSource = if (headingRadians != null) "Checked compass + relative yaw" else null,
            walkingSteps = steps, rejectedSteps = rejectedSteps)
    }

    private fun realign(reason: String) {
        headingRadians = null; headings.clear(); intervals.clear(); angleBudget = 0.0
        gps = null; point = null; lastStepNs = 0L; distanceSinceGps = 0.0
        lastBatchNs = 0L; batchSize = 0; recentSteps.clear()
        usedMockFix = false
        detail = reason
    }

    private fun validRotation(matrix: DoubleArray): Boolean = matrix.size == 9 && matrix.all(Double::isFinite) &&
        (0..2).all { row -> abs((0..2).sumOf { matrix[row * 3 + it].pow(2) } - 1) < 1e-3 } &&
        (0..2).all { row -> (row + 1..2).all { other -> abs((0..2).sumOf { matrix[row * 3 + it] * matrix[other * 3 + it] }) < 1e-3 } } &&
        abs(matrix[0] * (matrix[4] * matrix[8] - matrix[5] * matrix[7]) -
            matrix[1] * (matrix[3] * matrix[8] - matrix[5] * matrix[6]) +
            matrix[2] * (matrix[3] * matrix[7] - matrix[4] * matrix[6]) - 1) < 1e-3
}
