package com.setu.navigator.data

import android.content.Context
import android.util.AtomicFile
import org.json.JSONArray
import org.json.JSONObject
import java.io.File
import java.io.InputStream
import java.io.OutputStream
import java.io.Reader
import java.util.UUID

class TripStore(context: Context) {
    private val directory = File(context.filesDir, "trips").apply { mkdirs() }
    fun logFile(id: String): File {
        require(runCatching { UUID.fromString(id) }.isSuccess)
        return File(directory, "$id.setulog")
    }

    fun all(): List<Trip> = directory.listFiles().orEmpty().filter { it.extension == "json" }
        .mapNotNull { file -> runCatching { AtomicFile(file).openRead().bufferedReader().use { decode(JSONObject(it.readText())) } }.getOrNull() }
        .sortedByDescending { it.startedAtMs }

    fun save(trip: Trip) {
        val document = JSONObject().put("id", trip.id).put("name", trip.name)
            .put("startedAtMs", trip.startedAtMs).put("durationMs", trip.durationMs)
            .put("distanceMeters", trip.distanceMeters).put("sampleCount", trip.sampleCount)
            .put("synthetic", trip.synthetic).put("recovered", trip.recovered)
            .put("points", JSONArray().apply { trip.points.forEach { put(encodePose(it)) } })
        val file = AtomicFile(File(directory, "${trip.id}.json"))
        val stream = file.startWrite()
        try {
            stream.write(document.toString().toByteArray(Charsets.UTF_8))
            file.finishWrite(stream)
        } catch (error: Exception) {
            file.failWrite(stream)
            throw error
        }
    }

    fun delete(trip: Trip) {
        val files = listOf(logFile(trip.id), File(directory, "${trip.id}.json"),
            File(directory, "${trip.id}.json.bak"), File(directory, "${trip.id}.json.new"))
        files.forEach { file -> require(!file.exists() || file.delete()) { "This recording could not be fully deleted. Please try again." } }
    }

    fun export(trip: Trip, destination: OutputStream) {
        val source = logFile(trip.id)
        require(source.isFile) { "The original recording is missing." }
        if (!trip.recovered) source.inputStream().use { it.copyTo(destination) }
        else source.bufferedReader().use { reader ->
            while (true) {
                val line = readBoundedLine(reader) ?: break
                if (!line.second && runCatching { JSONObject(line.first) }.isFailure) break
                destination.write((line.first + "\n").toByteArray(Charsets.UTF_8))
            }
        }
    }

    fun import(source: InputStream): Trip {
        val id = UUID.randomUUID().toString()
        val target = logFile(id)
        try {
            target.outputStream().use { destination ->
                val buffer = ByteArray(8192)
                var total = 0L
                while (true) {
                    val count = source.read(buffer)
                    if (count < 0) break
                    total += count
                    require(total <= 100L * 1024 * 1024) { "This recording exceeds the 100 MB import limit." }
                    destination.write(buffer, 0, count)
                }
            }
            val trip = readRecording(target, id, recovered = false)
            save(trip)
            return trip
        } catch (error: Exception) {
            target.delete()
            throw error
        }
    }

    fun recoverIncomplete(excludedId: () -> String = { "" }): Int {
        var recovered = 0
        directory.listFiles().orEmpty().filter { it.extension == "setulog" }.forEach { file ->
            val id = file.nameWithoutExtension
            if (id != excludedId() && !File(directory, "$id.json").exists()) {
                runCatching {
                    logFile(id)
                    val trip = readRecording(file, id, recovered = true)
                    if (id != excludedId()) { save(trip); recovered++ }
                }
            }
        }
        return recovered
    }

    private fun readRecording(file: File, id: String, recovered: Boolean): Trip {
        val points = mutableListOf<Pose>()
        var samples = 0L
        var firstNs: Long? = null
        var lastNs = 0L
        var metadata: JSONObject? = null
        file.bufferedReader().use { reader ->
            var number = 0
            while (true) {
                val line = readBoundedLine(reader) ?: break
                number++
                val record = try { JSONObject(line.first) } catch (error: Exception) {
                    if (recovered && !line.second && metadata != null) break
                    throw IllegalArgumentException("Invalid JSON in recording line $number.", error)
                }
                if (number == 1) {
                    require(record.optString("schema") == "setu.log.v1") { "Unsupported recording format. Expected SETU log v1." }
                    require(record.optString("trajectoryStream", "pose") in listOf("pose", "track_pose")) { "Unsupported trajectory stream." }
                    metadata = record
                    if (record.has("startedAtNs")) firstNs = record.getLong("startedAtNs").also { require(it >= 0) }
                    continue
                }
                require(record.has("tNs")) { "Recording line $number has no timestamp." }
                val timestamp = record.getLong("tNs")
                require(timestamp >= 0) { "Recording timestamps cannot be negative." }
                if (firstNs == null) firstNs = timestamp
                lastNs = maxOf(lastNs, timestamp)
                if (record.optString("type") != "end") samples++
                if (record.optString("type") == metadata?.optString("trajectoryStream", "pose")) {
                    val pose = decodePose(record)
                    val previous = points.lastOrNull()
                    require(previous == null || pose.timestampNs >= previous.timestampNs) { "Trajectory positions must be in timestamp order." }
                    if (previous == null || pose.timestampNs > previous.timestampNs) points.add(pose)
                    else require(pose.point == previous.point) { "Two different trajectory positions share a timestamp." }
                }
            }
        }
        val header = requireNotNull(metadata) { "The selected recording is empty." }
        val distance = trajectoryDistance(points)
        return Trip(id, header.optString("name", "Imported drive").take(100),
            header.optLong("startedAtMs", System.currentTimeMillis()),
            (lastNs - (firstNs ?: lastNs)).coerceAtLeast(0) / 1_000_000,
            distance, samples, points, header.optBoolean("synthetic"), recovered)
    }

    private fun readBoundedLine(reader: Reader): Pair<String, Boolean>? {
        val line = StringBuilder()
        while (true) {
            val character = reader.read()
            if (character < 0) return if (line.isEmpty()) null else line.toString().trimEnd('\r') to false
            if (character == '\n'.code) return line.toString().trimEnd('\r') to true
            require(line.length < 65536) { "Recording contains an oversized record." }
            line.append(character.toChar())
        }
    }

    private fun decode(document: JSONObject): Trip {
        val records = document.getJSONArray("points")
        return Trip(document.getString("id"), document.getString("name"), document.getLong("startedAtMs"),
            document.getLong("durationMs"), document.getDouble("distanceMeters"), document.getLong("sampleCount"),
            (0 until records.length()).map { decodePose(records.getJSONObject(it)) },
            document.optBoolean("synthetic"), document.optBoolean("recovered"))
    }

    companion object {
        fun encodePose(pose: Pose): JSONObject = JSONObject().put("type", "pose")
            .put("latitude", pose.point.latitude).put("longitude", pose.point.longitude)
            .put("measurementVersion", 1)
            .put("speedMps", pose.speedMps ?: JSONObject.NULL).put("bearing", pose.bearing ?: JSONObject.NULL)
            .put("accuracyMeters", pose.accuracyMeters ?: JSONObject.NULL).put("tNs", pose.timestampNs).put("source", pose.source)
            .put("altitudeMeters", pose.altitudeMeters ?: JSONObject.NULL)
            .put("verticalAccuracyMeters", pose.verticalAccuracyMeters ?: JSONObject.NULL)
            .put("speedAccuracyMps", pose.speedAccuracyMps ?: JSONObject.NULL)
            .put("bearingAccuracyDegrees", pose.bearingAccuracyDegrees ?: JSONObject.NULL)
            .put("mock", pose.mock ?: JSONObject.NULL)
            .put("filterRadius95Meters", pose.filterRadius95Meters ?: JSONObject.NULL)

        fun decodePose(document: JSONObject): Pose {
            val version = if (document.has("measurementVersion")) document.get("measurementVersion") else 0
            require(version == 0 || version == 1) { "Unsupported GPS measurement version." }
            fun optional(name: String, range: ClosedFloatingPointRange<Double>? = null): Double? {
                if (document.isNull(name)) return null
                val number = document.get(name)
                require(number is Number) { "$name must be a number or null." }
                val value = number.toDouble()
                require(value.isFinite() && (range == null || value in range)) { "Invalid $name." }
                return value
            }
            fun legacyOptional(name: String, range: ClosedFloatingPointRange<Double>): Double? =
                optional(name, range)?.takeUnless { version == 0 && it == 0.0 }
            val speed = legacyOptional("speedMps", 0.0..Double.MAX_VALUE)
            val bearing = legacyOptional("bearing", 0.0..360.0)?.also { require(it < 360) }
            val altitude = optional("altitudeMeters")
            val mock = document.opt("mock").takeUnless { it == null || it == JSONObject.NULL }
            require(mock == null || mock is Boolean) { "mock must be a boolean or null." }
            return Pose(
                point = GeoPoint(document.getDouble("latitude"), document.getDouble("longitude")),
                speedMps = speed, bearing = bearing, accuracyMeters = legacyOptional("accuracyMeters", 0.0..Double.MAX_VALUE),
                timestampNs = document.getLong("tNs").also { require(it >= 0) }, source = document.optString("source", "Imported"),
                altitudeMeters = altitude,
                verticalAccuracyMeters = optional("verticalAccuracyMeters", 0.0..Double.MAX_VALUE)?.takeIf { altitude != null },
                speedAccuracyMps = optional("speedAccuracyMps", 0.0..Double.MAX_VALUE)?.takeIf { speed != null },
                bearingAccuracyDegrees = optional("bearingAccuracyDegrees", 0.0..Double.MAX_VALUE)?.takeIf { bearing != null },
                mock = mock,
                filterRadius95Meters = optional("filterRadius95Meters", 0.0..Double.MAX_VALUE),
            )
        }
    }
}
