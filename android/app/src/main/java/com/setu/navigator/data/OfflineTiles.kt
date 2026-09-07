package com.setu.navigator.data

import android.content.Context
import android.net.Uri
import org.json.JSONArray
import org.json.JSONObject
import java.io.File
import java.security.MessageDigest
import java.util.zip.ZipInputStream

internal class OfflineTiles(private val context: Context, private val metadata: JSONObject) {
    fun source(attribution: String, bounds: List<Double>): JSONObject {
        val directory = prepare()
        return JSONObject().put("type", "vector")
            .put("tiles", JSONArray().put(Uri.fromFile(directory).toString().trimEnd('/') + "/{z}/{x}/{y}.pbf"))
            .put("minzoom", metadata.getInt("minZoom")).put("maxzoom", metadata.getInt("maxZoom"))
            .put("bounds", JSONArray(listOf(bounds[1], bounds[0], bounds[3], bounds[2])))
            .put("attribution", attribution)
    }

    private fun prepare(): File = synchronized(lock) {
        val checksum = metadata.getString("sha256")
        require(checksum.matches(Regex("[a-f0-9]{64}")))
        val root = File(context.cacheDir, "vector-maps").apply { check(isDirectory || mkdirs()) }
        val destination = File(root, checksum)
        val marker = File(destination, "complete")
        if (marker.isFile && marker.readText() == checksum) return@synchronized destination
        val expectedCount = metadata.getInt("tileCount").also { require(it in 1..25000) }
        val expectedSize = metadata.getLong("uncompressedBytes").also { require(it in 1..512L * 1024 * 1024) }
        val digest = MessageDigest.getInstance("SHA-256")
        context.assets.open(ARCHIVE).use { input ->
            val buffer = ByteArray(65536)
            while (true) {
                val count = input.read(buffer)
                if (count < 0) break
                digest.update(buffer, 0, count)
            }
        }
        check(digest.digest().joinToString("") { "%02x".format(it) } == checksum) { "Offline tiles failed their integrity check." }
        val staging = File(root, "$checksum.partial")
        check(staging.canonicalFile.parentFile == root.canonicalFile)
        if (staging.exists()) check(staging.deleteRecursively())
        check(staging.mkdir())
        try {
            var size = 0L
            var count = 0
            val entries = mutableSetOf<String>()
            ZipInputStream(context.assets.open(ARCHIVE).buffered()).use { archive ->
                val buffer = ByteArray(65536)
                while (true) {
                    val entry = archive.nextEntry ?: break
                    require(!entry.isDirectory && entry.name.matches(Regex("(?:[6-9]|1[0-3])/[0-9]{1,4}/[0-9]{1,4}\\.pbf")))
                    require(entries.add(entry.name) && ++count <= expectedCount)
                    val target = File(staging, entry.name)
                    check(target.canonicalPath.startsWith(staging.canonicalPath + File.separator))
                    check(target.parentFile!!.isDirectory || target.parentFile!!.mkdirs())
                    var tileSize = 0
                    target.outputStream().buffered().use { output ->
                        while (true) {
                            val length = archive.read(buffer)
                            if (length < 0) break
                            tileSize += length
                            size += length
                            require(tileSize <= 500000 && size <= expectedSize)
                            output.write(buffer, 0, length)
                        }
                    }
                    require(tileSize > 0)
                    archive.closeEntry()
                }
            }
            check(count == expectedCount && size == expectedSize) { "The offline tile archive is incomplete." }
            File(staging, "complete").writeText(checksum)
            if (destination.exists()) {
                check(destination.canonicalFile.parentFile == root.canonicalFile)
                check(destination.deleteRecursively())
            }
            check(staging.renameTo(destination)) { "Could not prepare the offline map. Check available storage." }
            destination
        } finally {
            if (staging.exists()) staging.deleteRecursively()
        }
    }

    companion object {
        private val lock = Any()
        private const val ARCHIVE = "regions/delhi/city-tiles.zip"
        fun matching(context: Context, region: MapRegion): OfflineTiles? {
            if (region.id != "delhi" || region.cityChecksum == null) return null
            val document = context.assets.open("regions/delhi/tiles.json").bufferedReader().use { JSONObject(it.readText()) }
            require(document.getString("schema") == "setu.vector-tiles.v1")
            return if (document.getString("sourceSha256") == region.cityChecksum) OfflineTiles(context, document) else null
        }
    }
}
