package com.setu.navigator

import com.setu.navigator.data.GeoPoint
import com.setu.navigator.data.Pose
import com.setu.navigator.estimation.MotionAlignment
import org.junit.Assert.*
import org.junit.Test
import kotlin.math.*

class MotionAlignmentTest {
    private val identity = doubleArrayOf(1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0)

    private fun exercise(movement: Boolean = true, sendGps: Boolean = true, lateGps: Boolean = false): MotionAlignment.Alignment? {
        val alignment = MotionAlignment()
        val yaw = Math.toRadians(70.0)
        var eastSpeed = 8.0
        var northSpeed = 2.0
        var previousEast = 0.0
        var previousNorth = 0.0
        var delayed: Pose? = null
        for (step in 0..1400) {
            val timestamp = 1_000_000_000L + step * 10_000_000L
            val phase = step / 200 % 4
            val east = if (!movement) 0.0 else when (phase) { 0 -> 1.8; 2 -> -1.8; else -> 0.0 }
            val north = if (!movement) 0.0 else when (phase) { 1 -> 1.8; 3 -> -1.8; else -> 0.0 }
            if (step > 0) {
                eastSpeed += (previousEast + east) * 0.005 * cos(yaw) - (previousNorth + north) * 0.005 * sin(yaw)
                northSpeed += (previousEast + east) * 0.005 * sin(yaw) + (previousNorth + north) * 0.005 * cos(yaw)
            }
            previousEast = east; previousNorth = north
            alignment.rotation(timestamp, identity)
            alignment.imu(timestamp, doubleArrayOf(east, north, 9.80665), doubleArrayOf(0.0, 0.0, 0.0))
            if (lateGps && step % 100 == 20) { delayed?.let(alignment::gnss); delayed = null }
            if (sendGps && step % 100 == 0) {
                val pose = Pose(GeoPoint(28.68, 77.28), hypot(eastSpeed, northSpeed),
                    (Math.toDegrees(atan2(eastSpeed, northSpeed)) + 360) % 360,
                    accuracyMeters = 3.0, timestampNs = timestamp, speedAccuracyMps = 0.05,
                    bearingAccuracyDegrees = 1.0, mock = true)
                if (lateGps) delayed = pose else alignment.gnss(pose)
            }
        }
        return alignment.alignment(15_000_000_000L)
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
}
