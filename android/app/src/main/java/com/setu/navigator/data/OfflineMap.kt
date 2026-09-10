package com.setu.navigator.data

import android.content.Context
import android.net.Uri
import android.util.AtomicFile
import org.json.JSONObject
import java.io.File
import java.io.InputStream
import java.security.MessageDigest
import java.util.zip.GZIPInputStream

class OfflineMap(private val context: Context, val region: MapRegion, private var graph: RoadGraph? = null) {
    val places get() = region.places
    val center get() = region.center
    val demonstrationStart get() = region.previewStart
    val sizeBytes: Long get() = region.sizeBytes

    fun citySource(): JSONObject {
        OfflineTiles.matching(context, region)?.let { return it.source(region.attribution, region.bounds) }
        require((region.cityBytes ?: 0) <= 32L * 1024 * 1024) {
            "This map is too large for the legacy renderer. Select the included Delhi & NCR tiled map."
        }
        return JSONObject().put("type", "geojson").put("data", cityUri()).put("attribution", region.attribution)
    }

    private fun asset(name: String, fallback: String) = region.assetDirectory?.let { "$it/$name" } ?: fallback
    private fun open(name: String, fallback: String): InputStream = region.directory?.resolve(name)?.inputStream()
        ?: if (region.compressedAssets) GZIPInputStream(context.assets.open(asset(name, fallback) + ".gzip"))
        else context.assets.open(asset(name, fallback))

    fun cityJson(): String = open("city.geojson", "bengaluru.geojson").bufferedReader().use { it.readText() }
    fun cityUri(): String {
        if (region.compressedAssets && region.directory == null) return Uri.fromFile(cachedCity()).toString()
        open("city.geojson", "bengaluru.geojson").use { }
        return region.directory?.resolve("city.geojson")?.let { Uri.fromFile(it).toString() }
            ?: "asset://${asset("city.geojson", "bengaluru.geojson")}"
    }

    @Synchronized
    private fun cachedCity(): File {
        val expectedBytes = requireNotNull(region.cityBytes)
        val expectedHash = requireNotNull(region.cityChecksum)
        val directory = File(context.cacheDir, "bundled-maps").apply { check(isDirectory || mkdirs()) }
        val target = File(directory, "${region.id}-${region.revision}-${expectedHash.take(16)}.geojson")
        if (target.isFile && target.length() == expectedBytes) return target
        val atomic = AtomicFile(target)
        val output = atomic.startWrite()
        try {
            val digest = MessageDigest.getInstance("SHA-256")
            var size = 0L
            open("city.geojson", "bengaluru.geojson").use { input ->
                val buffer = ByteArray(65536)
                while (true) {
                    val count = input.read(buffer)
                    if (count < 0) break
                    size += count
                    check(size <= expectedBytes) { "The bundled map exceeds its declared size." }
                    output.write(buffer, 0, count)
                    digest.update(buffer, 0, count)
                }
            }
            check(size == expectedBytes && digest.digest().joinToString("") { "%02x".format(it) } == expectedHash) { "Bundled map integrity check failed." }
            atomic.finishWrite(output)
        } catch (failure: Exception) {
            atomic.failWrite(output)
            throw failure
        }
        return target
    }

    fun contains(point: GeoPoint) = region.contains(point)

    @Synchronized
    private fun loadGraph(checkpoint: () -> Unit): RoadGraph = graph
        ?: (CompiledRoadGraph.load(context, region, checkpoint)
            ?: MapJson.graph(open("roads.json", "bengaluru-roads.json"), checkpoint)).also { graph = it }

    @Synchronized
    fun route(from: GeoPoint, to: GeoPoint, checkpoint: () -> Unit = {}): DriveRoute {
        checkpoint()
        require(contains(from) && contains(to)) { "This journey is outside ${region.name}." }
        return loadGraph(checkpoint).route(from, to, checkpoint)
    }
}
