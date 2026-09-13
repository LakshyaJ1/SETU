package com.setu.navigator.data

import android.content.Context
import android.net.Uri
import org.json.JSONArray
import org.json.JSONObject
import java.io.File
import java.security.MessageDigest
import java.util.zip.ZipInputStream

internal class OfflineTiles(private val context: Context, private val metadata: JSONObject) {
    private data class Tile(val bytes: Long, val checksum: String)

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
        val expectedIndex = metadata.getString("indexSha256")
        require(expectedIndex.matches(Regex("[a-f0-9]{64}")))
        val expectedCount = metadata.getInt("tileCount").also { require(it in 1..25000) }
        val expectedSize = metadata.getLong("uncompressedBytes").also { require(it in 1..512L * 1024 * 1024) }
        val indexBytes = context.assets.open("regions/delhi/tile-index.json").use { input ->
            val output = java.io.ByteArrayOutputStream()
            val buffer = ByteArray(65536)
            while (true) {
                val count = input.read(buffer)
                if (count < 0) break
                require(output.size() + count <= 4 * 1024 * 1024) { "Oversized tile inventory." }
                output.write(buffer, 0, count)
            }
            output.toByteArray()
        }
        require(MessageDigest.getInstance("SHA-256").digest(indexBytes).hex() == expectedIndex) { "Tile inventory failed its integrity check." }
        val index = JSONObject(indexBytes.toString(Charsets.UTF_8))
        require(index.getString("schema") == "setu.tile-index.v1" && index.getString("archiveSha256") == checksum)
        val documents = index.getJSONArray("tiles")
        require(documents.length() == expectedCount)
        val tiles = LinkedHashMap<String, Tile>()
        var totalBytes = 0L
        for (position in 0 until documents.length()) {
            val tile = documents.getJSONArray(position)
            require(tile.length() == 3)
            val name = tile.getString(0)
            require(name.matches(Regex("(?:[6-9]|1[0-3])/[0-9]{1,4}/[0-9]{1,4}\\.pbf")))
            val coordinates = name.removeSuffix(".pbf").split('/').map(String::toInt)
            require(coordinates[1] < (1 shl coordinates[0]) && coordinates[2] < (1 shl coordinates[0]))
            val size = tile.getLong(1).also { require(it in 1..500000) }
            val hash = tile.getString(2).also { require(it.matches(Regex("[a-f0-9]{64}"))) }
            require(tiles.put(name, Tile(size, hash)) == null) { "Duplicate tile inventory entry." }
            totalBytes += size
        }
        require(totalBytes == expectedSize)
        val root = File(context.filesDir, "offline-vector-maps").apply { check(isDirectory || mkdirs()) }
        val destination = File(root, checksum)
        val marker = File(destination, "complete")
        // Re-hashing all 11,159 tiles (48.5 MB) costs real time and ran on every style load, so a
        // theme change or a map reselection paid it again. Once this process has verified every tile
        // of this exact archive, and the completion marker is still present, the directory is
        // trusted for the rest of the process; a restart re-verifies in full. Nothing outside this
        // class writes there, so the integrity contract in docs/20 is unchanged across launches.
        if (checksum in verifiedRoots && marker.isFile && marker.length() == 64L) return@synchronized destination
        val verificationBuffer = ByteArray(65536)
        val verificationHash = MessageDigest.getInstance("SHA-256")
        val intact = runCatching {
            marker.isFile && marker.length() == 64L && marker.readText() == expectedIndex && tiles.all { (name, tile) ->
                val file = File(destination, name)
                file.isFile && file.length() == tile.bytes && file.inputStream().use { input ->
                    verificationHash.reset()
                    while (true) {
                        val count = input.read(verificationBuffer)
                        if (count < 0) break
                        verificationHash.update(verificationBuffer, 0, count)
                    }
                    verificationHash.digest().hex() == tile.checksum
                }
            }
        }.getOrDefault(false)
        if (intact) { verifiedRoots.add(checksum); return@synchronized destination }
        val digest = MessageDigest.getInstance("SHA-256")
        context.assets.open(ARCHIVE).use { input ->
            val buffer = ByteArray(65536)
            while (true) {
                val count = input.read(buffer)
                if (count < 0) break
                digest.update(buffer, 0, count)
            }
        }
        check(digest.digest().hex() == checksum) { "Offline tiles failed their integrity check." }
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
                    val expected = requireNotNull(tiles[entry.name]) { "Unexpected offline tile." }
                    require(!entry.isDirectory)
                    require(entries.add(entry.name) && ++count <= expectedCount)
                    val target = File(staging, entry.name)
                    check(target.canonicalPath.startsWith(staging.canonicalPath + File.separator))
                    check(target.parentFile!!.isDirectory || target.parentFile!!.mkdirs())
                    var tileSize = 0
                    val tileDigest = MessageDigest.getInstance("SHA-256")
                    target.outputStream().buffered().use { output ->
                        while (true) {
                            val length = archive.read(buffer)
                            if (length < 0) break
                            tileSize += length
                            size += length
                            require(tileSize <= expected.bytes && size <= expectedSize)
                            tileDigest.update(buffer, 0, length)
                            output.write(buffer, 0, length)
                        }
                    }
                    require(tileSize.toLong() == expected.bytes && tileDigest.digest().hex() == expected.checksum) { "Offline tile failed its integrity check." }
                    archive.closeEntry()
                }
            }
            check(count == expectedCount && size == expectedSize) { "The offline tile archive is incomplete." }
            File(staging, "complete").writeText(expectedIndex)
            if (destination.exists()) {
                check(destination.canonicalFile.parentFile == root.canonicalFile)
                check(destination.deleteRecursively())
            }
            check(staging.renameTo(destination)) { "Could not prepare the offline map. Check available storage." }
            verifiedRoots.add(checksum)
            destination
        } finally {
            if (staging.exists()) staging.deleteRecursively()
        }
    }

    companion object {
        private fun ByteArray.hex(): String {
            val digits = "0123456789abcdef"
            return buildString(size * 2) { for (byte in this@hex) { val value = byte.toInt() and 255; append(digits[value ushr 4]); append(digits[value and 15]) } }
        }
        private val lock = Any()
        /** Archive checksums whose published tile directory this process has verified in full. */
        private val verifiedRoots = HashSet<String>()
        private const val ARCHIVE = "regions/delhi/city-tiles.zip"
        fun matching(context: Context, region: MapRegion): OfflineTiles? {
            if (region.id != "delhi" || region.cityChecksum == null) return null
            val document = context.assets.open("regions/delhi/tiles.json").bufferedReader().use { JSONObject(it.readText()) }
            require(document.getString("schema") == "setu.vector-tiles.v1")
            return if (document.getString("sourceSha256") == region.cityChecksum) OfflineTiles(context, document) else null
        }
    }
}
