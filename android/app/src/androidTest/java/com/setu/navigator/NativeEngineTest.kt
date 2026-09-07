package com.setu.navigator

import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import com.setu.navigator.data.GeoPoint
import com.setu.navigator.data.Pose
import com.setu.navigator.estimation.NativeEngine
import com.setu.navigator.estimation.NativeFilter
import org.junit.Assert.*
import org.junit.Test
import org.junit.runner.RunWith
import kotlin.math.abs

@RunWith(AndroidJUnit4::class)
class NativeEngineTest {
    private val context = InstrumentationRegistry.getInstrumentation().targetContext
    private val directory get() = NativeEngine.magneticData(context)
    private val rotation = doubleArrayOf(1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0)
    private val acceleration = doubleArrayOf(0.0, 0.0, 9.80665)
    private val gyro = DoubleArray(3)
    private val start = 1_000_000_000L
    private fun fix(timestamp: Long, east: Double = 0.0) = Pose(GeoPoint(0.0, Math.toDegrees(east / 6378137.0)),
        speedMps = 4.0, bearing = 90.0, accuracyMeters = 3.0, timestampNs = timestamp,
        altitudeMeters = 0.0, verticalAccuracyMeters = 8.0, speedAccuracyMps = 0.2, bearingAccuracyDegrees = 1.0, mock = true)

    private fun seed(engine: NativeEngine) {
        assertEquals(1, engine.attitude(start, rotation, 0.15))
        assertEquals(1, engine.imu(start, acceleration, gyro))
        assertEquals(1, engine.gnss(fix(start)))
        assertEquals(2.0, engine.snapshot()[0], 0.0)
    }

    @Test
    fun delayedCorrectionsMatchOnTimePropagationAndGeographicDisplacement() {
        NativeEngine(directory).use { timely -> NativeEngine(directory).use { delayed ->
            seed(timely)
            seed(delayed)
            for (step in 1..400) {
                val timestamp = start + step * 10_000_000L
                timely.imu(timestamp, acceleration, gyro)
                delayed.imu(timestamp, acceleration, gyro)
                if (step % 50 == 0 && step <= 350) assertEquals(1, timely.gnss(fix(timestamp, step * 0.04)))
                if (step >= 63 && (step - 13) % 50 == 0 && step <= 363) {
                    assertEquals(1, delayed.gnss(fix(timestamp - 130_000_000, (step - 13) * 0.04)))
                }
            }
            val expected = timely.snapshot()
            val actual = delayed.snapshot()
            for (index in listOf(1, 2, 3, 4, 5, 6, 7, 8, 16, 17, 18, 19)) assertEquals("Field $index", expected[index], actual[index], 1e-7)
            assertEquals(7.0, actual[13], 0.0)
            assertEquals(8.0, actual[10], 0.0)
            assertEquals(16.0, actual[18], 0.03)
            assertEquals(0.0, actual[19], 0.03)
            assertEquals(Math.toDegrees(16.0 / 6378137.0), actual[3], 1e-6)
            assertTrue(actual[7].isFinite() && actual[7] > 0)
        } }
    }

    @Test
    fun initializationNeedsHeadingAndMissingAltitudeDoesNotBecomeSeaLevel() {
        NativeEngine(directory).use { engine ->
            engine.imu(start, acceleration, gyro)
            assertEquals(0, engine.gnss(fix(start).copy(altitudeMeters = null, verticalAccuracyMeters = null, bearing = null, speedMps = null)))
            assertEquals(1.0, engine.snapshot()[0], 0.0)
            assertTrue(engine.snapshot()[2].isNaN())
            assertEquals(-1, engine.attitude(start, rotation, 0.9))
            assertEquals(1, engine.attitude(start, rotation, 0.2))
            val initialized = engine.snapshot()
            assertEquals(2.0, initialized[0], 0.0)
            assertTrue(initialized[4].isNaN())
            assertTrue(initialized[6].isNaN())
        }
    }

    @Test
    fun gapsWithholdTheEstimateAndRequireNewAlignmentInputs() {
        NativeEngine(directory).use { engine ->
            seed(engine)
            engine.imu(start + 200_000_000, acceleration, gyro)
            assertEquals(4.0, engine.snapshot()[0], 0.0)
            assertTrue(engine.snapshot()[2].isNaN())
            assertEquals(1.0, engine.snapshot()[14], 0.0)
            val resumed = start + 500_000_000
            engine.imu(resumed, acceleration, gyro)
            assertEquals(0, engine.gnss(fix(resumed)))
            assertEquals(1.0, engine.snapshot()[0], 0.0)
            engine.attitude(resumed, rotation, 0.15)
            assertEquals(2.0, engine.snapshot()[0], 0.0)
        }
    }

    @Test
    fun gatesAndInvalidTimestampsDoNotMoveTheState() {
        NativeEngine(directory).use { engine ->
            seed(engine)
            engine.imu(start + 10_000_000, acceleration, gyro)
            val previous = engine.snapshot()
            assertEquals(0, engine.gnss(fix(start + 10_000_000, 10000.0)))
            val gated = engine.snapshot()
            for (index in 1..9) assertEquals(previous[index], gated[index], 0.0)
            assertEquals(1.0, gated[11], 0.0)
            assertEquals(0, engine.imu(start, acceleration, gyro))
            assertEquals(-1, engine.gnss(fix(start + 1_000_000_000)))
            assertEquals(-1, engine.gnss(fix(start + 20_000_000).copy(accuracyMeters = null)))
            assertEquals(0, engine.gnss(fix(start + 10_000_000)))
            assertEquals(-1, engine.attitude(start + 20_000_000, DoubleArray(8), 0.1))
            engine.imu(start + 20_000_000, acceleration, gyro)
            assertEquals(1, engine.gnss(fix(start + 20_000_000, 0.08).copy(mock = false)))
            assertEquals(1.0, engine.snapshot()[9], 0.0)
            assertEquals(-1, engine.imu(start + 30_000_000, doubleArrayOf(Double.NaN, 0.0, 9.80665), gyro))
            assertEquals(4.0, engine.snapshot()[0], 0.0)
        }
    }

    @Test
    fun pendingFixDoesNotResetTheFilterAndOutageEventuallyWithholdsOutput() {
        NativeEngine(directory).use { engine ->
            seed(engine)
            val pending = start + 50_000_000
            assertEquals(0, engine.gnss(fix(pending, 0.2)))
            assertEquals(1.0, engine.snapshot()[10], 0.0)
            repeat(5) { engine.imu(start + (it + 1) * 10_000_000L, acceleration, gyro) }
            assertEquals(2.0, engine.snapshot()[10], 0.0)
            var sawInertial = false
            var sawWithheld = false
            for (step in 6..1100) {
                engine.imu(start + step * 10_000_000L, acceleration, gyro)
                if (step % 10 == 0) {
                    val state = engine.snapshot()
                    sawInertial = sawInertial || state[0] == 3.0
                    sawWithheld = sawWithheld || state[0] == 5.0
                }
            }
            assertTrue(sawInertial)
            assertTrue(sawWithheld)
            assertTrue(engine.snapshot()[2].isNaN())
        }
    }

    @Test
    fun magneticDeclinationMatchesPublishedNoaaWmm2025Examples() {
        NativeEngine(directory).use { engine ->
            var checked = 0
            InstrumentationRegistry.getInstrumentation().context.assets.open("WMM2025_TestValues.txt").bufferedReader().useLines { lines ->
                lines.filter { it.isNotBlank() && !it.startsWith("#") }.forEach { line ->
                    val values = line.trim().split(Regex("\\s+")).map(String::toDouble)
                    if (values[1] <= 20 && abs(values[2]) <= 89 && values[6] >= 2000) {
                        val actual = Math.toDegrees(engine.declination(values[0], GeoPoint(values[2], values[3]), values[1] * 1000))
                        assertEquals("NOAA row: $line", values[4], actual, 0.006)
                        checked++
                    }
                }
            }
            assertTrue("Expected published low-altitude cases", checked >= 10)
            assertTrue(engine.declination(2030.0, GeoPoint(0.0, 0.0), 0.0).isNaN())
            assertTrue(engine.declination(2024.9, GeoPoint(0.0, 0.0), 0.0).isNaN())
        }
    }

    @Test
    fun horizontalVelocityUpdateDoesNotInventVerticalSpeed() {
        NativeFilter().use { filter ->
            filter.reset(rotation, DoubleArray(3), doubleArrayOf(1.0, 2.0, 7.0), doubleArrayOf(1e-8, 0.5, 5.0, 0.02, 0.10, 0.05))
            assertTrue(filter.update(NativeFilter.Measurement.VELOCITY_2D, doubleArrayOf(0.0, 0.0), doubleArrayOf(0.2, 0.2)).accepted)
            assertEquals(7.0, filter.snapshot()[11], 1e-12)
        }
        val engine = NativeEngine(directory)
        engine.close()
        engine.close()
        assertTrue(runCatching { engine.snapshot() }.isFailure)
    }
}
