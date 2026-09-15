package com.setu.navigator

import android.os.ParcelFileDescriptor
import android.os.SystemClock
import androidx.test.core.app.ActivityScenario
import androidx.test.platform.app.InstrumentationRegistry
import com.setu.navigator.data.SensorHub
import org.junit.Assert.*
import org.junit.Assume.assumeTrue
import org.junit.Test

class LocationLifecycleTest {
    @Test
    fun coldStartWithLocationOffObservesReenableWithoutRestart() {
        assumeTrue(InstrumentationRegistry.getArguments().getString("physicalHardware") == "true")
        val instrumentation = InstrumentationRegistry.getInstrumentation()
        val context = instrumentation.targetContext
        check(!(context.applicationContext as SetuApplication).repository.recording.value)
        val hub = SensorHub(context)
        check(hub.hasLocationPermission())
        val originallyEnabled = hub.isLocationEnabled()
        fun toggle(enabled: Boolean) {
            ParcelFileDescriptor.AutoCloseInputStream(instrumentation.uiAutomation.executeShellCommand(
                "cmd location set-location-enabled $enabled")).use { it.readBytes() }
            val deadline = SystemClock.elapsedRealtime() + 10000
            while (hub.isLocationEnabled() != enabled && SystemClock.elapsedRealtime() < deadline) SystemClock.sleep(50)
            assertEquals("System location toggle did not settle", enabled, hub.isLocationEnabled())
        }
        fun waitFor(enabled: Boolean) {
            val deadline = SystemClock.elapsedRealtime() + 10000
            while (hub.locationEnabled.value != enabled && SystemClock.elapsedRealtime() < deadline) SystemClock.sleep(50)
            assertEquals(enabled, hub.locationEnabled.value)
        }
        ActivityScenario.launch(MainActivity::class.java).use { scenario ->
            try {
                toggle(false)
                scenario.onActivity { hub.start() }
                assertFalse(hub.locationEnabled.value)
                toggle(true)
                waitFor(true)
                toggle(false)
                waitFor(false)
            } finally {
                scenario.onActivity { hub.stop() }
                toggle(originallyEnabled)
            }
        }
    }
}
