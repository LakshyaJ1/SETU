package com.setu.navigator

import android.content.ContextWrapper
import android.os.Debug
import android.os.SystemClock
import androidx.test.platform.app.InstrumentationRegistry
import com.setu.navigator.data.*
import org.json.JSONObject
import org.junit.After
import org.junit.Assert.*
import org.junit.Test
import java.io.File
import java.io.RandomAccessFile
import java.util.UUID
import java.util.concurrent.CancellationException

class CompiledRoadGraphTest {
    private val instrumentation = InstrumentationRegistry.getInstrumentation()
    private val base = instrumentation.targetContext
    private val namespace = "compiled-graph-${UUID.randomUUID()}"
    private val directory = File(base.cacheDir, namespace).apply { mkdirs() }
    private val context = object : ContextWrapper(base) {
        override fun getFilesDir() = File(directory, "files").apply { mkdirs() }
        override fun getCacheDir() = File(directory, "cache").apply { mkdirs() }
        override fun getSharedPreferences(name: String, mode: Int) = base.getSharedPreferences("$namespace-$name", mode)
    }

    @After
    fun cleanup() {
        directory.deleteRecursively()
        base.deleteSharedPreferences("$namespace-setu-maps")
    }

    @Test
    fun pythonCompiledFixtureMatchesJsonRoutesAndOneWaySemantics() {
        val fixture = File(directory, "fixture.bin")
        instrumentation.context.assets.open("graph-fixture/roads.bin").use { source -> fixture.outputStream().use { source.copyTo(it) } }
        val mapped = GraphBinary.read(fixture)
        val json = instrumentation.context.assets.open("map-fixture/roads.json").use { MapJson.graph(it) }
        val region = JSONObject(instrumentation.context.assets.open("map-fixture/manifest.json").bufferedReader().use { it.readText() })
        val places = region.getJSONArray("places")
        val origin = region.getJSONArray("previewStart").let { GeoPoint(it.getDouble(1), it.getDouble(0)) }
        for (index in 0 until places.length()) {
            val point = places.getJSONObject(index).getJSONArray("point").let { GeoPoint(it.getDouble(1), it.getDouble(0)) }
            for ((from, to) in listOf(origin to point, point to origin)) {
                val expected = json.route(from, to)
                val actual = mapped.route(from, to)
                assertEquals(expected.points, actual.points)
                assertEquals(expected.distanceMeters, actual.distanceMeters, 1e-6)
                assertEquals(expected.maneuvers, actual.maneuvers)
            }
        }
        assertEquals(json.nodeCount, mapped.nodeCount)
        assertEquals(json.edgeCount, mapped.edgeCount)
    }

    @Test
    fun ncrColdAndWarmRoutesUseMappedGraphAndRecoverCorruptCacheWithoutJsonParsing() {
        val region = MapPackStore(context).regions.value.single { it.id == "delhi" }
        val metadata = JSONObject(base.assets.open("regions/delhi/graph.json").bufferedReader().use { it.readText() })
        val started = SystemClock.elapsedRealtime()
        assertThrows(CancellationException::class.java) { CompiledRoadGraph.load(context, region) { throw CancellationException() } }
        assertTrue(File(context.cacheDir, "compiled-graphs").listFiles().orEmpty().isEmpty())
        val graph = checkNotNull(CompiledRoadGraph.load(context, region) {})
        val coldMs = SystemClock.elapsedRealtime() - started
        val destination = region.places.single { it.id == region.demoDestination }.point
        val routeStarted = SystemClock.elapsedRealtime()
        val route = graph.route(region.previewStart, destination)
        val routeMs = SystemClock.elapsedRealtime() - routeStarted
        val repeatedStarted = SystemClock.elapsedRealtime()
        assertEquals(route.points, graph.route(region.previewStart, destination).points)
        val repeatedRouteMs = SystemClock.elapsedRealtime() - repeatedStarted
        val candidateEdges = graph.index().visit(region.previewStart, {}) {}
        assertTrue(route.distanceMeters in 20_000.0..70_000.0)
        assertTrue(route.destinationOffsetMeters <= 250)
        assertEquals(metadata.getInt("nodes"), graph.nodeCount)
        assertEquals(metadata.getInt("edges"), graph.edgeCount)
        val warmStarted = SystemClock.elapsedRealtime()
        val warm = checkNotNull(CompiledRoadGraph.load(context, region) {})
        val warmMs = SystemClock.elapsedRealtime() - warmStarted
        assertEquals(route.points, warm.route(region.previewStart, destination).points)
        val cache = File(context.cacheDir, "compiled-graphs/${metadata.getString("sha256")}.bin")
        val hash = cache.inputStream().use { input -> java.security.MessageDigest.getInstance("SHA-256").apply {
            val bytes = ByteArray(65536)
            while (true) { val count = input.read(bytes); if (count < 0) break; update(bytes, 0, count) }
        }.digest().joinToString("") { "%02x".format(it) } }
        assertEquals(metadata.getString("sha256"), hash)
        RandomAccessFile(cache, "rw").use { it.seek(0); it.writeByte(0) }
        val recovered = checkNotNull(CompiledRoadGraph.load(context, region) {})
        assertEquals(route.points, recovered.route(region.previewStart, destination).points)
        val memory = Debug.MemoryInfo().also(Debug::getMemoryInfo)
        val evidence = JSONObject().put("scenario", "Full NCR compiled graph cold/warm/corrupt-cache routes; no driving accuracy claim")
            .put("device", android.os.Build.MODEL).put("sdk", android.os.Build.VERSION.SDK_INT)
            .put("coldPreparationMs", coldMs).put("warmOpenMs", warmMs).put("routeMs", routeMs)
            .put("repeatedRouteMs", repeatedRouteMs).put("startCandidateEdges", candidateEdges).put("spatialIndexBytes", graph.index().bytes)
            .put("distanceMeters", route.distanceMeters).put("nodes", graph.nodeCount).put("edges", graph.edgeCount)
            .put("sampledPssKiB", memory.totalPss).put("javaHeapUsedBytes", Runtime.getRuntime().totalMemory() - Runtime.getRuntime().freeMemory())
            .put("peakMemoryMeasured", false).put("mapRendererLoaded", false)
        File(base.getExternalFilesDir(null), "verification").apply { mkdirs() }.resolve("compiled-graph-metrics.json").writeText(evidence.toString(2))
    }
}
