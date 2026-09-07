package com.setu.navigator

import android.content.ContextWrapper
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import com.setu.navigator.data.*
import org.json.JSONObject
import org.junit.After
import org.junit.Assert.*
import org.junit.Test
import org.junit.runner.RunWith
import java.io.ByteArrayOutputStream
import java.io.File
import java.util.UUID

@RunWith(AndroidJUnit4::class)
class TripStoreTest {
    private val target = InstrumentationRegistry.getInstrumentation().targetContext
    private val directory = File(target.cacheDir, "trip-tests-${UUID.randomUUID()}").apply { mkdirs() }
    private val store = TripStore(object : ContextWrapper(target) { override fun getFilesDir() = directory })
    private val header = JSONObject().put("schema", "setu.log.v1").put("name", "Import verification")
        .put("startedAtMs", 1000).put("startedAtNs", 1000000000).toString()
    private val first = TripStore.encodePose(Pose(GeoPoint(12.9753, 77.6067), 4.0, 90.0, 5.0, 1000000000, "Test GPS")).toString()
    private val second = TripStore.encodePose(Pose(GeoPoint(12.9753, 77.6068), 4.0, 90.0, 5.0, 2000000000, "Test GPS")).toString()

    @After
    fun cleanup() { directory.deleteRecursively() }

    @Test
    fun importExportAndDeleteRoundTrip() {
        val original = "$header\n$first\n$second\n"
        val trip = store.import(original.byteInputStream())
        assertEquals(2, trip.points.size)
        assertEquals(1000L, trip.durationMs)
        assertEquals(2L, trip.sampleCount)
        assertTrue(trip.distanceMeters > 10)
        val exported = ByteArrayOutputStream()
        store.export(trip, exported)
        assertEquals(original, exported.toString("UTF-8"))
        store.delete(trip)
        assertTrue(store.all().isEmpty())
        assertFalse(store.logFile(trip.id).exists())
    }

    @Test
    fun optionalMeasurementsSurviveImportAndStoredMetadata() {
        val unknown = Pose(GeoPoint(12.9753, 77.6067), timestampNs = 1000000000, source = "Test location", mock = true)
        val zero = unknown.copy(timestampNs = 2000000000, speedMps = 0.0, bearing = 0.0, accuracyMeters = 5.0,
            altitudeMeters = 0.0, verticalAccuracyMeters = 4.0, speedAccuracyMps = 0.5, bearingAccuracyDegrees = 20.0)
        val original = "$header\n${TripStore.encodePose(unknown)}\n${TripStore.encodePose(zero)}\n"
        val trip = store.import(original.byteInputStream())
        assertEquals(listOf(unknown, zero), trip.points)
        assertEquals(trip.points, store.all().single().points)
        val exported = ByteArrayOutputStream()
        store.export(trip, exported)
        assertEquals(original, exported.toString("UTF-8"))
    }

    @Test
    fun malformedImportsLeaveNoOrphanFiles() {
        listOf("", "{}\n", "$header\n$second\n$first\n", "$header\n" + "x".repeat(65537)).forEach { data ->
            assertTrue(runCatching { store.import(data.byteInputStream()) }.isFailure)
        }
        assertTrue(File(directory, "trips").listFiles().orEmpty().isEmpty())
    }

    @Test
    fun interruptedFinalRecordIsRecoveredAndExportsCleanly() {
        val id = UUID.randomUUID().toString()
        store.logFile(id).writeText("$header\n$first\n$second\n{\"type\":")
        assertEquals(1, store.recoverIncomplete())
        val recovered = store.all().single()
        assertTrue(recovered.recovered)
        assertEquals(2, recovered.points.size)
        assertEquals(0, store.recoverIncomplete())
        val exported = ByteArrayOutputStream()
        store.export(recovered, exported)
        assertEquals(2, store.import(exported.toByteArray().inputStream()).points.size)
    }

    @Test
    fun activeRecordingIsNotRecovered() {
        val id = UUID.randomUUID().toString()
        store.logFile(id).writeText("$header\n$first\n")
        assertEquals(0, store.recoverIncomplete { id })
        assertTrue(store.all().isEmpty())
    }
}
