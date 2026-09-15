package com.setu.navigator

import androidx.test.platform.app.InstrumentationRegistry
import com.setu.navigator.model.*
import kotlinx.coroutines.runBlocking
import org.junit.Assert.*
import org.junit.Test

class OnDeviceModelProviderTest {
    @Test
    fun actualPackagedModelRunsLocallyButUnapprovedPredictionsCannotFuse() = runBlocking {
        val context = InstrumentationRegistry.getInstrumentation().targetContext
        OnDeviceModelProvider(context).use { provider ->
            val health = provider.health()
            assertTrue(health.reason, health.ready)
            val samples = List(801) { index -> ImuSample(1_000_000_000L + index * 5_000_000L,
                listOf(0.0, 0.0, 9.80665), listOf(0.0, 0.0, 0.0)) }
            val window = ModelWindow(samples, 200.0, "Car")
            val result = provider.infer(window)
            val measurement = checkNotNull(result.measurement) { result.reason ?: "Missing inference" }
            assertTrue(measurement.speedMps.isFinite())
            assertTrue(measurement.sigmaMps.isFinite() && measurement.sigmaMps > 0)
            assertEquals(0.0, measurement.validity, 0.0)
            assertTrue(result.reason.orEmpty().contains("not approved"))
            assertNull(provider.infer(window.copy(vehicle = "Heavy vehicle")).measurement)
            assertNull(provider.infer(window.copy(samples = samples.reversed())).measurement)
            assertNull(provider.infer(window.copy(samples = samples.map { it.copy(accelerationMps2 = listOf(Double.NaN)) })).measurement)
        }
    }
}
