package com.setu.navigator

import android.os.SystemClock
import androidx.test.core.app.ActivityScenario
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import com.setu.navigator.data.GnssShadowReplay
import com.setu.navigator.data.TrainingArchive
import com.setu.navigator.data.CollectionMetadata
import com.setu.navigator.data.GeoPoint
import org.json.JSONArray
import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Assume.assumeTrue
import org.junit.Test
import org.junit.runner.RunWith
import java.io.File
import java.security.MessageDigest
import java.util.TreeMap
import java.util.zip.ZipFile

@RunWith(AndroidJUnit4::class)
class ScooterCaptureReviewTest {
    @Test fun changingCarToScooterReconfiguresSensorsAndDoesNotStartCarModel() {
        assumeTrue(InstrumentationRegistry.getArguments().getString("physicalHardware") == "true")
        val context = InstrumentationRegistry.getInstrumentation().targetContext
        val repository = (context.applicationContext as SetuApplication).repository
        check(!repository.recording.value)
        val saved = repository.settings.value
        ActivityScenario.launch(MainActivity::class.java).use { scenario ->
            try {
                scenario.onActivity {
                    repository.updateSettings(saved.copy(vehicle = "Car", onDeviceSpeedModel = true, modelSharingAllowed = false))
                    repository.hub.start()
                }
                waitUntil { repository.hub.nativeEstimate.value.pairedSamples > 10 }
                assertTrue(repository.hub.nativeEstimate.value.vehicleConstraintsEnabled)
                scenario.onActivity { repository.updateSettings(repository.settings.value.copy(vehicle = "Two-wheeler")) }
                waitUntil { !repository.hub.nativeEstimate.value.vehicleConstraintsEnabled }
                assertNull(repository.hub.modelSession)
                val collection = CollectionMetadata.create(context, "scooter-profile-check", repository.settings.value, false)
                assertFalse(collection.getBoolean("localModelEnabled"))
                assertEquals("unconfirmed", collection.getString("mount"))
            } finally { repository.updateSettings(saved) }
        }
    }

    @Test fun exportSelectedRidesAndMeasureIndependentBlackouts() {
        val arguments = InstrumentationRegistry.getArguments()
        val ids = arguments.getString("scooterRecordingIds")
        assumeTrue("Select existing recordings explicitly; originals are read only.", ids != null)
        val label = arguments.getString("reportLabel") ?: "review"
        require(label.matches(Regex("[a-z-]+")))
        val context = InstrumentationRegistry.getInstrumentation().targetContext
        val repository = (context.applicationContext as SetuApplication).repository
        check(!repository.recording.value)
        val directory = File(context.getExternalFilesDir(null), "verification/scooter-$label").apply { mkdirs() }
        val reports = JSONArray()
        for (id in checkNotNull(ids).split(',')) {
            require(id.matches(Regex("[a-f0-9-]{36}")))
            val source = repository.tripStore.logFile(id)
            val before = digest(source)
            val destination = File(directory, "$id.zip")
            val manifest = GnssShadowReplay(context, warmupSeconds = 30).use { replay ->
                TrainingArchive.export(source, destination.outputStream(), replay)
            }
            assertEquals(before, digest(source))
            assertEquals("Two-wheeler", manifest.getJSONObject("recording").getJSONObject("collection").getString("vehicle"))
            assertTrue(manifest.getBoolean("complete"))
            assertEquals(0L, manifest.getLong("droppedRecords"))
            var blackouts = 0
            var available = 0
            val statuses = mutableMapOf<String, Int>()
            val errors = mutableListOf<Double>()
            ZipFile(destination).use { zip ->
                zip.getInputStream(zip.getEntry("aligned.jsonl")).bufferedReader().useLines { lines ->
                    lines.forEach { line ->
                        val row = JSONObject(line)
                        val prediction = row.optJSONObject("shadowEstimate")
                        if (prediction?.optString("phase") == "gps_withheld") {
                            blackouts++
                            if (prediction.getBoolean("hasEstimate")) available++
                            val status = prediction.getString("status")
                            statuses[status] = (statuses[status] ?: 0) + 1
                            if (!row.isNull("shadowReferenceErrorMeters")) errors.add(row.getDouble("shadowReferenceErrorMeters"))
                        }
                    }
                }
            }
            val sorted = errors.sorted()
            val report = JSONObject().put("recordingId", id).put("sourceSha256", before)
                .put("durationSeconds", manifest.getLong("durationSeconds"))
                .put("referenceSeconds", manifest.getInt("referenceSeconds"))
                .put("pairedSeconds", manifest.getInt("pairedSeconds"))
                .put("sessionIssues", manifest.getJSONArray("issues"))
                .put("blackoutOutputs", blackouts).put("availableBlackoutOutputs", available)
                .put("blackoutStatuses", JSONObject(statuses as Map<*, *>))
                .put("referenceComparisons", errors.size)
                .put("errorMetersP50P95Max", JSONArray(if (sorted.isEmpty()) emptyList<Double>() else
                    listOf(sorted[(sorted.lastIndex * .5).toInt()], sorted[(sorted.lastIndex * .95).toInt()], sorted.last())))
                .put("deploymentApproved", false)
            reports.put(report)
            File(directory, "summary.json").writeText(reports.toString(2))
        }
    }

    @Test fun measureLongWarmupBlackoutsWithoutChangingRecordings() {
        val arguments = InstrumentationRegistry.getArguments()
        val ids = arguments.getString("longWarmupRecordingIds")
        assumeTrue("Select existing recordings explicitly; originals are read only.", ids != null)
        val durations = (arguments.getString("outageSeconds") ?: "10,30,60,120,180")
            .split(',').map(String::toInt).distinct()
        require(durations.isNotEmpty() && durations.all { it in listOf(10, 20, 30, 40, 50, 60, 90, 120, 180) })
        val context = InstrumentationRegistry.getInstrumentation().targetContext
        val repository = (context.applicationContext as SetuApplication).repository
        check(!repository.recording.value)
        val label = arguments.getString("reportLabel") ?: "v2"
        require(label.matches(Regex("[a-z0-9-]{1,40}")))
        val directory = File(context.getExternalFilesDir(null), "verification/long-warmup-$label").apply { mkdirs() }
        val summaries = JSONArray()
        val sensorTypes = setOf("accelerometer", "gyroscope", "magnetometer", "rotation_vector",
            "game_rotation_vector", "step_detector")
        for (id in checkNotNull(ids).split(',')) {
            require(id.matches(Regex("[a-f0-9-]{36}")))
            val source = repository.tripStore.logFile(id)
            val before = digest(source)
            val references = TreeMap<Long, JSONObject>()
            var started = -1L
            var ended = -1L
            var metadata = JSONObject()
            source.useLines { lines -> lines.forEach { line ->
                val row = JSONObject(line)
                if (row.optString("schema") == "setu.log.v1") metadata = row.getJSONObject("collection")
                when (row.optString("type")) {
                    in sensorTypes -> if (started < 0) started = row.getLong("tNs")
                    "gnss_reference" -> if (row.optString("provider") == "gps") references[row.getLong("tNs")] = row
                    "end" -> { ended = row.getLong("tNs"); assertEquals(0L, row.getLong("droppedRecords")) }
                }
            } }
            require(started >= 0 && ended > started)
            for (duration in durations) {
                val predictions = TreeMap<Long, JSONObject>()
                var aidedOutputs = 0
                var aidedAvailable = 0
                val aidedDetails = mutableMapOf<String, Int>()
                GnssShadowReplay(context, warmupSeconds = 120, outageSeconds = duration,
                    outputIntervalMs = 100).use { replay ->
                    source.useLines { lines -> lines.forEach { line ->
                        replay.accept(JSONObject(line))?.let { row ->
                            predictions[row.getLong("tNs")] = row
                            if (row.getString("phase") == "gps_aided_warmup") {
                                aidedOutputs++
                                if (row.getBoolean("hasEstimate")) aidedAvailable++
                                val detail = row.getString("detail")
                                aidedDetails[detail] = (aidedDetails[detail] ?: 0) + 1
                            }
                        }
                    } }
                }
                val cycleNs = (120 + duration) * 1_000_000_000L
                var cycleStart = started
                var cycles = 0
                var outputs = 0
                var available = 0
                var comparable = 0
                var withinTen = 0
                var referenceAvailable = 0
                val errors = mutableListOf<Double>()
                val statuses = mutableMapOf<String, Int>()
                val headings = mutableMapOf<String, Int>()
                File(directory, "$id-$duration.jsonl").bufferedWriter().use { writer ->
                    while (cycleStart + cycleNs <= ended) {
                        val cutoff = cycleStart + 120_000_000_000L
                        for (index in 0 until duration * 10) {
                            val timestamp = cutoff + index * 100_000_000L
                            val row = predictions.floorEntry(timestamp)?.value?.takeIf {
                                timestamp - it.getLong("tNs") <= 150_000_000L &&
                                    it.getLong("cycleStartNs") == cycleStart &&
                                    it.getString("phase") == "gps_withheld"
                            }
                            val pose = row?.optJSONObject("pose")?.takeIf {
                                timestamp - it.getLong("tNs") in 0..300_000_000L
                            }
                            outputs++
                            val reference = TrainingArchive.comparisonReference(references, timestamp)
                            if (reference != null) referenceAvailable++
                            if (pose != null) available++
                            val error = if (reference != null && pose != null) GeoPoint(pose.getDouble("latitude"), pose.getDouble("longitude"))
                                .distanceTo(GeoPoint(reference.getDouble("latitude"), reference.getDouble("longitude"))) else null
                            if (error != null) {
                                comparable++
                                errors.add(error)
                                if (error <= 10.0) withinTen++
                            }
                            val status = row?.getString("status") ?: "missing_output"
                            statuses[status] = (statuses[status] ?: 0) + 1
                            val heading = row?.optString("headingSource") ?: "none"
                            headings[heading] = (headings[heading] ?: 0) + 1
                            writer.appendLine(JSONObject().put("cycle", cycles)
                                .put("outageElapsedSeconds", index / 10.0)
                                .put("recordingElapsedSeconds", (timestamp - started) / 1e9)
                                .put("available", pose != null).put("errorMeters", error ?: JSONObject.NULL)
                                .put("referenceAvailable", reference != null)
                                .put("poseAgeMs", pose?.let { (timestamp - it.getLong("tNs")) / 1e6 } ?: JSONObject.NULL)
                                .put("speedMps", pose?.opt("speedMps") ?: JSONObject.NULL)
                                .put("status", status).put("headingSource", heading)
                                .put("acceptedGps", row?.optInt("acceptedGps") ?: 0)
                                .put("resets", row?.optInt("resets") ?: 0).toString())
                        }
                        cycleStart += cycleNs
                        cycles++
                    }
                }
                val sorted = errors.sorted()
                assertEquals(cycles * duration * 10, outputs)
                assertTrue("Selected rides must contain usable withheld GPS references", referenceAvailable > 0)
                assertEquals(before, digest(source))
                summaries.put(JSONObject().put("schema", "setu.phone-outage.v2")
                    .put("apkSha256", digest(File(context.applicationInfo.sourceDir)))
                    .put("scoreInterval", "half-open [0, outageSeconds); reference at score tick")
                    .put("recordingId", id).put("sourceSha256", before)
                    .put("collection", metadata).put("warmupSeconds", 120).put("outageSeconds", duration)
                    .put("scoreHz", 10).put("cycles", cycles).put("outputs", outputs)
                    .put("available", available).put("referenceAvailable", referenceAvailable)
                    .put("comparable", comparable).put("within10Meters", withinTen)
                    .put("jointSuccessLowerBound", if (outputs > 0) withinTen.toDouble() / outputs else JSONObject.NULL)
                    .put("conditionalErrorP90Meters", if (sorted.isEmpty()) JSONObject.NULL else
                        sorted[(kotlin.math.ceil(sorted.size * .9).toInt() - 1).coerceAtLeast(0)])
                    .put("aidedOutputs", aidedOutputs).put("aidedAvailable", aidedAvailable)
                    .put("aidedDetails", JSONObject(aidedDetails as Map<*, *>))
                    .put("statuses", JSONObject(statuses as Map<*, *>))
                    .put("headingSources", JSONObject(headings as Map<*, *>))
                    .put("reference", "Withheld phone GNSS, not independent survey truth")
                    .put("deploymentApproved", false))
                File(directory, "summary.json").writeText(summaries.toString(2))
                println("SETU long warmup: $id duration=$duration cycles=$cycles available=$available/$outputs")
            }
        }
    }

    private fun digest(file: File): String {
        val hash = MessageDigest.getInstance("SHA-256")
        file.inputStream().use { stream ->
            val buffer = ByteArray(65536)
            while (true) {
                val count = stream.read(buffer)
                if (count < 0) break
                hash.update(buffer, 0, count)
            }
        }
        return hash.digest().joinToString("") { "%02x".format(it) }
    }

    private fun waitUntil(condition: () -> Boolean) {
        val deadline = SystemClock.elapsedRealtime() + 20_000
        while (!condition()) {
            check(SystemClock.elapsedRealtime() < deadline) { "Timed out waiting for the activity profile." }
            SystemClock.sleep(100)
        }
    }
}
