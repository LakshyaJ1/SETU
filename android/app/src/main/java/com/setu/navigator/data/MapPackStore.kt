package com.setu.navigator.data

import android.content.Context
import android.util.JsonReader
import android.util.JsonToken
import com.setu.navigator.BuildConfig
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.asStateFlow
import org.json.JSONArray
import org.json.JSONObject
import java.io.File
import java.io.InputStream
import java.net.HttpURLConnection
import java.net.URI
import java.security.MessageDigest
import java.time.Instant
import java.util.UUID
import java.util.zip.ZipFile

data class MapRegion(val key: String, val id: String, val revision: Int, val name: String, val summary: String,
                     val bounds: List<Double>, val center: GeoPoint, val previewStart: GeoPoint, val previewLabel: String,
                     val places: List<Place>, val demoDestination: String, val source: String, val attribution: String,
                     val license: String, val sourceUrl: String, val dataTimestamp: String, val limitations: String,
                     val sizeBytes: Long, val directory: File? = null, val assetDirectory: String? = null,
                     val compressedAssets: Boolean = false, val cityBytes: Long? = null, val cityChecksum: String? = null,
                     val roadChecksum: String? = null) {
    val bundled: Boolean get() = directory == null
    fun contains(point: GeoPoint) = point.latitude in bounds[0]..bounds[2] && point.longitude in bounds[1]..bounds[3]
}

class MapPackStore(private val context: Context) {
    private val root = File(context.filesDir, "map-packs").apply { check(isDirectory || mkdirs()) }
    private val preferences = context.getSharedPreferences("setu-maps", Context.MODE_PRIVATE)
    val bundled = decode(JSONObject(context.assets.open("bundled-region.json").bufferedReader().use { it.readText() }), "bundled", null,
        context.assets.open("bengaluru.geojson").use { it.available().toLong() } + context.assets.open("bengaluru-roads.json").use { it.available().toLong() })
    private val included = listOf(bundled, includedDelhi())
    private val mutableRegions = MutableStateFlow(included)
    val regions = mutableRegions.asStateFlow()
    private val mutableMap = MutableStateFlow(OfflineMap(context, bundled))
    val activeMap = mutableMap.asStateFlow()
    private val fileLimits = mapOf("manifest.json" to 65_536L, "city.geojson" to 160L * 1024 * 1024, "roads.json" to 256L * 1024 * 1024)

    private fun includedDelhi(): MapRegion {
        val document = JSONObject(context.assets.open("regions/delhi/manifest.json").bufferedReader().use { it.readText() })
        val compressed = document.optBoolean("compressedAssets")
        val sizes = document.optJSONObject("uncompressedBytes")
        val size = listOf("city.geojson", "roads.json").sumOf { name ->
            if (compressed) requireNotNull(sizes).getLong(name) else context.assets.open("regions/delhi/$name").use { it.available().toLong() }
        }
        val cityBytes = if (compressed) requireNotNull(sizes).getLong("city.geojson") else null
        val checksum = if (compressed) document.getJSONObject("sha256").getString("city.geojson") else null
        require(cityBytes == null || cityBytes in 1..160L * 1024 * 1024)
        require(checksum == null || checksum.matches(Regex("[a-f0-9]{64}")))
        return decode(document, "bundled-delhi", null, size).copy(assetDirectory = "regions/delhi", compressedAssets = compressed,
            cityBytes = cityBytes, cityChecksum = checksum)
    }

    @Synchronized
    fun restore() {
        val installed = root.listFiles().orEmpty().filter { it.isDirectory && it.name.matches(Regex("[a-f0-9-]{36}")) }
            .take(8).mapNotNull { folder -> runCatching { read(folder) }.getOrNull() }
        mutableRegions.value = included + installed.sortedWith(compareBy({ it.name }, { -it.revision }))
        val selected = preferences.getString("active", "bundled")
        val region = mutableRegions.value.firstOrNull { it.key == selected } ?: bundled
        mutableMap.value = runCatching { checkedMap(region) }.getOrElse { OfflineMap(context, bundled) }
    }

    @Synchronized
    fun activate(key: String) {
        val region = mutableRegions.value.singleOrNull { it.key == key } ?: error("This map is no longer installed.")
        val map = checkedMap(region)
        check(preferences.edit().putString("active", key).commit()) { "Could not save the map selection." }
        mutableMap.value = map
    }

    @Synchronized
    fun remove(key: String) {
        val region = mutableRegions.value.singleOrNull { it.key == key } ?: error("This map is no longer installed.")
        require(!region.bundled) { "The included map is kept as your offline fallback." }
        require(mutableMap.value.region.key != key) { "Select another map before removing this one." }
        val folder = checkNotNull(region.directory)
        check(folder.canonicalFile.parentFile == root.canonicalFile && folder.name == key)
        check(folder.deleteRecursively()) { "This map could not be fully removed. Try again." }
        mutableRegions.value = mutableRegions.value.filterNot { it.key == key }
    }

    @Synchronized
    fun import(input: InputStream, checkpoint: () -> Unit = {}): MapRegion {
        require(mutableRegions.value.count { !it.bundled } < 8) { "Eight imported maps are already installed. Remove one first." }
        val temporary = File(context.cacheDir, "map-import-${UUID.randomUUID()}").apply { check(mkdirs()) }
        try {
            val compressed = File(temporary, "archive.zip")
            input.use { source -> compressed.outputStream().use { output ->
                val buffer = ByteArray(65536)
                var size = 0L
                while (true) {
                    checkpoint()
                    val count = source.read(buffer)
                    if (count < 0) break
                    size += count
                    require(size <= 200L * 1024 * 1024) { "The map pack exceeds 200 MB." }
                    output.write(buffer, 0, count)
                }
            } }
            val entries = mutableSetOf<String>()
            ZipFile(compressed).use { archive ->
                require(archive.size() == 3) { "A map pack needs exactly manifest.json, city.geojson and roads.json." }
                val contents = archive.entries()
                while (contents.hasMoreElements()) {
                    checkpoint()
                    val entry = contents.nextElement()
                    val limit = fileLimits[entry.name] ?: error("Unexpected map-pack entry: ${entry.name.take(80)}")
                    require(!entry.isDirectory && entries.add(entry.name)) { "Duplicate or invalid map-pack entry." }
                    var size = 0L
                    archive.getInputStream(entry).use { source -> File(temporary, entry.name).outputStream().use { output ->
                        val buffer = ByteArray(65536)
                        while (true) {
                            checkpoint()
                            val count = source.read(buffer)
                            if (count < 0) break
                            size += count
                            require(size <= limit) { "${entry.name} exceeds the supported map size." }
                            output.write(buffer, 0, count)
                        }
                    } }
                }
            }
            check(compressed.delete()) { "Could not finish checking the map archive." }
            require(entries == fileLimits.keys) { "A map pack needs manifest.json, city.geojson and roads.json." }
            val key = UUID.randomUUID().toString()
            val candidate = read(temporary, key)
            require(mutableRegions.value.none { it.id == candidate.id && it.revision == candidate.revision }) {
                "${candidate.name} revision ${candidate.revision} is already installed."
            }
            require(mutableRegions.value.none { it.id == candidate.id && it.revision > candidate.revision }) { "A newer revision of this map is already installed." }
            verifyHashes(temporary)
            validateCity(File(temporary, "city.geojson"), candidate, checkpoint)
            val graph = CompiledRoadGraph.load(context, candidate, checkpoint)
                ?: MapJson.graph(File(temporary, "roads.json").inputStream(), checkpoint)
            val map = OfflineMap(context, candidate, graph)
            val demo = map.route(candidate.previewStart, candidate.places.single { it.id == candidate.demoDestination }.point)
            require(demo.points.size >= 2 && demo.distanceMeters >= 20) { "The map needs a connected preview route of at least 20 metres." }
            checkpoint()
            val destination = File(root, key)
            check(temporary.renameTo(destination)) { "Could not finish installing the map. Previous maps are unchanged." }
            val installed = candidate.copy(directory = destination)
            mutableRegions.value = mutableRegions.value + installed
            return installed
        } finally {
            if (temporary.exists()) {
                check(temporary.canonicalFile.parentFile == context.cacheDir.canonicalFile)
                temporary.deleteRecursively()
            }
        }
    }

    fun download(address: String, expectedSha256: String, progress: (Long, Long) -> Unit = { _, _ -> }, checkpoint: () -> Unit = {}): MapRegion {
        val uri = URI(address.trim())
        require(uri.userInfo == null && uri.fragment == null && !uri.host.isNullOrBlank()) { "Use a direct map-pack URL without credentials or a fragment." }
        require(uri.scheme == "https" || (BuildConfig.DEBUG && uri.scheme == "http" && uri.host in setOf("127.0.0.1", "localhost", "10.0.2.2"))) {
            "Map downloads require HTTPS. Debug builds also allow the local development server."
        }
        require(expectedSha256.matches(Regex("[a-fA-F0-9]{64}"))) { "Enter the publisher's 64-character SHA-256 checksum." }
        val file = File.createTempFile("map-download-", ".setumap", context.cacheDir)
        val connection = uri.toURL().openConnection() as HttpURLConnection
        try {
            connection.connectTimeout = 10000
            connection.readTimeout = 10000
            connection.instanceFollowRedirects = false
            connection.setRequestProperty("Accept-Encoding", "identity")
            require(connection.responseCode == 200) { "Download returned HTTP ${connection.responseCode}. Use a direct file URL." }
            val total = connection.contentLengthLong
            require(total <= 200L * 1024 * 1024) { "The download exceeds 200 MB." }
            val digest = MessageDigest.getInstance("SHA-256")
            var received = 0L
            connection.inputStream.use { input -> file.outputStream().use { output ->
                val buffer = ByteArray(65536)
                while (true) {
                    checkpoint()
                    val count = input.read(buffer)
                    if (count < 0) break
                    received += count
                    require(received <= 200L * 1024 * 1024) { "The download exceeds 200 MB." }
                    digest.update(buffer, 0, count)
                    output.write(buffer, 0, count)
                    progress(received, total)
                }
            } }
            require(total < 0 || received == total) { "The download was incomplete. Try again." }
            val actual = digest.digest().joinToString("") { "%02x".format(it) }
            require(actual.equals(expectedSha256, ignoreCase = true)) { "Checksum mismatch. The downloaded map was not installed." }
            return file.inputStream().use { import(it, checkpoint) }
        } finally {
            connection.disconnect()
            file.delete()
        }
    }

    private fun checkedMap(region: MapRegion): OfflineMap {
        region.directory?.let(::verifyHashes)
        return OfflineMap(context, region)
    }

    private fun read(folder: File, key: String = folder.name): MapRegion {
        fileLimits.forEach { (name, limit) -> require(File(folder, name).isFile && File(folder, name).length() in 1..limit) { "Missing or oversized $name." } }
        return decode(document(File(folder, "manifest.json")), key, folder, fileLimits.keys.sumOf { File(folder, it).length() })
    }

    private fun verifyHashes(folder: File) {
        val document = document(File(folder, "manifest.json"))
        val expected = document.getJSONObject("sha256")
        listOf("city.geojson", "roads.json").forEach { name ->
            val digest = MessageDigest.getInstance("SHA-256")
            File(folder, name).inputStream().use { input ->
                val buffer = ByteArray(65536)
                while (true) { val count = input.read(buffer); if (count < 0) break; digest.update(buffer, 0, count) }
            }
            require(expected.getString(name).equals(digest.digest().joinToString("") { "%02x".format(it) }, ignoreCase = true)) { "$name failed its integrity check." }
        }
    }

    private fun decode(document: JSONObject, key: String, directory: File?, size: Long): MapRegion {
        require(document.getString("schema") == "setu.map.v1") { "Unsupported map-pack format." }
        fun text(name: String, limit: Int = 120) = document.getString(name).also { require(it.isNotBlank() && it.length <= limit && it.none(Char::isISOControl)) { "Invalid map field: $name." } }
        val id = text("id", 60).also { require(it.matches(Regex("[a-z0-9][a-z0-9-]*"))) }
        val revision = document.get("revision").also { require(it is Int && it in 1..1000000) { "Use a positive integer map revision." } } as Int
        val coordinates = document.getJSONArray("bounds")
        require(coordinates.length() == 4)
        require((0..3).all { coordinates.get(it) is Number }) { "Map bounds must be numbers." }
        val bounds = (0..3).map { coordinates.getDouble(it) }
        GeoPoint(bounds[0], bounds[1]); GeoPoint(bounds[2], bounds[3])
        require(bounds[2] > bounds[0] && bounds[3] > bounds[1] && bounds[2] - bounds[0] <= 4 && bounds[3] - bounds[1] <= 4) { "Use a regional map spanning at most four degrees." }
        fun included(point: GeoPoint) = point.latitude in bounds[0]..bounds[2] && point.longitude in bounds[1]..bounds[3]
        val center = point(document.getJSONArray("center")).also { require(included(it)) }
        val preview = point(document.getJSONArray("previewStart")).also { require(included(it)) }
        val locations = document.getJSONArray("places")
        require(locations.length() in 2..2000)
        val places = (0 until locations.length()).map { index ->
            val place = locations.getJSONObject(index)
            val placeId = place.getString("id").also { require(it.matches(Regex("[a-z0-9-]{1,60}"))) }
            val name = place.getString("name").also { require(it.isNotBlank() && it.length <= 100) }
            val detail = place.getString("detail").also { require(it.length <= 200) }
            Place(placeId, name, detail, point(place.getJSONArray("point")).also { require(included(it)) })
        }
        require(places.map { it.id }.distinct().size == places.size)
        val demo = text("demoDestination", 60).also { require(places.any { place -> place.id == it }) }
        val sourceUrl = text("sourceUrl", 500).also { value ->
            val address = URI(value)
            require(address.scheme == "https" && !address.host.isNullOrBlank() && address.userInfo == null && address.fragment == null)
        }
        val timestamp = text("dataTimestamp", 40).also { Instant.parse(it) }
        return MapRegion(key, id, revision, text("name"), text("summary", 300), bounds, center, preview, text("previewLabel", 80),
            places, demo, text("source"), text("attribution", 80), text("license"), sourceUrl, timestamp, text("limitations", 500), size, directory,
            cityBytes = directory?.resolve("city.geojson")?.length(), cityChecksum = document.optJSONObject("sha256")?.optString("city.geojson"),
            roadChecksum = document.optJSONObject("sha256")?.optString("roads.json"))
    }

    private fun point(coordinates: JSONArray): GeoPoint {
        require(coordinates.length() == 2) { "Map coordinates must be longitude, latitude pairs." }
        require(coordinates.get(0) is Number && coordinates.get(1) is Number) { "Map coordinates must be numbers." }
        return GeoPoint(coordinates.getDouble(1), coordinates.getDouble(0))
    }

    private fun validateCity(file: File, region: MapRegion, checkpoint: () -> Unit) {
        var featureCount = 0
        var collectionType = ""
        val glyphRanges = context.assets.list("fonts/Noto Sans Regular").orEmpty().map { it.substringBefore('-').toInt() }.toSet()
        var points = 0
        var inside = false
        fun coordinates(values: JSONArray, depth: Int) {
            require(depth in 0..3)
            if (depth == 0) { inside = region.contains(point(values)) || inside; points++; require(points <= 6_000_000); return }
            require(values.length() > 0) { "Map geometry cannot be empty." }
            for (index in 0 until values.length()) coordinates(values.getJSONArray(index), depth - 1)
        }
        fun validate(feature: JSONObject) {
            require(++featureCount <= 150_000) { "Unsupported number of map features." }
            if (featureCount % 100 == 0) checkpoint()
            require(feature.getString("type") == "Feature")
            val properties = feature.getJSONObject("properties")
            val kind = properties.getString("kind")
            require(kind in setOf("road", "park", "water", "building"))
            val name = properties.optString("name")
            require(name.length <= 500)
            require(name.codePoints().toArray().all { (it / 256 * 256) in glyphRanges }) { "This map uses labels without bundled offline glyphs. Supply transliterated labels for this build." }
            val geometry = feature.getJSONObject("geometry")
            val type = geometry.getString("type")
            require(if (kind == "road") type in setOf("LineString", "MultiLineString") else type in setOf("Polygon", "MultiPolygon")) { "Map geometry does not match its visual kind." }
            val depth = when (type) { "LineString" -> 1; "Polygon", "MultiLineString" -> 2; "MultiPolygon" -> 3; else -> error("Unsupported map geometry.") }
            val values = geometry.getJSONArray("coordinates")
            coordinates(values, depth)
            fun segments(parts: JSONArray, level: Int) {
                if (level > 1) { repeat(parts.length()) { segments(parts.getJSONArray(it), level - 1) }; return }
                require(parts.length() >= if (kind == "road") 2 else 4) { "Map geometry has too few points." }
                if (kind != "road") require(point(parts.getJSONArray(0)) == point(parts.getJSONArray(parts.length() - 1))) { "Polygon rings must be closed." }
            }
            segments(values, depth)
        }
        JsonReader(file.reader()).use { reader ->
            val fields = mutableSetOf<String>()
            reader.beginObject()
            while (reader.hasNext()) {
                val field = reader.nextName()
                require(fields.add(field)) { "Duplicate map JSON field." }
                when (field) {
                    "type" -> collectionType = reader.nextString()
                    "features" -> {
                        reader.beginArray()
                        while (reader.hasNext()) validate(MapJson.objectValue(reader))
                        reader.endArray()
                    }
                    else -> MapJson.skip(reader)
                }
            }
            reader.endObject()
            require(reader.peek() == JsonToken.END_DOCUMENT) { "Unexpected data after map JSON." }
        }
        require(collectionType == "FeatureCollection" && featureCount > 0) { "The visual map needs a feature collection." }
        require(inside) { "The visual map has no coordinates inside its stated coverage." }
    }

    private fun document(file: File): JSONObject {
        JsonReader(file.reader()).use { reader ->
            fun value(depth: Int) {
                require(depth <= 16) { "Map JSON is nested too deeply." }
                when (reader.peek()) {
                    JsonToken.BEGIN_OBJECT -> { reader.beginObject(); while (reader.hasNext()) { reader.nextName(); value(depth + 1) }; reader.endObject() }
                    JsonToken.BEGIN_ARRAY -> { reader.beginArray(); while (reader.hasNext()) value(depth + 1); reader.endArray() }
                    JsonToken.STRING, JsonToken.NUMBER -> reader.nextString()
                    JsonToken.BOOLEAN -> reader.nextBoolean()
                    JsonToken.NULL -> reader.nextNull()
                    else -> error("Invalid map JSON.")
                }
            }
            require(reader.peek() == JsonToken.BEGIN_OBJECT) { "Map JSON needs an object." }
            value(0)
            require(reader.peek() == JsonToken.END_DOCUMENT) { "Unexpected data after map JSON." }
        }
        return JSONObject(file.readText())
    }
}
