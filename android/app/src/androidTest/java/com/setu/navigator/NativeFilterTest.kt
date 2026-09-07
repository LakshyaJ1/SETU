package com.setu.navigator

import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import com.setu.navigator.estimation.NativeFilter
import org.json.JSONArray
import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test
import org.junit.runner.RunWith
import kotlin.math.abs

@RunWith(AndroidJUnit4::class)
class NativeFilterTest {
    @Test
    fun matchesPythonAcrossPropagationAndEveryMeasurementChannel() {
        val context = InstrumentationRegistry.getInstrumentation().context
        val fixture = JSONObject(context.assets.open("native-filter-parity.json").bufferedReader().use { it.readText() })
        val cases = fixture.getJSONArray("cases")
        for (caseIndex in 0 until cases.length()) {
            val scenario = cases.getJSONObject(caseIndex)
            NativeFilter().use { filter ->
                filter.reset(scenario.vector("rotation"), scenario.vector("position"), scenario.vector("velocity"))
                val actions = scenario.getJSONArray("actions")
                for (actionIndex in 0 until actions.length()) {
                    val action = actions.getJSONObject(actionIndex)
                    val label = "${scenario.getString("name")} / $actionIndex"
                    if (action.getString("kind") == "imu") {
                        filter.propagate(action.vector("acceleration"), action.vector("angularRate"),
                            action.getDouble("seconds"), action.getDouble("noiseScale"))
                    } else {
                        val result = filter.update(NativeFilter.Measurement.valueOf(action.getString("kind")),
                            action.vector("values"), action.vector("deviations"))
                        assertEquals(label, action.getBoolean("accepted"), result.accepted)
                        val expectedNis = action.getDouble("nis")
                        assertEquals(label, expectedNis, result.nis, 2e-8 + abs(expectedNis) * 1e-9)
                    }
                    if (action.has("expected")) assertState(label, action.vector("expected"), filter.snapshot())
                }
                assertState(scenario.getString("name"), scenario.vector("expected"), filter.snapshot())
            }
        }
    }

    @Test
    fun invalidSamplesDoNotCorruptStateAndClosedHandlesAreSafe() {
        val filter = NativeFilter()
        val identity = doubleArrayOf(1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0)
        val zero = DoubleArray(3)
        filter.reset(identity, zero, zero)
        val initial = filter.snapshot()
        assertThrows(IllegalArgumentException::class.java) { filter.propagate(doubleArrayOf(Double.NaN, 0.0, 0.0), zero, 0.01) }
        assertThrows(IllegalArgumentException::class.java) { filter.propagate(zero, zero, 0.0) }
        assertThrows(IllegalArgumentException::class.java) { filter.propagate(zero, zero, 1.0) }
        assertThrows(IllegalArgumentException::class.java) { filter.propagate(DoubleArray(2), zero, 0.01) }
        assertThrows(IllegalArgumentException::class.java) { filter.reset(DoubleArray(9), zero, zero) }
        assertThrows(IllegalArgumentException::class.java) { filter.update(NativeFilter.Measurement.POSITION, zero, zero) }
        assertThrows(IllegalArgumentException::class.java) { filter.update(NativeFilter.Measurement.POSITION, doubleArrayOf(1.0), doubleArrayOf(1.0)) }
        assertArrayEquals(initial, filter.snapshot(), 0.0)
        val rejected = filter.update(NativeFilter.Measurement.POSITION, doubleArrayOf(1e6, 1e6, 1e6), doubleArrayOf(1.0, 1.0, 1.0))
        assertFalse(rejected.accepted)
        assertArrayEquals(initial, filter.snapshot(), 0.0)
        filter.close()
        filter.close()
        assertThrows(IllegalStateException::class.java) { filter.snapshot() }
        assertThrows(IllegalStateException::class.java) { filter.propagate(zero, zero, 0.01) }
    }

    private fun assertState(label: String, expected: DoubleArray, actual: DoubleArray) {
        assertEquals(279, actual.size)
        expected.forEachIndexed { index, value -> assertEquals("$label / state $index", value, actual[index], 2e-8 + abs(value) * 1e-9) }
        for (row in 0 until 16) {
            assertTrue("$label / covariance diagonal $row", actual[23 + row * 16 + row] > 0)
            for (column in 0 until 16) assertEquals(actual[23 + row * 16 + column], actual[23 + column * 16 + row], 1e-10)
        }
    }

    private fun JSONObject.vector(name: String): DoubleArray = getJSONArray(name).vector()
    private fun JSONArray.vector() = DoubleArray(length()) { getDouble(it) }
}
