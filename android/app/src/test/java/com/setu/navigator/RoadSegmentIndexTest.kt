package com.setu.navigator

import com.setu.navigator.data.GeoPoint
import com.setu.navigator.data.RoadGraph
import com.setu.navigator.data.RoadSegmentIndex
import org.junit.Assert.*
import org.junit.Test
import java.util.concurrent.CancellationException
import kotlin.math.cos
import kotlin.random.Random

class RoadSegmentIndexTest {
    @Test
    fun longSegmentsAndPolarQueriesRetainAllPossibleCandidates() {
        val random = Random(74)
        val points = List(1024) { GeoPoint(28.6 + random.nextDouble() * 0.1, 77.1 + random.nextDouble() * 0.1) }
        val graph = RoadGraph.Builder().apply {
            road(LongArray(points.size) { it.toLong() }, points, "Crossing roads", "no")
        }.build()
        val index = graph.index()
        repeat(32) {
            val location = points[random.nextInt(points.size)].interpolate(points[random.nextInt(points.size)], random.nextDouble())
            val candidates = mutableSetOf<Int>()
            index.visit(location, {}) { candidates.add(it) }
            val eastScale = 111320.0 * cos(Math.toRadians(location.latitude))
            for (edge in 0 until graph.edgeCount) {
                val source = graph.sourceNodes[edge]
                val target = graph.targets[edge]
                val east = (graph.longitudes[source] - location.longitude) * eastScale
                val north = (graph.latitudes[source] - location.latitude) * 111320.0
                val deltaEast = (graph.longitudes[target] - graph.longitudes[source]) * eastScale
                val deltaNorth = (graph.latitudes[target] - graph.latitudes[source]) * 111320.0
                val squared = deltaEast * deltaEast + deltaNorth * deltaNorth
                val fraction = if (squared == 0.0) 0.0 else (-(east * deltaEast + north * deltaNorth) / squared).coerceIn(0.0, 1.0)
                val projectedEast = east + fraction * deltaEast
                val projectedNorth = north + fraction * deltaNorth
                if (projectedEast * projectedEast + projectedNorth * projectedNorth <= 62500) assertTrue("Missing edge $edge", edge in candidates)
            }
        }
        val polar = RoadGraph.Builder().apply { road(longArrayOf(1, 2), listOf(GeoPoint(89.999, -40.0), GeoPoint(89.999, 40.0)), "Polar", "no") }.build()
        assertEquals(2, polar.index().visit(GeoPoint(90.0, 0.0), {}) {})
    }

    @Test
    fun localBlocksSkipRemoteSegmentsAndCancelledBuildCanBeRetried() {
        val graph = RoadGraph.Builder().apply {
            repeat(64) { group ->
                val points = List(257) { GeoPoint(27.0 + group * 0.02, 77.0 + it * 0.00001) }
                road(LongArray(points.size) { group * 1000L + it }, points, "Road $group", "no")
            }
        }.build()
        assertThrows(CancellationException::class.java) { graph.index { throw CancellationException() } }
        val index = graph.index()
        assertTrue(index.bytes < graph.edgeCount)
        val visited = index.visit(GeoPoint(27.0, 77.001), {}) {}
        assertEquals(512, visited)
        assertTrue(visited < graph.edgeCount / 10)
        assertThrows(CancellationException::class.java) { index.visit(GeoPoint(27.0, 77.0), { throw CancellationException() }) {} }
    }
}
