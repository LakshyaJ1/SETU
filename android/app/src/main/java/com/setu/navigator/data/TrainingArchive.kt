package com.setu.navigator.data

import org.json.JSONArray
import org.json.JSONObject
import java.io.File
import java.io.OutputStream
import java.security.MessageDigest
import java.util.TreeMap
import java.util.zip.ZipEntry
import java.util.zip.ZipOutputStream

interface CollectionReplay : AutoCloseable {
    val protocolDescription: String get() = "Custom replay; protocol unspecified"
    fun accept(record: JSONObject): JSONObject?
}

object TrainingArchive {
    private const val SECOND = 1_000_000_000L
    private const val MAX_DURATION = 6 * 60 * 60 * SECOND

    private class Samples {
        var count = 0
        var first = 0L
        var last = 0L
        var gap = 0L
        var invalid = false
        fun add(record: JSONObject) {
            val timestamp = record.getLong("tNs")
            val values = record.optJSONArray("values")
            invalid = invalid || values == null || values.length() < 3 ||
                (0..2).any { !values.optDouble(it).isFinite() } || (count > 0 && timestamp <= last)
            if (count == 0) first = timestamp else gap = maxOf(gap, timestamp - last)
            last = timestamp
            count++
        }
        fun json(start: Long, end: Long): JSONObject = JSONObject().put("count", count)
            .put("firstNs", first).put("lastNs", last).put("invalid", invalid)
            .put("maxGapNs", if (count == 0) end - start else maxOf(gap, first - start, end - last))
    }

    private class Epoch {
        val acceleration = Samples()
        val gyroscope = Samples()
    }

    fun export(source: File, destination: OutputStream, replay: CollectionReplay? = null,
               checkCancelled: () -> Unit = {}): JSONObject {
        require(source.isFile && source.length() <= 2L * 1024 * 1024 * 1024) { "Recording is missing or exceeds the 2 GB training-export limit." }
        val originalSize = source.length()
        val originalModified = source.lastModified()
        val epochs = TreeMap<Long, Epoch>()
        val references = TreeMap<Long, JSONObject>()
        val fused = TreeMap<Long, JSONObject>()
        val shadow = TreeMap<Long, JSONObject>()
        var header: JSONObject? = null
        var ending: JSONObject? = null
        var lastNs = 0L
        var records = 0L
        var malformedTail = false
        var configurationChanged = false
        var hasReferences = false
        source.bufferedReader().use { reader ->
            while (true) {
                checkCancelled()
                val line = readLine(reader) ?: break
                val record = try { JSONObject(line) } catch (failure: Exception) {
                    if (!reader.ready() && header != null) { malformedTail = true; break }
                    throw IllegalArgumentException("Invalid recording JSON.", failure)
                }
                if (header == null) {
                    require(record.optString("schema") == "setu.log.v1" && record.optString("clock") == "elapsedRealtimeNanos") {
                        "This recording has no supported monotonic clock. Export the original instead."
                    }
                    require(record.getLong("startedAtNs") >= 0)
                    header = record
                    replay?.accept(record)
                    continue
                }
                require(ending == null) { "Recording has data after its end marker." }
                val timestamp = record.getLong("tNs")
                val start = header.getLong("startedAtNs")
                require(timestamp >= 0 && timestamp - start <= MAX_DURATION) { "Invalid timestamp or recording longer than six hours." }
                if (timestamp < start) continue
                lastNs = maxOf(lastNs, timestamp)
                records++
                val epoch = ((timestamp - start).coerceAtLeast(1) - 1) / SECOND
                when (record.optString("type")) {
                    "accelerometer" -> epochs.getOrPut(epoch) { Epoch() }.acceleration.add(record)
                    "gyroscope" -> epochs.getOrPut(epoch) { Epoch() }.gyroscope.add(record)
                    "gnss_reference" -> {
                        if (!hasReferences) references.clear()
                        hasReferences = true
                        if (record.optString("provider") == "gps") references[timestamp] = record
                    }
                    "pose" -> if (!hasReferences) references[timestamp] = record
                    "native_pose" -> fused[epoch] = record
                    "collection_change" -> configurationChanged = true
                    "end" -> ending = record
                }
                replay?.accept(record)?.let { shadow[((it.getLong("tNs") - start).coerceAtLeast(1) - 1) / SECOND] = it }
            }
        }
        val metadata = requireNotNull(header) { "The recording is empty." }
        val started = metadata.getLong("startedAtNs")
        lastNs = maxOf(started, lastNs)
        val issues = mutableListOf<String>()
        if (ending == null || malformedTail) issues.add("incomplete_recording")
        if (ending?.optLong("droppedRecords", -1) != 0L) issues.add("dropped_or_unknown_records")
        if (metadata.optBoolean("synthetic")) issues.add("synthetic_recording")
        if (configurationChanged) issues.add("configuration_changed")
        val collection = metadata.optJSONObject("collection")
        if (collection == null) issues.add("legacy_metadata")
        else {
            if (collection.optString("mount") != "fixed") issues.add("mount_unconfirmed")
            if (collection.optString("vehicle") != "Car") issues.add("vehicle_outside_current_speed_model")
        }
        val manifest = JSONObject().put("schema", "setu.training-bundle.v1").put("recording", metadata)
            .put("issues", JSONArray(issues)).put("records", records)
            .put("complete", ending != null && !malformedTail).put("droppedRecords", ending?.optLong("droppedRecords", -1) ?: -1)
            .put("reference", "Android GNSS observations; noisy reference, not survey ground truth")
            .put("alignment", "1 Hz epoch ends; latest observation at or before epoch, maximum age 1.5 s; no coordinate interpolation")
            .put("shadowProtocol", replay?.protocolDescription ?: JSONObject.NULL)
            .put("shadowComparison", "Evaluation only: interpolate two quality-checked GNSS fixes bracketing the estimate, at most 1.5 s and 100 m apart; no extrapolation or estimator feedback")
            .put("deploymentApproved", false)
        val files = JSONObject()
        var referenceSeconds = 0
        var pairedSeconds = 0
        ZipOutputStream(destination).use { zip ->
            fun entry(name: String, write: (OutputStream) -> Unit) {
                zip.putNextEntry(ZipEntry(name))
                val digest = MessageDigest.getInstance("SHA-256")
                var size = 0L
                val output = object : OutputStream() {
                    override fun write(value: Int) { zip.write(value); digest.update(value.toByte()); size++ }
                    override fun write(bytes: ByteArray, offset: Int, length: Int) {
                        zip.write(bytes, offset, length); digest.update(bytes, offset, length); size += length
                    }
                }
                write(output)
                zip.closeEntry()
                files.put(name, JSONObject().put("bytes", size).put("sha256", digest.digest().joinToString("") { "%02x".format(it) }))
            }
            entry("raw.setulog") { output ->
                source.inputStream().use { input ->
                    val buffer = ByteArray(65536)
                    while (true) {
                        checkCancelled()
                        val count = input.read(buffer)
                        if (count < 0) break
                        output.write(buffer, 0, count)
                    }
                }
            }
            entry("aligned.jsonl") { output ->
                for (index in 0 until (lastNs - started) / SECOND) {
                    checkCancelled()
                    val end = started + (index + 1) * SECOND
                    val epoch = epochs[index] ?: Epoch()
                    fun recent(record: JSONObject?): JSONObject? = record?.takeIf { end - it.getLong("tNs") in 0..1_500_000_000L }
                    val reference = recent(references.floorEntry(end)?.value)
                    val native = recent(fused.floorEntry(index)?.value)
                    val prediction = recent(shadow.floorEntry(index)?.value)
                    val reasons = referenceIssues(reference).toMutableList()
                    val acceleration = epoch.acceleration.json(end - SECOND, end)
                    val gyroscope = epoch.gyroscope.json(end - SECOND, end)
                    for ((kind, samples) in listOf("accelerometer" to acceleration, "gyroscope" to gyroscope)) {
                        if (samples.getBoolean("invalid") || samples.getInt("count") < 50 || samples.getLong("maxGapNs") > 50_000_000L) reasons.add("${kind}_gap_or_rate")
                    }
                    if (referenceIssues(reference).isEmpty()) referenceSeconds++
                    if (reasons.isEmpty()) pairedSeconds++
                    val shadowPose = prediction?.optJSONObject("pose")
                    val comparison = if (prediction?.optString("phase") == "gps_withheld" && shadowPose != null)
                        comparisonReference(references, shadowPose.getLong("tNs")) else null
                    val errorMeters = comparison?.let { GeoPoint(shadowPose!!.getDouble("latitude"), shadowPose.getDouble("longitude"))
                        .distanceTo(GeoPoint(it.getDouble("latitude"), it.getDouble("longitude"))) }
                    val row = JSONObject().put("schema", "setu.aligned.v1").put("tNs", end)
                        .put("accelerometer", acceleration).put("gyroscope", gyroscope)
                        .put("gpsReference", reference ?: JSONObject.NULL)
                        .put("gpsAgeNs", reference?.let { end - it.getLong("tNs") } ?: JSONObject.NULL)
                        .put("fusedEstimate", native ?: JSONObject.NULL).put("shadowEstimate", prediction ?: JSONObject.NULL)
                        .put("shadowReferenceErrorMeters", errorMeters ?: JSONObject.NULL)
                        .put("shadowComparisonReference", comparison ?: JSONObject.NULL)
                        .put("shadowComparisonAvailable", comparison != null)
                        .put("issues", JSONArray(reasons)).put("sessionIssues", JSONArray(issues))
                    output.write((row.toString() + "\n").toByteArray(Charsets.UTF_8))
                }
            }
            require(source.length() == originalSize && source.lastModified() == originalModified) { "Recording changed during export. Stop recording and retry." }
            manifest.put("files", files).put("referenceSeconds", referenceSeconds).put("pairedSeconds", pairedSeconds)
                .put("durationSeconds", (lastNs - started) / SECOND)
            zip.putNextEntry(ZipEntry("manifest.json"))
            zip.write(manifest.toString(2).toByteArray(Charsets.UTF_8))
            zip.closeEntry()
        }
        return manifest
    }

    internal fun comparisonReference(references: java.util.NavigableMap<Long, JSONObject>, timestamp: Long): JSONObject? {
        val before = references.floorEntry(timestamp)?.value ?: return null
        val after = references.ceilingEntry(timestamp)?.value ?: return null
        if (referenceIssues(before).isNotEmpty() || referenceIssues(after).isNotEmpty()) return null
        val start = before.getLong("tNs")
        val end = after.getLong("tNs")
        if (timestamp !in start..end || end - start !in 0..1_500_000_000L) return null
        val origin = GeoPoint(before.getDouble("latitude"), before.getDouble("longitude"))
        val destination = GeoPoint(after.getDouble("latitude"), after.getDouble("longitude"))
        if (origin.distanceTo(destination) > 100.0) return null
        val fraction = if (end == start) 0.0 else (timestamp - start).toDouble() / (end - start)
        val longitudeDelta = (destination.longitude - origin.longitude + 540.0) % 360.0 - 180.0
        return JSONObject().put("tNs", timestamp).put("fromNs", start).put("toNs", end)
            .put("method", if (start == end) "exact_timestamp" else "linear_interpolation")
            .put("latitude", origin.latitude + fraction * (destination.latitude - origin.latitude))
            .put("longitude", (origin.longitude + fraction * longitudeDelta + 540.0) % 360.0 - 180.0)
            .put("accuracyMeters", maxOf(before.getDouble("accuracyMeters"), after.getDouble("accuracyMeters")))
    }

    fun referenceIssues(reference: JSONObject?): List<String> {
        if (reference == null) return listOf("gps_missing_or_stale")
        val issues = mutableListOf<String>()
        if (reference.optString("provider") != "gps") issues.add("gps_provider_unverified")
        if (reference.opt("mock") != false) issues.add("mock_or_unknown_origin")
        if (reference.optDouble("latitude") !in -90.0..90.0 || reference.optDouble("longitude") !in -180.0..180.0) issues.add("invalid_coordinates")
        if (reference.optDouble("accuracyMeters") !in 0.0..10.0) issues.add("gps_accuracy")
        if (reference.optDouble("speedMps") !in 0.0..45.0 || reference.optDouble("speedAccuracyMps") !in 0.0..1.5) issues.add("gps_speed_quality")
        return issues
    }

    private fun readLine(reader: java.io.Reader): String? {
        val line = StringBuilder()
        while (true) {
            val character = reader.read()
            if (character < 0) return line.toString().takeIf { it.isNotEmpty() }
            if (character == '\n'.code) return line.toString()
            require(line.length < 65536) { "Recording contains an oversized record." }
            line.append(character.toChar())
        }
    }
}
