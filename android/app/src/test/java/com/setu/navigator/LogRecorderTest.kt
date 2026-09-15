package com.setu.navigator

import com.setu.navigator.data.LogRecorder
import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test
import java.io.BufferedWriter
import java.io.IOException
import java.io.StringWriter
import java.io.Writer
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit

class LogRecorderTest {
    @Test
    fun drainsBeforeEndAndAccountsForInvalidSamples() {
        val output = StringWriter()
        val recorder = LogRecorder(BufferedWriter(output), { _, _ -> }, { throw it }, { 9000L })
        repeat(100) { index -> recorder.sensor("accelerometer", index + 1L, floatArrayOf(1f, 2f, 3f), 3, 3) }
        recorder.sensor("accelerometer", 101, floatArrayOf(Float.NaN), 1, 0)
        recorder.sensor("accelerometer", 102, floatArrayOf(0f), 3, 0)
        recorder.sensor("unknown", 103, floatArrayOf(0f), 1, 0)
        recorder.close()
        recorder.close()
        val records = output.toString().lineSequence().filter(String::isNotBlank).map(::JSONObject).toList()
        assertEquals(101, records.size)
        assertEquals(101L, recorder.records)
        assertEquals("end", records.last().getString("type"))
        assertEquals(3L, records.last().getLong("droppedRecords"))
        assertEquals(9000L, records.last().getLong("tNs"))
        assertEquals((1L..100L).toList(), records.dropLast(1).map { it.getLong("tNs") })
    }

    @Test
    fun timeoutDoesNotCloseWriterWhileItIsStillDraining() {
        val entered = CountDownLatch(1)
        val release = CountDownLatch(1)
        val closed = CountDownLatch(1)
        val output = StringWriter()
        val slow = object : Writer() {
            override fun write(buffer: CharArray, offset: Int, count: Int) {
                entered.countDown()
                check(release.await(5, TimeUnit.SECONDS))
                output.write(buffer, offset, count)
            }
            override fun flush() = Unit
            override fun close() { closed.countDown() }
        }
        val recorder = LogRecorder(BufferedWriter(slow, 1), { _, _ -> }, {}, closeTimeoutMs = 30)
        try {
            recorder.document(JSONObject().put("type", "pose"))
            assertTrue(entered.await(3, TimeUnit.SECONDS))
            assertThrows(IOException::class.java) { recorder.close() }
            assertEquals(1L, closed.count)
        } finally { release.countDown() }
        assertTrue(closed.await(3, TimeUnit.SECONDS))
        recorder.close()
        assertEquals(listOf("pose", "end"), output.toString().lineSequence().filter(String::isNotBlank).map { JSONObject(it).getString("type") }.toList())
    }

    @Test
    fun writerFailureIsNotReportedAsASuccessfulClose() {
        val failed = CountDownLatch(1)
        val broken = object : Writer() {
            override fun write(buffer: CharArray, offset: Int, count: Int) { throw IOException("disk full") }
            override fun flush() = Unit
            override fun close() = Unit
        }
        val recorder = LogRecorder(BufferedWriter(broken, 1), { _, _ -> }, { failed.countDown() })
        recorder.document(JSONObject().put("type", "pose"))
        assertTrue(failed.await(3, TimeUnit.SECONDS))
        repeat(2) { assertEquals("disk full", assertThrows(IOException::class.java) { recorder.close() }.message) }
    }
}
