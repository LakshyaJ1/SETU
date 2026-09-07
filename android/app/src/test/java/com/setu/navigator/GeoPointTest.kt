package com.setu.navigator

import com.setu.navigator.data.GeoPoint
import com.setu.navigator.data.durationLabel
import org.junit.Assert.*
import org.junit.Test

class GeoPointTest {
    @Test fun distanceIsSymmetricAndMeasuredInMeters() {
        val start = GeoPoint(12.97, 77.59)
        val finish = GeoPoint(12.98, 77.59)
        assertEquals(1111.95, start.distanceTo(finish), 1.0)
        assertEquals(start.distanceTo(finish), finish.distanceTo(start), 0.001)
        assertEquals(0.0, start.distanceTo(start), 0.0)
    }
    @Test fun bearingAndInterpolationPreserveEndpoints() {
        val start = GeoPoint(0.0, 0.0)
        val finish = GeoPoint(0.0, 1.0)
        assertEquals(90.0, start.bearingTo(finish), 0.0001)
        assertEquals(start, start.interpolate(finish, -1.0))
        assertEquals(finish, start.interpolate(finish, 2.0))
    }
    @Test(expected = IllegalArgumentException::class) fun nonFiniteCoordinatesAreRejected() { GeoPoint(Double.NaN, 0.0) }
    @Test fun longDurationsDoNotWrapAtAnHour() { assertEquals("1:01:01", durationLabel(3_661_000)) }
}
