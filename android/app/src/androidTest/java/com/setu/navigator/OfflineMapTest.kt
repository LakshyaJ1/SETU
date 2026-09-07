package com.setu.navigator

import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import com.setu.navigator.data.GeoPoint
import com.setu.navigator.data.OfflineMap
import com.setu.navigator.data.MapPackStore
import org.junit.Assert.*
import org.junit.Test
import org.junit.runner.RunWith

@RunWith(AndroidJUnit4::class)
class OfflineMapTest {
    private val maps = MapPackStore(InstrumentationRegistry.getInstrumentation().targetContext).activeMap.value

    @Test
    fun includedDestinationsHaveDrivableRoutes() {
        maps.places.forEach { destination ->
            val route = maps.route(maps.demonstrationStart, destination.point)
            assertTrue(destination.name, route.points.isNotEmpty())
            assertTrue(destination.name, route.distanceMeters >= 0)
            assertTrue(destination.name, route.points.last().distanceTo(destination.point) <= 250)
        }
    }

    @Test(expected = IllegalArgumentException::class)
    fun outOfCoverageOriginIsRejected() {
        maps.route(GeoPoint(28.6139, 77.2090), maps.places.first().point)
    }
}
