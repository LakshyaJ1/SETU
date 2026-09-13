package com.setu.navigator.data

import android.content.Context
import android.util.AtomicFile
import org.json.JSONObject
import java.io.File
import java.security.MessageDigest
import java.util.zip.GZIPInputStream

object CompiledRoadGraph {
    /**
     * Checksums of extracted graphs this process has already digested in full.
     *
     * The extracted graph is 238 MB, and hashing it took seconds on every launch's first route.
     * The file lives in app-private storage and nothing outside this object writes it, so once a
     * process has verified it the result holds for that process; a restart verifies again.
     */
    private val verified = HashSet<String>()

    @Synchronized
    fun load(context: Context, region: MapRegion, checkpoint: () -> Unit): RoadGraph? {
        if (region.roadChecksum == null) return null
        val directory = "regions/delhi"
        if (context.assets.list(directory)?.contains("graph.json") != true) return null
        val metadata = context.assets.open("$directory/graph.json").use { source ->
            val bytes = source.readBytes()
            require(bytes.size <= 65536) { "Oversized graph metadata." }
            JSONObject(bytes.toString(Charsets.UTF_8))
        }
        if (metadata.getString("sourceSha256") != region.roadChecksum) return null
        require(metadata.getString("schema") == "setu.road-graph.v1" && metadata.getString("archive") == "roads.bin.gzip")
        val checksum = metadata.getString("sha256")
        val size = metadata.getLong("bytes")
        require(checksum.matches(Regex("[a-f0-9]{64}")) && size in 20..GraphBinary.MAX_BYTES)
        val root = File(context.cacheDir, "compiled-graphs").apply { check(isDirectory || mkdirs()) }
        val target = File(root, "$checksum.bin")
        fun digest(file: File): String {
            val hash = MessageDigest.getInstance("SHA-256")
            file.inputStream().use { input ->
                val buffer = ByteArray(65536)
                while (true) {
                    checkpoint()
                    val count = input.read(buffer)
                    if (count < 0) break
                    hash.update(buffer, 0, count)
                }
            }
            return hash.digest().joinToString("") { "%02x".format(it) }
        }
        val trusted = checksum in verified && target.isFile && target.length() == size
        if (!trusted && (!target.isFile || target.length() != size || digest(target) != checksum)) {
            val atomic = AtomicFile(target)
            val output = atomic.startWrite()
            try {
                val hash = MessageDigest.getInstance("SHA-256")
                var total = 0L
                GZIPInputStream(context.assets.open("$directory/roads.bin.gzip")).use { input ->
                    val buffer = ByteArray(65536)
                    while (true) {
                        checkpoint()
                        val count = input.read(buffer)
                        if (count < 0) break
                        total += count
                        require(total <= size) { "Compiled graph exceeds its declared size." }
                        output.write(buffer, 0, count)
                        hash.update(buffer, 0, count)
                    }
                }
                require(total == size && hash.digest().joinToString("") { "%02x".format(it) } == checksum) { "Compiled graph failed its integrity check." }
                atomic.finishWrite(output)
            } catch (failure: Exception) {
                atomic.failWrite(output)
                throw failure
            }
        }
        verified.add(checksum)
        return GraphBinary.read(target, checkpoint).also {
            require(it.nodeCount == metadata.getInt("nodes") && it.edgeCount == metadata.getInt("edges")) { "Compiled graph counts do not match." }
        }
    }
}
