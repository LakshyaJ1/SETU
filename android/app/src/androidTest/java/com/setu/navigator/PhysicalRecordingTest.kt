package com.setu.navigator

import android.Manifest
import android.content.Intent
import android.content.pm.PackageManager
import android.os.PowerManager
import android.os.SystemClock
import androidx.test.core.app.ActivityScenario
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import com.setu.navigator.data.RecordingService
import com.setu.navigator.data.Trip
import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Assume.assumeTrue
import org.junit.Test
import org.junit.runner.RunWith
import java.io.File

@RunWith(AndroidJUnit4::class)
class PhysicalRecordingTest {
    @Test
    fun actualImuRecordingContinuesInBackgroundWithoutLocationOrModelSharing() = verifyRecording(background = true)

    @Test
    fun actualImuRecordingContinuesInForegroundWithoutLocationOrModelSharing() = verifyRecording(background = false)

    private fun verifyRecording(background: Boolean) {
        assumeTrue("Opt in with -e physicalHardware true on an authorized phone.",
            InstrumentationRegistry.getArguments().getString("physicalHardware") == "true")
        val instrumentation = InstrumentationRegistry.getInstrumentation()
        val context = instrumentation.targetContext
        val repository = (context.applicationContext as SetuApplication).repository
        check(!repository.recording.value) { "Do not interrupt an existing recording." }
        check(context.checkSelfPermission(Manifest.permission.ACCESS_FINE_LOCATION) == PackageManager.PERMISSION_GRANTED) { "Grant location permission before this hardware test." }
        if (InstrumentationRegistry.getArguments().getString("requireLocationOff") == "true") {
            check(!repository.hub.isLocationEnabled()) { "Disable location before the requested blackout test." }
        }
        val settings = repository.settings.value
        val batterySaver = context.getSystemService(PowerManager::class.java).isPowerSaveMode
        if (InstrumentationRegistry.getArguments().getString("requireBatterySaverOff") == "true") {
            check(!batterySaver) { "Turn off Battery saver before the requested background test." }
        }
        val existing = repository.tripStore.all().map { it.id }.toSet()
        val mode = if (background) "background" else "foreground"
        val recordingName = "USB hardware $mode verification"
        val durationMs = if (background) 15000L else 30000L
        var ownsRecording = false
        var ownedTrip: Trip? = null
        ActivityScenario.launch(MainActivity::class.java).use { scenario ->
            try {
                scenario.onActivity { activity ->
                    activity.window.addFlags(android.view.WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
                    repository.updateSettings(settings.copy(modelSharingAllowed = false))
                    activity.startForegroundService(Intent(activity, RecordingService::class.java).putExtra("name", recordingName))
                    ownsRecording = true
                }
                waitUntil { repository.recording.value && repository.recordCount.value > 100 }
                assertTrue(repository.hub.sensors.value.hasAccelerometer && repository.hub.sensors.value.hasGyroscope)
                val before = repository.hub.sensors.value.sampleCount
                val backgroundStarted = SystemClock.elapsedRealtime()
                if (background) {
                    scenario.onActivity { it.moveTaskToBack(true) }
                    waitUntil { !repository.uiVisible }
                }
                SystemClock.sleep(durationMs)
                val backgroundMs = SystemClock.elapsedRealtime() - backgroundStarted
                val sensorState = repository.hub.sensors.value
                val after = sensorState.sampleCount
                val sampleAgeNs = SystemClock.elapsedRealtimeNanos() - sensorState.lastSampleNs
                File(context.getExternalFilesDir(null), "verification").apply { mkdirs() }.resolve("$mode-sampling-state.json").writeText(
                    JSONObject().put("backgroundMs", backgroundMs).put("sampleAgeNs", sampleAgeNs)
                        .put("beforeEvents", before).put("afterEvents", after).put("achievedHz", sensorState.achievedHz).toString(2))
                assertTrue("Recording service lost sensors in $mode", after > before + 200)
                assertTrue("Process was suspended for $backgroundMs ms", backgroundMs < durationMs + 15000)
                assertTrue("Sensor output is stale: ${sampleAgeNs / 1e6} ms", sampleAgeNs in 0..1_000_000_000L)
                assertTrue(repository.recording.value)
                val native = repository.hub.nativeEstimate.value
                assertTrue(native.pairedSamples > 100)
                assertNull(repository.hub.modelSession)
                context.startService(Intent(context, RecordingService::class.java).setAction("STOP"))
                waitUntil { !repository.recording.value }
                ownedTrip = repository.tripStore.all().single { it.id !in existing && it.name == recordingName }
                val counts = mutableMapOf<String, Int>()
                val lastTimestamp = mutableMapOf<String, Long>()
                val maximumGap = mutableMapOf<String, Long>()
                var hasEnd = false
                repository.tripStore.logFile(checkNotNull(ownedTrip).id).useLines { lines ->
                    lines.drop(1).forEach { line ->
                        val record = JSONObject(line)
                        val type = record.getString("type")
                        counts[type] = (counts[type] ?: 0) + 1
                        if (type in listOf("accelerometer", "gyroscope")) {
                            val timestamp = record.getLong("tNs")
                            val previous = lastTimestamp.put(type, timestamp)
                            if (previous != null) {
                                assertTrue("Nonmonotonic $type", timestamp > previous)
                                maximumGap[type] = maxOf(maximumGap[type] ?: 0, timestamp - previous)
                            }
                        }
                        if (type == "end") hasEnd = true
                    }
                }
                assertTrue(hasEnd)
                assertTrue((counts["accelerometer"] ?: 0) > 200 && (counts["gyroscope"] ?: 0) > 200)
                assertTrue("An IMU stream has a gap above 100 ms", maximumGap.values.all { it <= 100_000_000L })
                assertEquals(0, counts["model_measurement"] ?: 0)
                val evidence = JSONObject().put("scenario", "Actual Android IMU callbacks during $mode recording; no driving accuracy claim")
                    .put("mode", mode).put("requestedDurationMs", durationMs)
                    .put("device", android.os.Build.MODEL).put("locationEnabled", repository.hub.isLocationEnabled())
                    .put("batterySaverEnabled", batterySaver)
                    .put("backgroundMs", backgroundMs).put("backgroundSensorEvents", after - before)
                    .put("backgroundLastSampleAgeNs", sampleAgeNs)
                    .put("nativePairedSamples", native.pairedSamples).put("pairingDrops", native.pairingDrops)
                    .put("records", JSONObject(counts as Map<*, *>)).put("maximumImuGapNs", JSONObject(maximumGap as Map<*, *>))
                    .put("modelSharingEnabled", false).put("recordingSaved", true).put("existingTripCount", existing.size)
                File(context.getExternalFilesDir(null), "verification").apply { mkdirs() }.resolve("physical-$mode-recording-metrics.json").writeText(evidence.toString(2))
            } finally {
                if (ownsRecording && repository.recording.value) {
                    context.startService(Intent(context, RecordingService::class.java).setAction("STOP"))
                    waitUntil { !repository.recording.value }
                }
                ownedTrip = ownedTrip ?: repository.tripStore.all().singleOrNull { it.id !in existing && it.name == recordingName }
                ownedTrip?.let(repository.tripStore::delete)
                repository.refreshTrips()
                repository.updateSettings(settings)
            }
        }
    }

    private fun waitUntil(predicate: () -> Boolean) {
        val deadline = SystemClock.elapsedRealtime() + 20000
        while (!predicate()) {
            check(SystemClock.elapsedRealtime() < deadline) { "Timed out waiting for recording state." }
            SystemClock.sleep(100)
        }
    }
}
