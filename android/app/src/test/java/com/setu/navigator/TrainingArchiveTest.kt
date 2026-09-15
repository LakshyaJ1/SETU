package com.setu.navigator

import com.setu.navigator.data.GnssShadowReplay
import com.setu.navigator.data.TrainingArchive
import org.json.JSONArray
import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test
import java.io.ByteArrayOutputStream
import java.io.File
import java.security.MessageDigest
import java.util.TreeMap
import java.util.zip.ZipInputStream

class TrainingArchiveTest {
    private val start = 10_000_000_000L

    private fun gps(timestamp: Long) = JSONObject().put("type", "gnss_reference").put("tNs", timestamp)
        .put("provider", "gps").put("mock", false).put("latitude", 28.0).put("longitude", 77.0)
        .put("speedMps", 5.0).put("speedAccuracyMps", 0.5).put("accuracyMeters", 4.0)

    private fun recording(end: Boolean = true): File {
        val file = File.createTempFile("collection-test-", ".setulog")
        file.bufferedWriter().use { writer ->
            writer.appendLine(JSONObject().put("schema", "setu.log.v1").put("clock", "elapsedRealtimeNanos")
                .put("startedAtNs", start).put("collection", JSONObject()).toString())
            repeat(300) { index ->
                val timestamp = start + (index + 1) * 10_000_000L
                for (kind in listOf("accelerometer", "gyroscope")) writer.appendLine(JSONObject()
                    .put("type", kind).put("tNs", timestamp).put("values", JSONArray(listOf(0, 0, 1))).toString())
                if (index == 99) writer.appendLine(gps(timestamp).toString())
            }
            if (end) writer.appendLine(JSONObject().put("type", "end").put("tNs", start + 3_000_000_000L).put("droppedRecords", 0).toString())
        }
        return file
    }

    @Test
    fun exportsFullRateRawAndDoesNotInventMissingGps() {
        val file = recording()
        try {
            val output = ByteArrayOutputStream()
            val report = TrainingArchive.export(file, output)
            val entries = mutableMapOf<String, ByteArray>()
            ZipInputStream(output.toByteArray().inputStream()).use { zip ->
                while (true) { val entry = zip.nextEntry ?: break; entries[entry.name] = zip.readBytes() }
            }
            assertArrayEquals(file.readBytes(), entries["raw.setulog"])
            val rows = entries.getValue("aligned.jsonl").toString(Charsets.UTF_8).lineSequence()
                .filter(String::isNotEmpty).map(::JSONObject).toList()
            assertEquals(3, rows.size)
            assertEquals(100, rows[0].getJSONObject("accelerometer").getInt("count"))
            assertEquals(0, rows[0].getJSONArray("issues").length())
            assertTrue(rows[2].isNull("gpsReference"))
            assertTrue(rows[0].isNull("shadowEstimate"))
            assertTrue(report.isNull("shadowProtocol"))
            assertEquals(2, report.getInt("pairedSeconds"))
            val hash = MessageDigest.getInstance("SHA-256").digest(file.readBytes()).joinToString("") { "%02x".format(it) }
            assertEquals(hash, report.getJSONObject("files").getJSONObject("raw.setulog").getString("sha256"))
        } finally { file.delete() }
    }

    @Test
    fun interruptedRecordingStaysExportableButCannotBeTrainingReady() {
        val file = recording(false)
        try {
            val report = TrainingArchive.export(file, ByteArrayOutputStream())
            assertFalse(report.getBoolean("complete"))
            assertTrue(report.getJSONArray("issues").toString().contains("incomplete_recording"))
        } finally { file.delete() }
    }

    @Test
    fun qualityGatesRejectUnknownMockAndNetworkReferences() {
        assertTrue(TrainingArchive.referenceIssues(gps(start)).isEmpty())
        assertTrue(TrainingArchive.referenceIssues(gps(start).put("mock", JSONObject.NULL)).contains("mock_or_unknown_origin"))
        assertTrue(TrainingArchive.referenceIssues(gps(start).put("provider", "network")).contains("gps_provider_unverified"))
        assertTrue(TrainingArchive.referenceIssues(gps(start).put("speedAccuracyMps", JSONObject.NULL)).contains("gps_speed_quality"))
    }

    @Test
    fun shadowGateNeverAcceptsLateGpsDuringWithholding() {
        val cutoff = start + 30_000_000_000L
        assertTrue(GnssShadowReplay.acceptsReference(start, start + 10, start + 5, start + 6, 30))
        assertFalse(GnssShadowReplay.acceptsReference(start, cutoff, cutoff - 10, cutoff - 5, 30))
        assertFalse(GnssShadowReplay.acceptsReference(start, cutoff - 5, cutoff - 10, cutoff, 30))
        assertFalse(GnssShadowReplay.acceptsReference(start, start + 10, start - 1, start + 1, 30))
    }

    @Test fun longWarmupStillRejectsAllGpsAtOrAfterTheCutoff() {
        assertEquals(120, GnssShadowReplay.DEFAULT_WARMUP_SECONDS)
        val cutoff = start + 120_000_000_000L
        assertTrue(GnssShadowReplay.acceptsReference(start, cutoff - 1, cutoff - 3, cutoff - 2, 120))
        assertFalse(GnssShadowReplay.acceptsReference(start, cutoff, cutoff - 3, cutoff - 2, 120))
        assertFalse(GnssShadowReplay.acceptsReference(start, cutoff - 1, cutoff - 3, cutoff, 120))
        assertFalse(GnssShadowReplay.acceptsReference(start, cutoff, cutoff, cutoff, 120))
        assertFalse(GnssShadowReplay.acceptsReference(start, cutoff, cutoff, cutoff))
    }

    @Test fun shadowComparisonInterpolatesOnlyTheEvaluationReference() {
        val references = TreeMap<Long, JSONObject>()
        val before = gps(start)
        val after = gps(start + 1_000_000_000L).put("latitude", 28.0001)
        references[start] = before
        references[start + 1_000_000_000L] = after
        val comparison = requireNotNull(TrainingArchive.comparisonReference(references, start + 650_000_000L))
        assertEquals("linear_interpolation", comparison.getString("method"))
        assertEquals(28.000065, comparison.getDouble("latitude"), 1e-9)
        assertEquals(start, comparison.getLong("fromNs"))
        assertEquals(start + 1_000_000_000L, comparison.getLong("toNs"))
        assertEquals(28.0, before.getDouble("latitude"), 0.0)
        assertEquals(28.0001, after.getDouble("latitude"), 0.0)
        assertEquals("exact_timestamp", TrainingArchive.comparisonReference(references, start)!!.getString("method"))
        assertNull(TrainingArchive.comparisonReference(references, start - 1))
        assertNull(TrainingArchive.comparisonReference(references, start + 1_000_000_001L))
    }

    @Test fun shadowComparisonRejectsPoorReferencesGapsAndPositionJumps() {
        val end = start + 1_000_000_000L
        val references = TreeMap<Long, JSONObject>().apply { put(start, gps(start)); put(end, gps(end)) }
        for (invalid in listOf(gps(end).put("accuracyMeters", 50), gps(end).put("mock", true),
            gps(end).put("speedAccuracyMps", 5), gps(end).put("provider", "network"),
            gps(end).put("latitude", 28.1))) {
            references[end] = invalid
            assertNull(TrainingArchive.comparisonReference(references, start + 500_000_000L))
        }
        references.remove(end)
        references[end + 1_000_000_000L] = gps(end + 1_000_000_000L)
        assertNull(TrainingArchive.comparisonReference(references, start + 500_000_000L))
    }

    @Test fun shadowComparisonCrossesTheAntimeridianWithoutCirclingTheGlobe() {
        val end = start + 1_000_000_000L
        val references = TreeMap<Long, JSONObject>().apply {
            put(start, gps(start).put("longitude", 179.9999))
            put(end, gps(end).put("longitude", -179.9999))
        }
        val result = requireNotNull(TrainingArchive.comparisonReference(references, start + 500_000_000L))
        assertEquals(180.0, kotlin.math.abs(result.getDouble("longitude")), 1e-8)
    }

    @Test
    fun cancellationDoesNotModifyOriginal() {
        val file = recording()
        val bytes = file.readBytes()
        try {
            assertThrows(IllegalStateException::class.java) {
                TrainingArchive.export(file, ByteArrayOutputStream()) { error("cancelled") }
            }
            assertArrayEquals(bytes, file.readBytes())
        } finally { file.delete() }
    }
}
