package com.setu.navigator

import com.setu.navigator.data.GeoPoint
import com.setu.navigator.data.Pose
import com.setu.navigator.data.appendTrackingPose
import com.setu.navigator.data.positionSegments
import org.junit.Assert.*
import org.junit.Test

class PositionTrackingTest {
    private fun pose(timestamp: Long, source: String = "GPS") = Pose(GeoPoint(12.9753, 77.6067),
        timestampNs = timestamp, source = source)

    @Test
    fun ignoresMissingStaleFutureAndPreSessionPositions() {
        val history = listOf(pose(8_000_000_000L))
        listOf(null, pose(6_000_000_000L), pose(11_000_000_000L), pose(7_000_000_000L)).forEach { candidate ->
            assertSame(history, appendTrackingPose(history, candidate, 10_000_000_000L, 8_000_000_000L))
        }
    }

    @Test
    fun throttlesDuplicateUpdatesWithoutReorderingTheTrace() {
        val history = listOf(pose(5_000_000_000L))
        listOf(4_900_000_000L, 5_000_000_000L, 5_200_000_000L).forEach { timestamp ->
            assertSame(history, appendTrackingPose(history, pose(timestamp), 5_500_000_000L, 1))
        }
        assertEquals(2, appendTrackingPose(history, pose(5_500_000_000L), 5_500_000_000L, 1).size)
        assertEquals(2, appendTrackingPose(history, pose(5_200_000_000L, "Native inertial"), 5_500_000_000L, 1).size)
    }

    @Test
    fun keepsTheDisplayHistoryBoundedWithoutChangingTheLatestFix() {
        var history = emptyList<Pose>()
        repeat(1250) { index ->
            val timestamp = 1_000_000_000L + index * 500_000_000L
            history = appendTrackingPose(history, pose(timestamp), timestamp, 1)
        }
        assertEquals(1200, history.size)
        assertEquals(26_000_000_000L, history.first().timestampNs)
        assertEquals(625_500_000_000L, history.last().timestampNs)
    }

    @Test
    fun neverDrawsAConnectionAcrossAnOutageOrSourceChange() {
        val history = listOf(pose(1_000_000_000L), pose(2_000_000_000L),
            pose(6_000_000_000L), pose(7_000_000_000L),
            pose(7_500_000_000L, "Native inertial"), pose(8_000_000_000L, "Native inertial"))
        assertEquals(listOf(2, 2, 2), positionSegments(history).map { it.size })
        assertTrue(positionSegments(history.take(1)).isEmpty())
    }
}
