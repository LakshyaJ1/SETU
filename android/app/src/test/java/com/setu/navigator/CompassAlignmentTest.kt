package com.setu.navigator

import com.setu.navigator.estimation.CompassAlignment
import org.junit.Assert.*
import org.junit.Test

class CompassAlignmentTest {
    private val rotation = doubleArrayOf(1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0)
    private val field = doubleArrayOf(0.0, 30.0, -30.0)
    private val acceleration = doubleArrayOf(0.0, 0.0, 9.80665)
    private fun sample(check: CompassAlignment, timestamp: Long, magnetic: DoubleArray = field, accuracy: Int = 3) {
        check.acceleration(timestamp, acceleration)
        check.gyroscope(timestamp, DoubleArray(3))
        check.magnetometer(timestamp, magnetic, accuracy)
    }

    @Test
    fun missingAccuracyRequiresAFixAndTwoSecondsOfCheckedSensors() {
        val check = CompassAlignment()
        sample(check, 1_000_000_000)
        assertNull(check.evaluate(1_000_000_000, rotation, -1.0, 3))
        check.reference(field)
        repeat(201) { index ->
            val timestamp = 2_000_000_000L + index * 10_000_000L
            sample(check, timestamp)
            val result = check.evaluate(timestamp, rotation, -1.0, 3)
            if (index < 200) assertNull(result) else {
                assertNotNull(result)
                assertEquals("Checked compass · estimated uncertainty", result!!.source)
                assertTrue(result.sigmaRadians >= Math.toRadians(30.0))
                assertTrue(check.detail.contains("not hardware-reported"))
            }
        }
    }

    @Test
    fun hardwareUncertaintyIsNotReplacedWhenItIsPoor() {
        val check = CompassAlignment()
        assertEquals("Sensor-reported heading", check.evaluate(1, rotation, 0.2, 3)!!.source)
        assertNull(check.evaluate(2, rotation, 0.8, 3))
        assertNull(check.evaluate(3, rotation, 0.2, 0))
        assertNull(check.evaluate(3, rotation, 0.2, 3))
    }

    @Test
    fun interferenceUnreliableMagnetometerAndMotionCannotInitialize() {
        val check = CompassAlignment().apply { reference(field) }
        repeat(350) { index ->
            val timestamp = 1_000_000_000L + index * 10_000_000L
            sample(check, timestamp, doubleArrayOf(0.0, 80.0, -80.0))
            assertNull(check.evaluate(timestamp, rotation, null, 3))
        }
        sample(check, 5_000_000_000, accuracy = 0)
        assertNull(check.evaluate(5_000_000_000, rotation, null, 3))
        sample(check, 6_000_000_000)
        check.gyroscope(6_000_000_000, doubleArrayOf(0.0, 0.0, 1.0))
        assertNull(check.evaluate(6_000_000_000, rotation, null, 3))
        assertTrue(check.detail.contains("still"))
    }

    @Test
    fun staleSamplesAndSensorGapsRestartTheStabilityCheck() {
        val check = CompassAlignment().apply { reference(field) }
        sample(check, 1_000_000_000)
        assertNull(check.evaluate(1_000_000_000, rotation, -1.0, 3))
        assertNull(check.evaluate(4_000_000_000, rotation, -1.0, 3))
        sample(check, 4_010_000_000)
        assertNull(check.evaluate(4_010_000_000, rotation, -1.0, 3))
        sample(check, 8_000_000_000)
        assertNull(check.evaluate(8_000_000_000, rotation, -1.0, 3))
    }

    @Test
    fun callbackOrderDoesNotDiscardFreshSamplesJustNewerThanRotation() {
        val check = CompassAlignment().apply { reference(field) }
        repeat(201) { index ->
            val timestamp = 1_000_000_000L + index * 10_000_000L
            sample(check, timestamp + 5_000_000L)
            val result = check.evaluate(timestamp, rotation, -1.0, 3)
            if (index == 200) assertNotNull(result)
        }
        sample(check, 4_101_000_000L)
        assertNull(check.evaluate(4_000_000_000L, rotation, -1.0, 3))
    }
}
