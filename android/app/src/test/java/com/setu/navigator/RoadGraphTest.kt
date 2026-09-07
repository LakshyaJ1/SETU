package com.setu.navigator

import com.setu.navigator.data.GeoPoint
import com.setu.navigator.data.RoadGraph
import com.setu.navigator.data.routeProgress
import org.junit.Assert.*
import org.junit.Test

class RoadGraphTest {
    private val west = GeoPoint(28.68, 77.27)
    private val east = GeoPoint(28.68, 77.28)

    @Test
    fun snapsToTheRoadSegmentRatherThanJumpingToADistantNode() {
        val graph = RoadGraph.Builder().apply { road(longArrayOf(1, 2), listOf(west, east), "Road 60", "no") }.build()
        val origin = west.interpolate(east, 0.4).copy(latitude = 28.6801)
        val destination = west.interpolate(east, 0.8)
        val route = graph.route(origin, destination)
        assertEquals(2, route.points.size)
        assertTrue(route.points.first().distanceTo(west.interpolate(east, 0.4)) < 0.1)
        assertEquals(west.distanceTo(east) * 0.4, route.distanceMeters, 0.1)
        assertTrue(route.startOffsetMeters in 10.0..12.0)
        assertEquals(origin, route.requestedStart)
        assertEquals(destination, route.requestedDestination)
    }

    @Test
    fun oneWayRouteUsesTheConnectedDetourInsteadOfDrivingBackwards() {
        val northEast = east.copy(latitude = 28.685)
        val northWest = west.copy(latitude = 28.685)
        val graph = RoadGraph.Builder(4, 4).apply {
            road(longArrayOf(1, 2), listOf(west, east), "Eastbound", "yes")
            road(longArrayOf(2, 3, 4, 1), listOf(east, northEast, northWest, west), "Return road", "yes")
        }.build()
        val route = graph.route(west.interpolate(east, 0.8), west.interpolate(east, 0.2))
        assertTrue(route.points.contains(northEast))
        assertTrue(route.points.contains(northWest))
        assertTrue(route.distanceMeters > west.distanceTo(east))
        assertTrue(route.maneuvers.any { it.text.contains("Return road") })
    }

    @Test(expected = IllegalStateException::class)
    fun disconnectedRoadsDoNotGetJoinedWithAnInventedStraightLine() {
        val graph = RoadGraph.Builder().apply {
            road(longArrayOf(10, 20), listOf(west, east), "First", "no")
            road(longArrayOf(30, 40), listOf(west.copy(latitude = 28.69), east.copy(latitude = 28.69)), "Second", "no")
        }.build()
        graph.route(west, east.copy(latitude = 28.69))
    }

    @Test
    fun reverseOnlyEdgesAndZeroLengthJourneysRemainValid() {
        val graph = RoadGraph.Builder().apply { road(longArrayOf(2, 1), listOf(east, west), "Forward", "-1") }.build()
        assertEquals(west.distanceTo(east), graph.route(west, east).distanceMeters, 0.1)
        assertEquals(0.0, graph.route(west, west).distanceMeters, 0.01)
    }

    @Test(expected = IllegalArgumentException::class)
    fun conflictingCoordinatesAreRejected() {
        RoadGraph.Builder().apply {
            road(longArrayOf(1, 2), listOf(west, east), "First", "no")
            road(longArrayOf(1, 3), listOf(east, west), "Conflict", "no")
        }
    }

    @Test
    fun graphGrowsAcrossItsInitialCapacityWithoutLosingConnections() {
        val points = (0..400).map { GeoPoint(28.68, 77.27 + it * 0.00001) }
        val graph = RoadGraph.Builder().apply { road(LongArray(points.size) { 10000L + it }, points, "Long street", "no") }.build()
        assertEquals(401, graph.nodeCount)
        assertEquals(800, graph.edgeCount)
        assertEquals(points.first().distanceTo(points.last()), graph.route(points.first(), points.last()).distanceMeters, 0.1)
    }

    @Test
    fun aTurnIsNotSkippedHalfwayAlongTheApproachRoad() {
        val north = east.copy(latitude = 28.69)
        val graph = RoadGraph.Builder().apply { road(longArrayOf(1, 2, 3), listOf(west, east, north), "Turning road", "no") }.build()
        val route = graph.route(west, north)
        val progress = routeProgress(route, west.interpolate(east, 0.8))
        assertEquals(0, progress.segment)
        assertEquals(1, route.maneuvers.first { it.index > progress.segment }.index)
        assertEquals(west.distanceTo(east) * 0.8, progress.distanceFromStart, 0.1)
        assertTrue(progress.distanceFromRoad < 0.1)
    }
}
