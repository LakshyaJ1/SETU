package com.setu.navigator.data

import kotlin.math.cos

internal class RoadSegmentIndex private constructor(private val bounds: DoubleArray, private val edges: Int) {
    val bytes get() = bounds.size * 8

    fun visit(location: GeoPoint, checkpoint: () -> Unit, accept: (Int) -> Unit): Int {
        val latitudeRadius = 250.0 / 111320.0 + 1e-10
        val longitudeRadius = 250.0 / (111320.0 * cos(Math.toRadians(location.latitude))) + 1e-10
        var visited = 0
        for (block in 0 until bounds.size / 4) {
            if (block % 256 == 0) checkpoint()
            val offset = block * 4
            if (bounds[offset] > location.latitude + latitudeRadius || bounds[offset + 1] < location.latitude - latitudeRadius ||
                bounds[offset + 2] > location.longitude + longitudeRadius || bounds[offset + 3] < location.longitude - longitudeRadius) continue
            for (edge in block * BLOCK_SIZE until minOf((block + 1) * BLOCK_SIZE, edges)) {
                accept(edge)
                visited++
            }
        }
        return visited
    }

    companion object {
        private const val BLOCK_SIZE = 256

        fun build(graph: RoadGraph, checkpoint: () -> Unit): RoadSegmentIndex {
            val bounds = DoubleArray(((graph.edgeCount + BLOCK_SIZE - 1) / BLOCK_SIZE) * 4) {
                if (it % 2 == 0) Double.POSITIVE_INFINITY else Double.NEGATIVE_INFINITY
            }
            for (edge in 0 until graph.edgeCount) {
                if (edge % 4096 == 0) checkpoint()
                val offset = edge / BLOCK_SIZE * 4
                val source = graph.sourceNodes[edge]
                val target = graph.targets[edge]
                bounds[offset] = minOf(bounds[offset], graph.latitudes[source], graph.latitudes[target])
                bounds[offset + 1] = maxOf(bounds[offset + 1], graph.latitudes[source], graph.latitudes[target])
                bounds[offset + 2] = minOf(bounds[offset + 2], graph.longitudes[source], graph.longitudes[target])
                bounds[offset + 3] = maxOf(bounds[offset + 3], graph.longitudes[source], graph.longitudes[target])
            }
            return RoadSegmentIndex(bounds, graph.edgeCount)
        }
    }
}
