package com.setu.navigator

import com.setu.navigator.data.LogRecorder
import org.junit.Assert.assertEquals
import org.junit.Test

/**
 * Number formatting parity for the recorder's hot path.
 *
 * The sensor callback used to build a `JSONObject` plus a `JSONArray` per sample - about a thousand
 * allocations a second across five sensors - and serialise it inline under a lock the UI thread also
 * wanted. The recorder now writes the same text from a pooled primitive record on its own thread.
 * "The same text" is a real compatibility claim: existing `.setulog` recordings, replay, export and
 * import all parse this format, so the encoding of a float must match `org.json` exactly.
 *
 * `org.json.JSONObject.numberToString` widens the float to a double, returns `-0` for negative zero,
 * renders a value equal to its own `long` as an integer, and otherwise falls back to the number's own
 * `toString`. These cases pin each of those branches. They run on the JVM without android.jar's
 * stubbed `org.json`, which is why the rules are asserted directly rather than by comparison.
 */
class LogRecorderFormatTest {

    private fun render(value: Float): String =
        StringBuilder().also { LogRecorder.appendNumber(it, value) }.toString()

    @Test
    fun wholeValuesRenderAsIntegers() {
        assertEquals("1", render(1.0f))
        assertEquals("0", render(0.0f))
        assertEquals("-3", render(-3.0f))
        assertEquals("10", render(10.0f))
        assertEquals("2048", render(2048.0f))
    }

    @Test
    fun negativeZeroKeepsItsSign() {
        // JSONObject special-cases this; a plain `0` would lose the sign a sensor actually reported.
        assertEquals("-0", render(-0.0f))
    }

    @Test
    fun fractionalValuesUseTheFloatRendering() {
        // Widening 9.81f to a double gives 9.809999465942383, so the float's own toString is what
        // org.json emits here - not the widened decimal.
        assertEquals("9.81", render(9.81f))
        assertEquals("0.5", render(0.5f))
        assertEquals("-0.25", render(-0.25f))
        assertEquals(java.lang.Float.toString(0.1f), render(0.1f))
        assertEquals(java.lang.Float.toString(-9.806649f), render(-9.806649f))
    }

    @Test
    fun typicalSensorSamplesRoundTripToTheSameNumbers() {
        val samples = floatArrayOf(-0.0393f, 9.8066f, 0.0117f, -0.00213f, 1.0f, 0.0f)
        val rendered = samples.map(::render)
        assertEquals(samples.size, rendered.size)
        rendered.forEachIndexed { index, text ->
            assertEquals("sample $index", samples[index], text.toFloat(), 0.0f)
        }
    }

    @Test
    fun renderedValuesParseBackExactly() {
        var value = -40.0f
        while (value <= 40.0f) {
            assertEquals(value, render(value).toFloat(), 0.0f)
            value += 0.37f
        }
    }
}
