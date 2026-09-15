package com.setu.navigator

import com.setu.navigator.estimation.positioningDemoMotion
import org.junit.Assert.*
import org.junit.Test
import kotlin.math.*

class PositioningDemoMotionTest {
    @Test
    fun demoHasAlternatingBendsAndAStopWithoutTeleporting() {
        val samples = positioningDemoMotion()
        assertEquals(2401, samples.size)
        assertEquals(samples, positioningDemoMotion())
        assertEquals(24000L, samples.last().elapsedMs)
        assertTrue(samples.sumOf { abs(it.turnRate) * .01 } > 5)
        val directions = samples.filter { abs(it.turnRate) > .1 }.map { sign(it.turnRate) }
        assertTrue(directions.zipWithNext().count { (before, after) -> before != after } >= 4)
        assertTrue(samples.filter { it.elapsedMs in 19000..20000 }.all { it.speed == 0.0 })
        assertTrue(samples.all { it.speed in 0.0..6.0 && abs(it.acceleration) <= 4.6 })
        samples.zipWithNext().forEach { (before, after) ->
            assertEquals(10L, after.elapsedMs - before.elapsedMs)
            assertTrue(hypot(after.east - before.east, after.north - before.north) <= .060001)
        }
    }

    @Test
    fun syntheticImuMatchesTheReferenceMotionThroughTurns() {
        val samples = positioningDemoMotion()
        fun eastAcceleration(index: Int) = samples[index].let {
            it.acceleration * cos(it.heading) - it.speed * it.turnRate * sin(it.heading)
        }
        fun northAcceleration(index: Int) = samples[index].let {
            it.acceleration * sin(it.heading) + it.speed * it.turnRate * cos(it.heading)
        }
        for (index in 1 until samples.lastIndex) {
            val before = samples[index - 1]
            val after = samples[index + 1]
            val eastChange = (after.speed * cos(after.heading) - before.speed * cos(before.heading)) / .02
            val northChange = (after.speed * sin(after.heading) - before.speed * sin(before.heading)) / .02
            val expectedEast = (eastAcceleration(index - 1) + 2 * eastAcceleration(index) + eastAcceleration(index + 1)) / 4
            val expectedNorth = (northAcceleration(index - 1) + 2 * northAcceleration(index) + northAcceleration(index + 1)) / 4
            assertEquals(expectedEast, eastChange, .003)
            assertEquals(expectedNorth, northChange, .003)
        }
    }
}
