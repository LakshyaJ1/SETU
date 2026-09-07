package com.setu.navigator

import android.content.ContextWrapper
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import com.setu.navigator.data.MapPackStore
import org.junit.After
import org.junit.Assert.*
import org.junit.Test
import org.junit.runner.RunWith
import java.io.File
import java.net.InetAddress
import java.net.ServerSocket
import java.util.UUID
import java.util.concurrent.CancellationException
import kotlin.concurrent.thread

@RunWith(AndroidJUnit4::class)
class MapPackStoreTest {
    private val target = InstrumentationRegistry.getInstrumentation().targetContext
    private val namespace = "map-tests-${UUID.randomUUID()}"
    private val directory = File(target.cacheDir, namespace).apply { mkdirs() }
    private val context = object : ContextWrapper(target) {
        override fun getFilesDir() = File(directory, "files").apply { mkdirs() }
        override fun getCacheDir() = File(directory, "cache").apply { mkdirs() }
        override fun getSharedPreferences(name: String, mode: Int) = target.getSharedPreferences("$namespace-$name", mode)
    }
    private val store = MapPackStore(context)

    @After
    fun cleanup() { directory.deleteRecursively(); target.deleteSharedPreferences("$namespace-setu-maps") }

    @Test
    fun installActivateRestoreAndRemovePreserveFallback() {
        val imported = store.import(MapPackFixture.bytes().inputStream())
        assertEquals(3, store.regions.value.size)
        assertTrue(store.activeMap.value.region.bundled)
        store.activate(imported.key)
        assertEquals(imported.key, store.activeMap.value.region.key)
        assertTrue(store.activeMap.value.route(imported.previewStart, imported.places.last().point).distanceMeters > 2000)
        val restored = MapPackStore(context).apply { restore() }
        assertEquals(imported.key, restored.activeMap.value.region.key)
        assertThrows(IllegalArgumentException::class.java) { store.remove(imported.key) }
        assertThrows(IllegalArgumentException::class.java) { store.remove("bundled") }
        store.activate("bundled")
        store.remove(imported.key)
        assertEquals(2, store.regions.value.size)
        assertFalse(imported.directory!!.exists())
        assertTrue(context.cacheDir.listFiles().orEmpty().isEmpty())
    }

    @Test
    fun revisionsNeverSilentlyReplaceOrDowngrade() {
        val documents = MapPackFixture.documents()
        documents.getValue("manifest.json").put("revision", 2)
        val imported = store.import(MapPackFixture.bytes(documents).inputStream())
        store.activate(imported.key)
        reject(MapPackFixture.bytes(documents))
        documents.getValue("manifest.json").put("revision", 1)
        reject(MapPackFixture.bytes(documents))
        documents.getValue("manifest.json").put("revision", 3)
        val newer = store.import(MapPackFixture.bytes(documents).inputStream())
        assertEquals(imported.key, store.activeMap.value.region.key)
        assertEquals(4, store.regions.value.size)
        store.activate(newer.key)
        store.remove(imported.key)
    }

    @Test
    fun badArchivesAndChecksumsLeaveNoInstalledFiles() {
        reject(MapPackFixture.zip(mapOf("../escaped.json" to byteArrayOf(1))))
        reject(MapPackFixture.zip(mapOf("manifest.json" to byteArrayOf(1))))
        reject(MapPackFixture.zip(mapOf("manifest.json" to ByteArray(65537) { 32 })))
        reject(MapPackFixture.bytes { it.getJSONObject("sha256").put("city.geojson", "0".repeat(64)) })
        val complete = MapPackFixture.bytes()
        reject(complete.copyOf(complete.size - 22))
        assertTrue(context.filesDir.resolve("map-packs").listFiles().orEmpty().isEmpty())
        assertFalse(context.cacheDir.resolve("escaped.json").exists())
    }

    @Test
    fun invalidGeometryMetadataAndGraphAreRejected() {
        fun malformed(change: (MutableMap<String, org.json.JSONObject>) -> Unit) {
            val documents = MapPackFixture.documents(); change(documents); reject(MapPackFixture.bytes(documents))
        }
        malformed { it.getValue("manifest.json").put("schema", "setu.map.v999") }
        malformed { it.getValue("manifest.json").put("revision", 1.5) }
        malformed { it.getValue("manifest.json").put("bounds", org.json.JSONArray(listOf(10, 77, 15, 78))) }
        malformed { it.getValue("manifest.json").put("sourceUrl", "https://user:password@example.invalid") }
        malformed { it.getValue("city.geojson").getJSONArray("features").getJSONObject(0).getJSONObject("geometry").getJSONArray("coordinates").getJSONArray(0).put(1, 91) }
        malformed { it.getValue("city.geojson").getJSONArray("features").getJSONObject(0).getJSONObject("geometry").getJSONArray("coordinates").getJSONArray(0).put(1, "12.97") }
        malformed { it.getValue("city.geojson").getJSONArray("features").getJSONObject(0).getJSONObject("geometry").put("coordinates", org.json.JSONArray()) }
        malformed { it.getValue("city.geojson").getJSONArray("features").getJSONObject(0).getJSONObject("properties").put("name", "\u4eac\u90fd") }
        malformed { it.getValue("roads.json").getJSONArray("roads").getJSONObject(0).put("oneway", "sometimes") }
        malformed { it.getValue("roads.json").getJSONArray("roads").getJSONObject(0).put("id", 1.5) }
        malformed { it.getValue("roads.json").getJSONArray("roads").getJSONObject(0).getJSONArray("nodes").put(2, 1) }
        malformed { it.getValue("roads.json").getJSONArray("roads").getJSONObject(0).put("oneway", "-1") }
    }

    @Test
    fun cancellationKeepsThePreviousMapAndCleansStaging() {
        var checkpoints = 0
        assertThrows(CancellationException::class.java) {
            store.import(MapPackFixture.bytes().inputStream()) { if (++checkpoints == 5) throw CancellationException("Test cancellation") }
        }
        assertTrue(store.activeMap.value.region.bundled)
        assertEquals(2, store.regions.value.size)
        assertTrue(context.cacheDir.listFiles().orEmpty().isEmpty())
        assertTrue(context.filesDir.resolve("map-packs").listFiles().orEmpty().isEmpty())
        val bytes = MapPackFixture.bytes()
        serve(bytes) { address -> assertThrows(CancellationException::class.java) {
            store.download(address, MapPackFixture.sha256(bytes), checkpoint = { throw CancellationException("Test cancellation") })
        } }
        assertTrue(context.cacheDir.listFiles().orEmpty().isEmpty())
    }

    @Test
    fun corruptInstalledMapCannotActivateAndRestoresFallback() {
        val imported = store.import(MapPackFixture.bytes().inputStream())
        store.activate(imported.key)
        imported.directory!!.resolve("city.geojson").appendText(" ")
        assertThrows(IllegalArgumentException::class.java) { store.activate(imported.key) }
        val restored = MapPackStore(context).apply { restore() }
        assertTrue(restored.activeMap.value.region.bundled)
        restored.remove(imported.key)
    }

    @Test
    fun directDownloadChecksHashAndDoesNotActivateAutomatically() {
        val bytes = MapPackFixture.bytes()
        var received = 0L
        serve(bytes) { address -> store.download(address, MapPackFixture.sha256(bytes), { count, total ->
            received = count; assertEquals(bytes.size.toLong(), total)
        }) }
        assertEquals(bytes.size.toLong(), received)
        assertEquals(3, store.regions.value.size)
        assertTrue(store.activeMap.value.region.bundled)
        assertTrue(context.cacheDir.listFiles().orEmpty().isEmpty())
    }

    @Test
    fun failedDownloadsNeverInstallOrFollowRedirects() {
        val bytes = MapPackFixture.bytes()
        serve(bytes) { address -> assertThrows(IllegalArgumentException::class.java) { store.download(address, "0".repeat(64)) } }
        serve(bytes, status = "302 Found", extra = "Location: http://127.0.0.1:1/should-not-follow\r\n") { address ->
            assertThrows(IllegalArgumentException::class.java) { store.download(address, MapPackFixture.sha256(bytes)) }
        }
        serve(bytes, declaredSize = bytes.size + 20) { address ->
            assertThrows(Exception::class.java) { store.download(address, MapPackFixture.sha256(bytes)) }
        }
        assertThrows(IllegalArgumentException::class.java) { store.download("http://example.invalid/map", "0".repeat(64)) }
        assertThrows(IllegalArgumentException::class.java) { store.download("https://user:password@example.invalid/map", "0".repeat(64)) }
        assertThrows(IllegalArgumentException::class.java) { store.download("https://example.invalid/map", "bad-checksum") }
        assertEquals(2, store.regions.value.size)
        assertTrue(context.cacheDir.listFiles().orEmpty().isEmpty())
    }

    @Test
    fun includedNcrCoversCitiesAndRoutesShahdaraToMait() {
        val delhi = store.regions.value.single { it.id == "delhi" }
        assertTrue(delhi.bundled)
        assertEquals("Delhi & NCR", delhi.name)
        assertEquals(2, delhi.revision)
        listOf(com.setu.navigator.data.GeoPoint(28.60, 76.84), com.setu.navigator.data.GeoPoint(28.89, 77.10),
            com.setu.navigator.data.GeoPoint(28.62, 77.33), com.setu.navigator.data.GeoPoint(28.40, 77.20)).forEach {
            assertTrue(delhi.contains(it))
        }
        assertFalse(delhi.contains(com.setu.navigator.data.GeoPoint(12.97, 77.60)))
        listOf(com.setu.navigator.data.GeoPoint(28.46, 77.03), com.setu.navigator.data.GeoPoint(28.54, 77.39),
            com.setu.navigator.data.GeoPoint(28.41, 77.32), com.setu.navigator.data.GeoPoint(28.67, 77.45),
            com.setu.navigator.data.GeoPoint(28.99, 77.71), com.setu.navigator.data.GeoPoint(29.69, 76.99),
            com.setu.navigator.data.GeoPoint(27.55, 76.63), com.setu.navigator.data.GeoPoint(27.22, 77.49)).forEach {
            assertTrue("NCR city missing from the map envelope", delhi.contains(it))
        }
        assertThrows(IllegalArgumentException::class.java) { store.remove(delhi.key) }
        store.activate(delhi.key)
        val route = store.activeMap.value.route(delhi.previewStart, delhi.places.single { it.id == delhi.demoDestination }.point)
        assertTrue("Shahdara to MAIT distance: ${route.distanceMeters}", route.distanceMeters in 20000.0..60000.0)
        assertTrue(route.points.size > 2)
        assertTrue(route.startOffsetMeters < 75.0)
        assertTrue(route.destinationOffsetMeters <= 250.0)
        listOf("Noida", "Ghaziabad", "Meerut").forEach { name ->
            val place = delhi.places.firstOrNull { it.name.equals(name, ignoreCase = true) }
            assertNotNull("Eastern NCR locality data missing: $name", place)
            val easternRoute = store.activeMap.value.route(delhi.previewStart, requireNotNull(place).point)
            assertTrue("No connected driving graph for $name", easternRoute.points.size > 2)
            assertTrue(easternRoute.destinationOffsetMeters <= 250.0)
        }
        val restored = MapPackStore(context).apply { restore() }
        assertEquals(delhi.key, restored.activeMap.value.region.key)
        assertEquals(setOf("delhi", "bengaluru-central"), restored.regions.value.map { it.id }.toSet())
        restored.activate("bundled")
        assertEquals("bengaluru-central", restored.activeMap.value.region.id)
    }

    @Test
    fun includedNcrUsesBoundedLocalVectorTiles() {
        val delhi = store.regions.value.single { it.id == "delhi" }
        store.activate(delhi.key)
        val source = store.activeMap.value.citySource()
        assertEquals("vector", source.getString("type"))
        val template = source.getJSONArray("tiles").getString(0)
        assertTrue(template.startsWith("file:///"))
        assertEquals(13, source.getInt("maxzoom"))
        val directory = File(java.net.URI(template.substringBefore("/{z}")))
        val tiles = directory.walkTopDown().filter { it.extension == "pbf" }.toList()
        assertTrue(tiles.size > 1000)
        assertTrue(tiles.all { it.length() in 1..500000 })
        assertEquals(template, store.activeMap.value.citySource().getJSONArray("tiles").getString(0))
    }

    private fun reject(bytes: ByteArray) {
        val before = store.regions.value
        assertThrows(Exception::class.java) { store.import(bytes.inputStream()) }
        assertEquals(before, store.regions.value)
        assertTrue(context.cacheDir.listFiles().orEmpty().isEmpty())
    }

    private fun serve(bytes: ByteArray, status: String = "200 OK", extra: String = "", declaredSize: Int = bytes.size, block: (String) -> Unit) {
        ServerSocket(0, 1, InetAddress.getByName("127.0.0.1")).use { server ->
            val worker = thread(isDaemon = true) { runCatching {
                server.accept().use { socket ->
                    socket.soTimeout = 3000
                    val reader = socket.getInputStream().bufferedReader()
                    while (!reader.readLine().isNullOrEmpty()) { }
                    socket.getOutputStream().apply {
                        write("HTTP/1.1 $status\r\nContent-Length: $declaredSize\r\n${extra}Connection: close\r\n\r\n".toByteArray())
                        write(bytes); flush()
                    }
                }
            } }
            block("http://127.0.0.1:${server.localPort}/fixture.setumap")
            worker.join(4000)
            assertFalse("Test HTTP server should finish", worker.isAlive)
        }
    }
}
