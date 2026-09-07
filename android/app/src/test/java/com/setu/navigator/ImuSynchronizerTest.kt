package com.setu.navigator

import com.setu.navigator.data.GeoPoint
import com.setu.navigator.data.Pose
import com.setu.navigator.estimation.*
import org.junit.Assert.*
import org.junit.Test

class ImuSynchronizerTest {
    @Test
    fun interpolationUsesTimestampsAndNeverInventsAcrossGaps() {
        val samples = mutableListOf<Pair<Long, DoubleArray>>()
        val sync = ImuSynchronizer { timestamp, acceleration, _ -> samples.add(timestamp to acceleration) }
        sync.gyroscope(15_000_000, doubleArrayOf(0.0, 0.0, 0.1))
        sync.acceleration(10_000_000, doubleArrayOf(1.0, 2.0, 9.0))
        assertTrue(samples.isEmpty())
        sync.acceleration(20_000_000, doubleArrayOf(3.0, 4.0, 11.0))
        assertEquals(15_000_000L, samples.single().first)
        assertArrayEquals(doubleArrayOf(2.0, 3.0, 10.0), samples.single().second, 1e-12)
        sync.gyroscope(15_000_000, DoubleArray(3))
        sync.gyroscope(30_000_000, DoubleArray(3))
        sync.acceleration(200_000_000, DoubleArray(3))
        assertEquals(1, samples.size)
        assertEquals(2L, sync.rejected)
        sync.acceleration(210_000_000, doubleArrayOf(Double.NaN, 0.0, 0.0))
        assertEquals(3L, sync.rejected)
    }

    @Test
    fun missingCounterpartIsBoundedAndRecovers() {
        var accepted = 0
        val sync = ImuSynchronizer { _, _, _ -> accepted++ }
        repeat(500) { index -> sync.gyroscope((index + 1L) * 5_000_000, DoubleArray(3)) }
        assertEquals(372L, sync.rejected)
        sync.acceleration(2_495_000_000, DoubleArray(3))
        sync.acceleration(2_505_000_000, DoubleArray(3))
        assertEquals(2, accepted)
    }

    @Test
    fun declinationRotatesMagneticNorthTowardTrueEast() {
        val identity = doubleArrayOf(1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0)
        val rotated = trueNorthRotation(identity, Math.PI / 2)
        assertEquals(1.0, rotated[1], 1e-12)
        assertEquals(-1.0, rotated[3], 1e-12)
        assertEquals(1.0, rotated[8], 1e-12)
        assertArrayEquals(identity, trueNorthRotation(identity, 0.0), 1e-12)
    }

    @Test
    fun nativeSelectionRequiresOptInAndAFreshPublishedState() {
        val gps = Pose(GeoPoint(12.9, 77.6), timestampNs = 1_000_000_000)
        val fused = gps.copy(source = "Native GPS + IMU", filterRadius95Meters = 5.0)
        val estimate = NativeEstimate(pose = fused)
        assertEquals(gps, navigationPose(gps, estimate, false, 1_000_000_000))
        assertEquals(fused, navigationPose(gps, estimate, true, 1_200_000_000))
        assertEquals(gps, navigationPose(gps, estimate, true, 1_300_000_001))
        assertEquals(gps, navigationPose(gps, estimate, true, 999_999_999))
        assertEquals(gps, navigationPose(gps, NativeEstimate(), true, 1_000_000_000))
    }

    @Test
    fun missingHeadingAccuracyExplainsFallbackWithoutInventingAPose() {
        val gps = Pose(GeoPoint(12.9, 77.6), timestampNs = 1_000_000_000)
        for (mode in 0..1) {
            val snapshot = DoubleArray(20).apply { this[0] = mode.toDouble() }
            val estimate = decodeNativeEstimate(snapshot, headingAccuracyAvailable = false)
            assertEquals("Heading accuracy unavailable", estimate.status)
            assertTrue(estimate.detail.contains("GPS tracking"))
            assertNull(estimate.pose)
            assertEquals(gps, navigationPose(gps, estimate, true, 1_000_000_000))
            assertEquals(decodeNativeEstimate(snapshot), decodeNativeEstimate(snapshot, headingAccuracyAvailable = true))
        }
    }

    @Test
    fun headingAvailabilityDoesNotOverrideActiveOrWithheldNativeStates() {
        for (mode in 2..5) {
            val snapshot = DoubleArray(20).apply { this[0] = mode.toDouble() }
            assertEquals(decodeNativeEstimate(snapshot), decodeNativeEstimate(snapshot, headingAccuracyAvailable = false))
        }
    }
}
