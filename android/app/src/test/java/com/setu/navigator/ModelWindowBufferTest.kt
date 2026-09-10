package com.setu.navigator

import com.setu.navigator.model.ModelWindow
import com.setu.navigator.model.ModelWindowBuffer
import org.junit.Assert.*
import org.junit.Test

class ModelWindowBufferTest {
    private val acceleration = doubleArrayOf(0.0, 0.0, 9.80665)
    private val gyro = DoubleArray(3)

    @Test
    fun windowsContainFourSecondsOfUnmodifiedSiSamplesAndAchievedRate() {
        val buffer = ModelWindowBuffer("Car")
        repeat(800) { index -> assertNull(buffer.append(1_000_000_000L + index * 5_000_000L, acceleration, gyro)) }
        val window = checkNotNull(buffer.append(5_000_000_000L, acceleration, gyro))
        assertEquals(801, window.samples.size)
        assertEquals(200.0, window.rateHz, 1e-10)
        assertEquals("Car", window.vehicle)
        acceleration[2] = 0.0
        assertEquals(9.80665, window.samples.first().accelerationMps2[2], 1e-10)
        repeat(199) { index -> assertNull(buffer.append(5_005_000_000L + index * 5_000_000L, acceleration, gyro)) }
        assertNotNull(buffer.append(6_000_000_000L, acceleration, gyro))
    }

    @Test
    fun gapsRequireANewContinuousWindowAndInvalidSamplesAreIgnored() {
        val buffer = ModelWindowBuffer("Car")
        repeat(401) { index -> buffer.append(1_000_000_000L + index * 10_000_000L, acceleration, gyro) }
        assertNull(buffer.append(5_000_000_000L, acceleration, gyro))
        assertNull(buffer.append(5_010_000_000L, doubleArrayOf(Double.NaN, 0.0, 0.0), gyro))
        assertNull(buffer.append(6_000_000_000L, acceleration, gyro))
        repeat(399) { index -> assertNull(buffer.append(6_010_000_000L + index * 10_000_000L, acceleration, gyro)) }
        val recovered = checkNotNull(buffer.append(10_000_000_000L, acceleration, gyro))
        assertEquals(6_000_000_000L, recovered.samples.first().timestampNs)
    }

    @Test
    fun longStreamsRemainBoundedAndDoNotMislabelTruncatedHighRateWindows() {
        val buffer = ModelWindowBuffer("Car")
        val emitted = mutableListOf<ModelWindow>()
        repeat(10_000) { index -> buffer.append(1_000_000_000L + index * 2_500_000L, acceleration, gyro)?.let(emitted::add) }
        assertTrue(emitted.isNotEmpty())
        assertTrue(emitted.all { it.samples.size <= 2048 && it.rateHz == 400.0 })
        val unsupported = ModelWindowBuffer("Car")
        repeat(8_000) { index -> assertNull(unsupported.append(1_000_000_000L + index * 1_000_000L, acceleration, gyro)) }
    }
}
