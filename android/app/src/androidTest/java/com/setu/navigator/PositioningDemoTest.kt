package com.setu.navigator

import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import com.setu.navigator.data.GeoPoint
import com.setu.navigator.estimation.buildPositioningDemo
import kotlinx.coroutines.CancellationException
import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test
import org.junit.runner.RunWith
import java.io.File

@RunWith(AndroidJUnit4::class)
class PositioningDemoTest {
    private val context get() = InstrumentationRegistry.getInstrumentation().targetContext

    @Test
    fun nativeEngineTracksThroughWithheldGpsAndAcceptsRecovery() {
        val demo = buildPositioningDemo(context, GeoPoint(12.9753, 77.6067))
        val outage = demo.frames.filter { !it.gpsAvailable }
        val maximumError = demo.frames.maxOf { it.reference.distanceTo(requireNotNull(it.estimate.pose).point) }
        assertEquals(241, demo.frames.size)
        assertEquals(24000L, demo.durationMs)
        assertEquals(80, outage.size)
        assertEquals(1, outage.map { it.estimate.accepted }.distinct().size)
        assertEquals(1, outage.map { it.lastGps.timestampNs }.distinct().size)
        val travelled = outage.zipWithNext().sumOf { (before, after) ->
            before.estimate.pose!!.point.distanceTo(after.estimate.pose!!.point)
        }
        assertTrue("The estimate must follow the curved path, not just its chord", travelled > 35)
        assertEquals("Inertial estimate", demo.frameAt(10000).estimate.status)
        assertTrue(demo.frameAt(10000).estimate.gpsAgeSeconds!! > 4)
        assertTrue(demo.frameAt(18000).estimate.accepted > outage.last().estimate.accepted)
        assertTrue(outage.last().estimate.radius95Meters!! > demo.frameAt(5500).estimate.radius95Meters!!)
        assertTrue(demo.frameAt(18000).estimate.radius95Meters!! < outage.last().estimate.radius95Meters!!)
        assertTrue("Synthetic tracking error: $maximumError m", maximumError < 5)
        assertTrue(demo.frames.all { it.estimate.pose?.mock == true && it.lastGps.mock == true })
        assertSame(demo.frames.first(), demo.frameAt(-1))
        assertSame(demo.frames.last(), demo.frameAt(99999))
        val directory = File(context.getExternalFilesDir(null), "verification").apply { mkdirs() }
        File(directory, "positioning-demo-metrics.json").writeText(JSONObject()
            .put("scenario", "Controlled synthetic GPS/IMU processed by the packaged native engine; not field accuracy")
            .put("frames", demo.frames.size).put("gpsWithheldSeconds", 8)
            .put("maximumSyntheticErrorMeters", maximumError)
            .put("outageTravelledMeters", travelled)
            .put("acceptedGpsDuringGap", 0)
            .put("radiusBeforeGapMeters", demo.frameAt(5500).estimate.radius95Meters)
            .put("radiusEndOfGapMeters", outage.last().estimate.radius95Meters)
            .put("radiusAfterRecoveryMeters", demo.frameAt(18000).estimate.radius95Meters).toString(2))
    }

    @Test(expected = CancellationException::class)
    fun cancelledPreparationDoesNotContinueGeneratingFrames() {
        buildPositioningDemo(context, GeoPoint(12.9753, 77.6067)) { throw CancellationException("Test cancellation") }
    }
}
