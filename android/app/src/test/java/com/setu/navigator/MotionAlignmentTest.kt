package com.setu.navigator

import com.setu.navigator.data.GeoPoint
import com.setu.navigator.data.Pose
import com.setu.navigator.estimation.MotionAlignment
import org.junit.Assert.*
import org.junit.Test
import kotlin.math.*

class MotionAlignmentTest {
    private val identity = doubleArrayOf(1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0)

    private fun exercise(movement: Boolean = true, sendGps: Boolean = true, lateGps: Boolean = false,
                         pulse: Boolean = false, jump: Boolean = false, courseSigma: Double = 1.0,
                         durationSeconds: Int = 14, accelerationScale: Double = 1.0,
                         eastBias: Double = 0.0, constantGps: Boolean = false,
                         changeOriginAtEnd: Boolean = false): MotionAlignment.Alignment? {
        val alignment = MotionAlignment()
        val yaw = Math.toRadians(70.0)
        var eastSpeed = 8.0
        var northSpeed = 2.0
        var previousEast = 0.0
        var previousNorth = 0.0
        var delayed: Pose? = null
        for (step in 0..durationSeconds * 100) {
            val timestamp = 1_000_000_000L + step * 10_000_000L
            val phase = step / 200 % 4
            val east = accelerationScale * if (!movement) 0.0 else when (phase) { 0 -> 1.8; 2 -> -1.8; else -> 0.0 }
            val north = accelerationScale * if (!movement) 0.0 else when (phase) { 1 -> 1.8; 3 -> -1.8; else -> 0.0 }
            if (step > 0) {
                eastSpeed += (previousEast + east) * 0.005 * cos(yaw) - (previousNorth + north) * 0.005 * sin(yaw)
                northSpeed += (previousEast + east) * 0.005 * sin(yaw) + (previousNorth + north) * 0.005 * cos(yaw)
            }
            previousEast = east; previousNorth = north
            alignment.rotation(timestamp, identity)
            alignment.imu(timestamp, doubleArrayOf(east + eastBias, north, 9.80665), doubleArrayOf(0.0, 0.0, 0.0))
            if (lateGps && step % 100 == 20) { delayed?.let(alignment::gnss); delayed = null }
            if (sendGps && step % 100 == 0) {
                val pose = Pose(GeoPoint(28.68, 77.28), if (constantGps) 5.0 else hypot(eastSpeed, northSpeed),
                    if (constantGps) 0.0 else (Math.toDegrees(atan2(eastSpeed, northSpeed)) + 360) % 360,
                    accuracyMeters = 3.0, timestampNs = timestamp, speedAccuracyMps = 0.05,
                    bearingAccuracyDegrees = courseSigma, mock = !(changeOriginAtEnd && step == durationSeconds * 100))
                if (lateGps) delayed = pose else alignment.gnss(pose)
            }
        }
        val end = 1_000_000_000L + durationSeconds * 1_000_000_000L
        if (pulse || jump) {
            repeat(4) { index ->
                alignment.imu(end + 5_000_000L + index * 5_000_000L, doubleArrayOf(0.0, 0.0, 9.80665),
                    doubleArrayOf(0.0, 0.0, if (pulse && index < 2) 20.0 else 0.0))
            }
            val angle = .2
            alignment.rotation(end + 20_000_000L, doubleArrayOf(cos(angle), -sin(angle), 0.0,
                sin(angle), cos(angle), 0.0, 0.0, 0.0, 1.0))
        }
        return alignment.alignment(if (pulse || jump) end + 20_000_000L else end)
    }

    @Test
    fun gpsAndChangingMotionAlignTheRelativeFrameWithoutAnyMagnetometer() {
        val result = requireNotNull(exercise())
        assertEquals(70.0, Math.toDegrees(atan2(result.rotation[3], result.rotation[0])), 1.0)
        assertTrue(result.sigmaRadians in Math.toRadians(15.0)..0.5)
    }

    @Test
    fun delayedGpsUsesTheMatchingSensorInterval() {
        val result = requireNotNull(exercise(lateGps = true))
        assertEquals(70.0, Math.toDegrees(atan2(result.rotation[3], result.rotation[0])), 1.0)
    }

    @Test
    fun constantSpeedCannotInventAnAbsoluteHeading() { assertNull(exercise(movement = false)) }

    @Test
    fun noGpsCannotCalibrateAnAbsoluteHeading() { assertNull(exercise(sendGps = false)) }

    @Test fun aBriefGyroPulseIsNotAnUnexplainedRotationJump() {
        assertNotNull(exercise(pulse = true))
        assertNull(exercise(jump = true))
    }

    @Test fun highlyUncertainGpsCoursesDoNotInitializeHeading() {
        assertNull(exercise(courseSigma = 90.0))
    }

    @Test fun poolsGentleMotionAndEstimatesConstantAccelerationBias() {
        val result = requireNotNull(exercise(durationSeconds = 80, accelerationScale = .25, eastBias = .12))
        assertEquals(70.0, Math.toDegrees(atan2(result.rotation[3], result.rotation[0])), 1.0)
        assertTrue(result.sigmaRadians in Math.toRadians(15.0)..0.5)
    }

    @Test fun pooledMotionDoesNotInventHeadingWithoutGpsExcitation() {
        assertNull(exercise(durationSeconds = 80, accelerationScale = .25, eastBias = .12, constantGps = true))
        assertNull(exercise(durationSeconds = 80, accelerationScale = .25, eastBias = .6))
    }

    @Test fun pooledMotionCannotSurviveAnUnexplainedFrameJumpOrOriginChange() {
        assertNull(exercise(durationSeconds = 80, accelerationScale = .25, eastBias = .12, jump = true))
        assertNull(exercise(durationSeconds = 80, accelerationScale = .25, eastBias = .12, changeOriginAtEnd = true))
    }
}
