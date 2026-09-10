package com.setu.navigator

import com.setu.navigator.data.GeoPoint
import com.setu.navigator.data.GraphBinary
import com.setu.navigator.data.RoadGraph
import org.junit.Assert.*
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder
import java.nio.ByteBuffer
import java.nio.ByteOrder
import java.util.concurrent.CancellationException

class GraphBinaryTest {
    @get:Rule val temporary = TemporaryFolder()
    private val west = GeoPoint(28.68, 77.27)
    private val east = GeoPoint(28.68, 77.28)

    private fun binary(): ByteArray {
        val graph = RoadGraph.Builder().apply {
            road(longArrayOf(1, 2), listOf(west, east), "Road", "no")
        }.build()
        val output = ByteBuffer.allocate(20 + graph.nodeCount * 20 + graph.edgeCount * 24 + 8).order(ByteOrder.LITTLE_ENDIAN)
        output.put("SETUGR1\n".toByteArray()).putInt(graph.nodeCount).putInt(graph.edgeCount).putInt(1)
        for (values in listOf(graph.latitudes, graph.longitudes)) repeat(values.limit()) { output.putDouble(values[it]) }
        for (values in listOf(graph.heads, graph.sourceNodes, graph.targets, graph.next)) repeat(values.limit()) { output.putInt(values[it]) }
        repeat(graph.lengths.limit()) { output.putDouble(graph.lengths[it]) }
        repeat(graph.nameIds.limit()) { output.putInt(graph.nameIds[it]) }
        output.putInt(4).put("Road".toByteArray())
        return output.array()
    }

    @Test
    fun mappedGraphPreservesGeometryDirectionsAndPartialSegmentRoutes() {
        val file = temporary.newFile().apply { writeBytes(binary()) }
        val graph = GraphBinary.read(file)
        assertTrue(graph.latitudes.isDirect)
        assertTrue(graph.latitudes.isReadOnly)
        assertEquals(2, graph.nodeCount)
        assertEquals(2, graph.edgeCount)
        val route = graph.route(west.interpolate(east, 0.2), west.interpolate(east, 0.8))
        assertEquals(west.distanceTo(east) * 0.6, route.distanceMeters, 0.1)
        assertEquals(east.distanceTo(west), graph.route(east, west).distanceMeters, 0.1)
    }

    @Test
    fun invalidCountsCoordinatesLinksTargetsLengthsNamesAndTrailingDataFailClosed() {
        val mutations: List<(ByteBuffer) -> Unit> = listOf(
            { it.put(0, 0) },
            { it.putInt(8, 4_000_001) },
            { it.putInt(12, -1) },
            { it.putInt(16, 0) },
            { it.putDouble(20, Double.NaN) },
            { it.putDouble(36, 200.0) },
            { it.putInt(52, 2) },
            { it.putInt(60, 1) },
            { it.putInt(68, 5) },
            { it.putInt(76, 0) },
            { it.putDouble(84, -1.0) },
            { it.putInt(100, 2) },
            { it.putInt(108, 1000) },
            { it.put(112, 0xff.toByte()) },
        )
        for (mutation in mutations) {
            val bytes = binary()
            mutation(ByteBuffer.wrap(bytes).order(ByteOrder.LITTLE_ENDIAN))
            val file = temporary.newFile().apply { writeBytes(bytes) }
            assertThrows(Exception::class.java) { GraphBinary.read(file) }
        }
        for (bytes in listOf(binary().copyOf(50), binary() + byteArrayOf(0))) {
            val file = temporary.newFile().apply { writeBytes(bytes) }
            assertThrows(IllegalArgumentException::class.java) { GraphBinary.read(file) }
        }
    }

    @Test
    fun cancellationLeavesTheValidatedFileUntouched() {
        val bytes = binary()
        val file = temporary.newFile().apply { writeBytes(bytes) }
        assertThrows(CancellationException::class.java) { GraphBinary.read(file) { throw CancellationException() } }
        assertArrayEquals(bytes, file.readBytes())
    }
}
