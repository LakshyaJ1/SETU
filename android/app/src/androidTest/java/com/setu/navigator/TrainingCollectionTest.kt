package com.setu.navigator

import android.content.Intent
import android.net.Uri
import android.os.SystemClock
import androidx.lifecycle.ViewModelProvider
import androidx.test.core.app.ActivityScenario
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import com.setu.navigator.data.GnssShadowReplay
import com.setu.navigator.data.RecordingService
import com.setu.navigator.data.Trip
import com.setu.navigator.data.GeoPoint
import com.setu.navigator.data.Pose
import com.setu.navigator.data.TripStore
import com.setu.navigator.estimation.NativeEngine
import org.json.JSONArray
import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test
import org.junit.runner.RunWith
import java.io.File
import java.util.zip.ZipFile
import java.util.Calendar
import java.util.TimeZone
import kotlin.math.*

@RunWith(AndroidJUnit4::class)
class TrainingCollectionTest {
    private val context get() = InstrumentationRegistry.getInstrumentation().targetContext

    @Test
    fun phoneRecordsAndExportsPortableTrainingBundle() {
        val repository = (context.applicationContext as SetuApplication).repository
        check(!repository.recording.value) { "Do not interrupt the user's recording." }
        val settings = repository.settings.value
        val existing = repository.tripStore.all().map { it.id }.toSet()
        var owned: Trip? = null
        ActivityScenario.launch(MainActivity::class.java).use { scenario ->
            try {
                scenario.onActivity { activity ->
                    repository.updateSettings(settings.copy(vehicle = "Car", modelSharingAllowed = false))
                    activity.startForegroundService(Intent(activity, RecordingService::class.java)
                        .putExtra("name", "Collection pipeline verification").putExtra("fixedMount", true))
                }
                waitUntil { repository.recording.value && repository.recordCount.value > 100 }
                SystemClock.sleep(15000)
                context.startService(Intent(context, RecordingService::class.java).setAction("STOP"))
                waitUntil { !repository.recording.value }
                owned = repository.tripStore.all().single { it.id !in existing && it.name == "Collection pipeline verification" }
                val original = repository.tripStore.logFile(checkNotNull(owned).id)
                val archive = File(context.cacheDir, "collection-verification.zip")
                lateinit var model: SetuViewModel
                scenario.onActivity { activity ->
                    model = ViewModelProvider(activity)[SetuViewModel::class.java]
                    model.exportTrainingTrip(checkNotNull(owned), Uri.fromFile(archive))
                }
                waitUntil { !model.busy && model.trainingExportSummary?.startsWith("Training bundle saved:") == true }
                val report = ZipFile(archive).use { zip ->
                    zip.getInputStream(zip.getEntry("manifest.json")).bufferedReader().use { JSONObject(it.readText()) }
                }
                assertTrue(report.getBoolean("complete"))
                assertEquals(0L, report.getLong("droppedRecords"))
                val metadata = report.getJSONObject("recording").getJSONObject("collection")
                assertEquals(checkNotNull(owned).id, metadata.getString("sessionId"))
                assertEquals("fixed", metadata.getString("mount"))
                assertEquals("Car", metadata.getString("vehicle"))
                assertTrue(metadata.getJSONArray("sensors").length() >= 2)
                ZipFile(archive).use { zip ->
                    val frames = zip.getInputStream(zip.getEntry("aligned.jsonl")).bufferedReader().useLines { lines ->
                        lines.map(::JSONObject).toList()
                    }
                    assertTrue(frames.size >= 14)
                    assertTrue(frames.count { it.getJSONObject("accelerometer").getInt("count") >= 100 } >= 10)
                    assertTrue(frames.any { !it.isNull("shadowEstimate") })
                    zip.getInputStream(zip.getEntry("raw.setulog")).use { assertArrayEquals(original.readBytes(), it.readBytes()) }
                }
                File(context.getExternalFilesDir(null), "verification").apply { mkdirs() }
                    .resolve("collection-pipeline-metrics.json").writeText(JSONObject()
                        .put("seconds", report.getLong("durationSeconds")).put("records", report.getLong("records"))
                        .put("pairedSeconds", report.getInt("pairedSeconds")).put("complete", true)
                        .put("droppedRecords", 0).put("installedClientExport", true).toString(2))
            } finally {
                if (repository.recording.value) {
                    context.startService(Intent(context, RecordingService::class.java).setAction("STOP"))
                    waitUntil { !repository.recording.value }
                }
                repository.tripStore.all().filter { it.id !in existing && it.name == "Collection pipeline verification" }
                    .forEach(repository.tripStore::delete)
                repository.updateSettings(settings)
                repository.refreshTrips()
            }
        }
    }

    @Test
    fun gpsReferenceChangesCannotLeakIntoTheWithheldTrajectory() {
        val origin = GeoPoint(28.6773, 77.286)
        val wallTime = System.currentTimeMillis()
        val calendar = Calendar.getInstance(TimeZone.getTimeZone("UTC")).apply { timeInMillis = wallTime }
        val year = calendar.get(Calendar.YEAR) + (calendar.get(Calendar.DAY_OF_YEAR) - 1).toDouble() / calendar.getActualMaximum(Calendar.DAY_OF_YEAR)
        val field = NativeEngine(NativeEngine.magneticData(context)).use { checkNotNull(it.magneticField(year, origin, 0.0)) }
        val declination = atan2(field[0], field[1])
        val start = 10_000_000_000L
        fun run(shift: Double): List<JSONObject> {
            val output = mutableListOf<JSONObject>()
            GnssShadowReplay(context, warmupSeconds = 30).use { replay ->
                for (index in 0..3900) {
                    val seconds = index / 100.0
                    val timestamp = start + index * 10_000_000L
                    val angularRate = if (seconds >= 30) .2 * cos(seconds - 30) else 0.0
                    val heading = if (seconds >= 30) .2 * sin(seconds - 30) else 0.0
                    val vectors = mapOf("accelerometer" to listOf(0.0, 4.0 * angularRate, 9.80665),
                        "gyroscope" to listOf(0.0, 0.0, angularRate),
                        "magnetometer" to listOf(cos(heading) * field[0] + sin(heading) * field[1],
                            -sin(heading) * field[0] + cos(heading) * field[1], field[2]),
                        "rotation_vector" to listOf(0.0, 0.0, sin((heading + declination) / 2), cos((heading + declination) / 2), -1.0))
                    for ((kind, values) in vectors) replay.accept(JSONObject().put("type", kind).put("tNs", timestamp)
                        .put("accuracy", 3).put("values", JSONArray(values)))?.let(output::add)
                    if (index % 100 == 0) {
                        val point = GeoPoint(origin.latitude + if (seconds >= 30) shift else 0.0,
                            origin.longitude + Math.toDegrees(4 * seconds / (6378137 * cos(Math.toRadians(origin.latitude)))))
                        replay.accept(TripStore.encodePose(Pose(point, 4.0, 90.0, 3.0, timestamp, "Synthetic fixture",
                            altitudeMeters = 0.0, speedAccuracyMps = .2, bearingAccuracyDegrees = 1.0, mock = false))
                            .put("type", "gnss_reference").put("provider", "gps").put("receivedAtNs", timestamp).put("wallTimeMs", wallTime))
                    }
                }
            }
            return output.filter { it.getString("phase") == "gps_withheld" }
        }
        val original = run(0.0)
        val changedReference = run(.1)
        assertTrue(original.size >= 8)
        assertTrue(original.take(5).all { it.getBoolean("hasEstimate") })
        assertEquals(1, original.map { it.getInt("acceptedGps") }.distinct().size)
        assertTrue(original.first().getInt("acceptedGps") > 0)
        assertEquals(original.map(JSONObject::toString), changedReference.map(JSONObject::toString))
        val first = original.first().getJSONObject("pose")
        val later = original[4].getJSONObject("pose")
        assertNotEquals(first.getDouble("longitude"), later.getDouble("longitude"))
    }

    @Test
    fun shadowReplayWorksAcrossRebootsAndReportsMissingHeadingHonestly() {
        val started = SystemClock.elapsedRealtimeNanos() + 100_000_000_000L
        val frames = mutableListOf<JSONObject>()
        GnssShadowReplay(context, warmupSeconds = 30).use { replay ->
            for (index in 0..6100) {
                val timestamp = started + index * 10_000_000L
                for (kind in listOf("accelerometer", "gyroscope")) {
                    replay.accept(JSONObject().put("type", kind).put("tNs", timestamp)
                        .put("accuracy", 3).put("values", JSONArray(if (kind == "accelerometer") listOf(0.0, 0.0, 9.80665) else listOf(0.0, 0.0, 0.0))))?.let(frames::add)
                }
            }
        }
        assertTrue(frames.size >= 59)
        assertTrue(frames.any { it.getString("phase") == "gps_withheld" })
        assertTrue(frames.all { !it.getBoolean("hasEstimate") && it.isNull("pose") })
        assertEquals(2, frames.map { it.getLong("cycleStartNs") }.distinct().size)
    }

    private fun waitUntil(condition: () -> Boolean) {
        val deadline = SystemClock.elapsedRealtime() + 20000
        while (!condition() && SystemClock.elapsedRealtime() < deadline) SystemClock.sleep(50)
        assertTrue("Timed out waiting for recording lifecycle", condition())
    }
}
