package com.setu.navigator.estimation

import kotlin.math.*

data class HeadingAlignment(val sigmaRadians: Double, val source: String)

class CompassAlignment {
    private data class Sample(val timestamp: Long, val values: DoubleArray, val accuracy: Int)
    private var acceleration: Sample? = null
    private var magnetic: Sample? = null
    private var gyro: Sample? = null
    private var reference: DoubleArray? = null
    private var stableSince = 0L
    private var previousRotation = 0L
    private var initialRotation: DoubleArray? = null
    var detail = "Get a GPS fix first; keep the phone still briefly to check its compass."
        private set

    fun reference(fieldMicrotesla: DoubleArray) {
        reference = fieldMicrotesla.takeIf { it.size == 3 && it.all(Double::isFinite) && norm(it) in 20.0..70.0 }?.copyOf()
    }

    fun acceleration(timestamp: Long, values: DoubleArray) { acceleration = sample(timestamp, values, 3) }
    fun gyroscope(timestamp: Long, values: DoubleArray) { gyro = sample(timestamp, values, 3) }
    fun magnetometer(timestamp: Long, values: DoubleArray, accuracy: Int) { magnetic = sample(timestamp, values, accuracy) }

    private fun sample(timestamp: Long, values: DoubleArray, accuracy: Int) =
        values.takeIf { timestamp > 0 && it.size == 3 && it.all(Double::isFinite) }?.let { Sample(timestamp, it.copyOf(), accuracy) }

    private fun waitFor(message: String): HeadingAlignment? {
        stableSince = 0
        initialRotation = null
        detail = message
        return null
    }

    fun evaluate(timestamp: Long, trueRotation: DoubleArray, reportedSigma: Double?, accuracy: Int): HeadingAlignment? {
        if (timestamp <= previousRotation || trueRotation.size != 9 || trueRotation.any { !it.isFinite() }) return null
        val gap = timestamp - previousRotation
        previousRotation = timestamp
        if (accuracy < 2) return waitFor("Compass calibration is low. Move away from metal and calibrate the phone compass.")
        if (reportedSigma != null && reportedSigma.isFinite() && reportedSigma >= 0) {
            if (reportedSigma > 0.6) return waitFor("The phone reports too much heading uncertainty. Recalibrate away from metal.")
            stableSince = 0
            initialRotation = null
            detail = "Using the phone's reported heading uncertainty."
            return HeadingAlignment(maxOf(0.15, reportedSigma), "Sensor-reported heading")
        }
        val expected = reference ?: return waitFor("Enable Location and obtain a fresh fix before sensor-only tracking.")
        val samples = listOf(acceleration, magnetic, gyro)
        if (samples.any { it == null || abs(timestamp - it.timestamp) > 100_000_000L }) {
            return waitFor("Waiting for fresh accelerometer, gyroscope and calibrated magnetometer samples.")
        }
        val accelerationSample = requireNotNull(acceleration)
        val magneticSample = requireNotNull(magnetic)
        val gyroSample = requireNotNull(gyro)
        if (magneticSample.accuracy < 2) return waitFor("Magnetic calibration is low. Move away from metal and calibrate the phone compass.")
        val worldMagnetic = rotate(trueRotation, magneticSample.values)
        val fieldRatio = norm(worldMagnetic) / norm(expected)
        val fieldAngle = acos((worldMagnetic.indices.sumOf { worldMagnetic[it] * expected[it] } / (norm(worldMagnetic) * norm(expected))).coerceIn(-1.0, 1.0))
        if (!fieldAngle.isFinite() || fieldRatio !in 0.75..1.25 || fieldAngle > Math.toRadians(15.0)) {
            return waitFor("Magnetic interference detected. Move away from metal or magnetic mounts.")
        }
        val worldAcceleration = rotate(trueRotation, accelerationSample.values)
        val gravityResidual = norm(doubleArrayOf(worldAcceleration[0], worldAcceleration[1], worldAcceleration[2] - 9.80665))
        if (gravityResidual > 0.45 || norm(gyroSample.values) > 0.12) {
            return waitFor("Keep the phone still for two seconds to check compass alignment.")
        }
        if (gap > 100_000_000L || initialRotation == null) {
            stableSince = timestamp
            initialRotation = trueRotation.copyOf()
        }
        val initial = requireNotNull(initialRotation)
        val rotationChange = acos(((trueRotation.indices.sumOf { trueRotation[it] * initial[it] } - 1) / 2).coerceIn(-1.0, 1.0))
        if (rotationChange > Math.toRadians(5.0)) return waitFor("Keep the phone still for two seconds to check compass alignment.")
        if (timestamp - stableSince < 2_000_000_000L) {
            detail = "Checking compass stability. Keep the phone still for two seconds."
            return null
        }
        val timingAngle = samples.maxOf { abs(timestamp - requireNotNull(it).timestamp) } / 1e9 * norm(gyroSample.values)
        val sigma = sqrt(Math.toRadians(30.0).pow(2) + fieldAngle.pow(2) + rotationChange.pow(2) + timingAngle.pow(2))
        if (sigma > 0.6) return waitFor("Compass checks are too uncertain. Recalibrate away from metal.")
        detail = "Compass-based alignment uses a conservative 30°+ model prior, not hardware-reported or field-verified accuracy."
        return HeadingAlignment(sigma, "Checked compass · estimated uncertainty")
    }

    private fun rotate(rotation: DoubleArray, vector: DoubleArray) = DoubleArray(3) { row ->
        (0..2).sumOf { column -> rotation[row * 3 + column] * vector[column] }
    }

    private fun norm(vector: DoubleArray) = sqrt(vector.sumOf { it * it })
}
