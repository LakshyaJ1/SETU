package com.setu.navigator

import com.setu.navigator.data.GeoPoint
import com.setu.navigator.data.Pose
import org.junit.Assert.*
import org.junit.Test

class PoseTest {
    @Test
    fun freshnessRejectsFutureUnsetAndStaleTimestamps() {
        val pose = Pose(GeoPoint(12.9, 77.6), timestampNs = 5_000_000_000L)
        assertTrue(pose.isFresh(5_000_000_000L))
        assertTrue(pose.isFresh(7_999_999_999L))
        assertFalse(pose.isFresh(8_000_000_000L))
        assertFalse(pose.isFresh(4_999_999_999L))
        assertFalse(pose.copy(timestampNs = 0).isFresh(1))
        assertNull(pose.speedMps)
        assertNull(pose.bearing)
        assertNull(pose.accuracyMeters)
    }
}
