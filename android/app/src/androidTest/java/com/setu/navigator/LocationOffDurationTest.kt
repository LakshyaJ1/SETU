package com.setu.navigator

import android.content.Intent
import android.os.ParcelFileDescriptor
import android.os.SystemClock
import android.view.WindowManager
import androidx.test.core.app.ActivityScenario
import androidx.test.platform.app.InstrumentationRegistry
import com.setu.navigator.data.RecordingService
import org.json.JSONArray
import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Assume.assumeTrue
import org.junit.Test
import java.io.File
import java.util.UUID

class LocationOffDurationTest {
    @Test
    fun realSensorsContinueForNinetySecondsWithSystemLocationOff() {
        assumeTrue(InstrumentationRegistry.getArguments().getString("physicalHardware") == "true")
        val instrumentation = InstrumentationRegistry.getInstrumentation()
        val context = instrumentation.targetContext
        val repository = (context.applicationContext as SetuApplication).repository
        check(!repository.recording.value) { "Do not interrupt a user recording." }
        val settings = repository.settings.value
        val locationEnabled = repository.hub.isLocationEnabled()
        val name = "Location-off duration verification ${UUID.randomUUID()}"
        val existing = repository.tripStore.all().map { it.id }.toSet()
        var ownsRecording = false
        val stages = JSONArray()
        val evidence = File(context.getExternalFilesDir(null), "verification/location-off-durations.json")
        fun toggle(enabled: Boolean) {
            ParcelFileDescriptor.AutoCloseInputStream(instrumentation.uiAutomation.executeShellCommand(
                "cmd location set-location-enabled $enabled")).use { it.readBytes() }
            waitUntil { repository.hub.isLocationEnabled() == enabled }
        }
        ActivityScenario.launch(MainActivity::class.java).use { scenario ->
            try {
                scenario.onActivity { activity ->
                    activity.window.addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
                    repository.updateSettings(settings.copy(vehicle = "Two-wheeler",
                        onDeviceSpeedModel = false, modelSharingAllowed = false))
                    activity.startForegroundService(Intent(activity, RecordingService::class.java).putExtra("name", name))
                    ownsRecording = true
                }
                waitUntil { repository.recording.value && repository.hub.nativeEstimate.value.pairedSamples > 100 }
                toggle(false)
                waitUntil { !repository.hub.locationEnabled.value }
                val started = SystemClock.elapsedRealtime()
                var previousSamples = repository.hub.sensors.value.sampleCount
                var previousPairs = repository.hub.nativeEstimate.value.pairedSamples
                var previousSeconds = 0
                for (seconds in listOf(10, 20, 30, 40, 50, 90)) {
                    val remaining = started + seconds * 1000 - SystemClock.elapsedRealtime()
                    if (remaining > 0) SystemClock.sleep(remaining)
                    val sensor = repository.hub.sensors.value
                    val native = repository.hub.nativeEstimate.value
                    val age = (SystemClock.elapsedRealtimeNanos() - sensor.lastSampleNs) / 1e6
                    val elapsed = SystemClock.elapsedRealtime() - started
                    val sampleDelta = sensor.sampleCount - previousSamples
                    val pairDelta = native.pairedSamples - previousPairs
                    stages.put(JSONObject().put("seconds", seconds).put("elapsedMs", elapsed)
                        .put("systemLocationEnabled", repository.hub.isLocationEnabled())
                        .put("observedLocationEnabled", repository.hub.locationEnabled.value)
                        .put("sensorEventsInPhase", sampleDelta).put("pairedImuInPhase", pairDelta)
                        .put("lastSensorAgeMs", age).put("nativeStatus", native.status)
                        .put("hasNativePosition", native.pose != null)
                        .put("nativeSpeedMps", native.pose?.speedMps ?: JSONObject.NULL)
                        .put("positionAccuracy", JSONObject.NULL))
                    evidence.parentFile!!.mkdirs()
                    evidence.writeText(JSONObject().put("schema", "setu.location-off-continuity.v1")
                        .put("device", android.os.Build.MODEL).put("stages", stages)
                        .put("reference", "No independent moving reference; continuity only, not navigation accuracy")
                        .put("deploymentApproved", false).toString(2))
                    assertFalse(repository.hub.isLocationEnabled())
                    assertFalse(repository.hub.locationEnabled.value)
                    assertTrue(repository.recording.value)
                    assertTrue("Sensor callbacks stopped at $seconds s", sampleDelta > (seconds - previousSeconds) * 50)
                    assertTrue("IMU pairing stopped at $seconds s", pairDelta > (seconds - previousSeconds) * 20)
                    assertTrue("Sensor output is stale at $seconds s: $age ms", age in 0.0..1000.0)
                    assertTrue("Test process suspended", elapsed < seconds * 1000 + 5000)
                    previousSamples = sensor.sampleCount
                    previousPairs = native.pairedSamples
                    previousSeconds = seconds
                }
                toggle(true)
                waitUntil { repository.hub.locationEnabled.value }
            } finally {
                if (ownsRecording && repository.recording.value) {
                    context.startService(Intent(context, RecordingService::class.java).setAction("STOP"))
                    waitUntil { !repository.recording.value }
                }
                repository.tripStore.all().filter { it.id !in existing && it.name == name }
                    .forEach(repository.tripStore::delete)
                repository.refreshTrips()
                repository.updateSettings(settings)
                toggle(locationEnabled)
            }
        }
    }

    private fun waitUntil(condition: () -> Boolean) {
        val deadline = SystemClock.elapsedRealtime() + 15000
        while (!condition()) {
            check(SystemClock.elapsedRealtime() < deadline) { "Timed out waiting for sensor/location state." }
            SystemClock.sleep(50)
        }
    }
}
