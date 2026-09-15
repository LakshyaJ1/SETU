package com.setu.navigator

import android.location.Location
import android.content.ContextWrapper
import android.content.pm.PackageManager
import android.os.SystemClock
import androidx.core.location.LocationCompat
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import com.setu.navigator.data.*
import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test
import org.junit.runner.RunWith

@RunWith(AndroidJUnit4::class)
class GnssObservationTest {
    private fun location() = Location("setu-test").apply {
        latitude = 12.9753
        longitude = 77.6067
        elapsedRealtimeNanos = 1_000_000_000L
        LocationCompat.setMock(this, true)
    }

    @Test
    fun optionalMeasurementsPreserveMissingAndMeasuredZero() {
        val location = location()
        val missing = checkNotNull(locationPose(location, 2_000_000_000L))
        assertNull(missing.speedMps)
        assertNull(missing.bearing)
        assertNull(missing.accuracyMeters)
        assertNull(missing.altitudeMeters)
        assertEquals(true, missing.mock)
        assertEquals("Test location", missing.source)
        location.speed = 0f
        location.bearing = 0f
        location.accuracy = 5f
        location.altitude = 0.0
        location.speedAccuracyMetersPerSecond = 0.5f
        location.bearingAccuracyDegrees = 30f
        location.verticalAccuracyMeters = 8f
        val measured = checkNotNull(locationPose(location, 2_000_000_000L))
        assertEquals(0.0, measured.speedMps!!, 0.0)
        assertEquals(0.0, measured.bearing!!, 0.0)
        assertEquals(0.0, measured.altitudeMeters!!, 0.0)
        assertEquals(5.0, measured.accuracyMeters!!, 0.0)
        assertEquals(0.5, measured.speedAccuracyMps!!, 0.0)
        assertEquals(30.0, measured.bearingAccuracyDegrees!!, 0.0)
        assertEquals(8.0, measured.verticalAccuracyMeters!!, 0.0)
        assertEquals(measured, TripStore.decodePose(TripStore.encodePose(measured)))
        assertEquals(missing, TripStore.decodePose(TripStore.encodePose(missing)))
        location.bearingAccuracyDegrees = 270f
        val uncertain = checkNotNull(locationPose(location, 2_000_000_000L))
        assertEquals(270.0, TripStore.decodePose(TripStore.encodePose(uncertain)).bearingAccuracyDegrees!!, 0.0)
    }

    @Test
    fun invalidOrOrphanMeasurementsCannotBecomeObservations() {
        val location = location().apply {
            speed = Float.NaN
            accuracy = -1f
            speedAccuracyMetersPerSecond = 1f
            verticalAccuracyMeters = 3f
            bearingAccuracyDegrees = 10f
        }
        val pose = checkNotNull(locationPose(location, 2_000_000_000L))
        assertNull(pose.speedMps)
        assertNull(pose.accuracyMeters)
        assertNull(pose.speedAccuracyMps)
        assertNull(pose.bearingAccuracyDegrees)
        assertNull(pose.verticalAccuracyMeters)
        assertNull(locationPose(location, 999_999_999L))
        location.latitude = Double.NaN
        assertNull(locationPose(location, 2_000_000_000L))
        location.latitude = 91.0
        assertNull(locationPose(location, 2_000_000_000L))
        location.latitude = 12.0
        location.elapsedRealtimeNanos = 0
        assertNull(locationPose(location, 2_000_000_000L))
    }

    @Test
    fun legacyZeroMeasurementsAreUnknownAndNonzeroValuesSurvive() {
        val legacy = JSONObject().put("latitude", 12.9753).put("longitude", 77.6067).put("tNs", 1000)
            .put("speedMps", 0.0).put("bearing", 0.0).put("accuracyMeters", 0.0)
        val ambiguous = TripStore.decodePose(legacy)
        assertNull(ambiguous.speedMps)
        assertNull(ambiguous.bearing)
        assertNull(ambiguous.accuracyMeters)
        assertNull(ambiguous.mock)
        legacy.put("speedMps", 2.0).put("bearing", 90.0).put("accuracyMeters", 5.0)
        val measured = TripStore.decodePose(legacy)
        assertEquals(2.0, measured.speedMps!!, 0.0)
        assertEquals(90.0, measured.bearing!!, 0.0)
        assertEquals(5.0, measured.accuracyMeters!!, 0.0)
        assertEquals(ambiguous, TripStore.decodePose(TripStore.encodePose(ambiguous)))
    }

    @Test
    fun malformedMeasurementMetadataIsRejected() {
        val original = TripStore.encodePose(checkNotNull(locationPose(location(), 2_000_000_000L))).toString()
        listOf("measurementVersion" to 2, "measurementVersion" to "1", "speedMps" to "unknown",
            "accuracyMeters" to -1, "bearing" to 360, "bearingAccuracyDegrees" to -1,
            "verticalAccuracyMeters" to -1, "mock" to "false").forEach { (field, value) ->
            assertTrue(field, runCatching { TripStore.decodePose(JSONObject(original).put(field, value)) }.isFailure)
        }
    }

    @Test
    fun duplicateDelayedAndFutureFixesDoNotReplaceLatestOrEnterLog() {
        val context = object : ContextWrapper(InstrumentationRegistry.getInstrumentation().targetContext) {
            override fun checkSelfPermission(permission: String) = PackageManager.PERMISSION_DENIED
        }
        val hub = SensorHub(context)
        val records = mutableListOf<JSONObject>()
        hub.record = { if (it.optString("type") == "pose") records.add(it) }
        hub.start()
        try {
        val now = SystemClock.elapsedRealtimeNanos()
        val first = location().apply { elapsedRealtimeNanos = now - 2_000_000_000L }
        hub.onLocationChanged(first)
        hub.onLocationChanged(first)
        hub.onLocationChanged(Location(first).apply { elapsedRealtimeNanos-- })
        hub.onLocationChanged(Location(first).apply { elapsedRealtimeNanos = Long.MAX_VALUE })
        assertEquals(1, records.size)
        assertEquals(first.elapsedRealtimeNanos, hub.pose.value!!.timestampNs)
        val next = Location(first).apply { elapsedRealtimeNanos = now - 1_000_000_000L }
        hub.onLocationChanged(next)
        assertEquals(2, records.size)
        assertEquals(next.elapsedRealtimeNanos, hub.pose.value!!.timestampNs)
        assertTrue(records.all { it.isNull("speedMps") && it.isNull("bearing") && it.isNull("accuracyMeters") })
        hub.stop()
        hub.onLocationChanged(Location(next).apply { elapsedRealtimeNanos++ })
        assertEquals(2, records.size)
        } finally { hub.stop() }
    }
}
