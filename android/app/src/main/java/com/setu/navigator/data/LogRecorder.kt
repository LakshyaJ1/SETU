package com.setu.navigator.data

import org.json.JSONObject
import java.io.BufferedWriter
import java.util.concurrent.ArrayBlockingQueue
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicLong

/**
 * Hot-path sink for raw sensor samples.
 *
 * Implementations must not allocate, block, lock or touch disk: this is called from the sensor
 * HandlerThread at the full device rate (accelerometer, gyroscope, magnetometer and both rotation
 * vectors, so roughly a thousand callbacks a second on a 200 Hz phone).
 */
interface SensorSink {
    fun sensor(type: String, tNs: Long, values: FloatArray, count: Int, accuracy: Int)
}

/**
 * Writes a `.setulog` JSON Lines recording from a dedicated thread.
 *
 * The recorder previously built a `JSONObject` plus a `JSONArray` plus a boxed `List` for every
 * sensor callback and then serialised and wrote it inline, under a lock the UI thread also wanted.
 * At ~1000 callbacks a second that dominated the sensor thread and contended with settings writes.
 *
 * Here the producer side only copies primitives into a pooled record and offers it to a bounded
 * queue, so the sensor thread never allocates, never serialises and never blocks. Formatting,
 * buffering and flushing happen on the writer thread. The emitted text is byte-for-byte what the
 * previous `JSONObject.toString()` path produced, so existing recordings, replay, export and import
 * are unaffected.
 *
 * Overflow is counted, never silent: a full queue increments [dropped] rather than stalling
 * acquisition, matching the logging rule in `docs/04` that dropped samples must be accounted for.
 */
class LogRecorder(
    private val writer: BufferedWriter,
    private val derive: (String) -> JSONObject?,
    private val onProgress: (records: Long, dropped: Long) -> Unit,
    private val onError: (Exception) -> Unit,
) : SensorSink, AutoCloseable {

    private class Sample {
        @JvmField var type: String = ""
        @JvmField var tNs: Long = 0
        @JvmField val values = FloatArray(MAX_VALUES)
        @JvmField var count: Int = 0
        @JvmField var accuracy: Int = 0
    }

    private val pool = ArrayBlockingQueue<Sample>(CAPACITY)
    private val queue = ArrayBlockingQueue<Any>(CAPACITY)
    private val recordCount = AtomicLong()
    private val dropCount = AtomicLong()
    @Volatile private var running = true
    @Volatile private var failure: Exception? = null
    private val builder = StringBuilder(192)

    val records: Long get() = recordCount.get()
    val dropped: Long get() = dropCount.get()

    private val thread = Thread({ drain() }, "setu-log-writer").apply {
        priority = Thread.NORM_PRIORITY - 1
        isDaemon = true
    }

    init {
        repeat(CAPACITY) { pool.offer(Sample()) }
        thread.start()
    }

    // ------------------------------------------------------------------ producer side

    override fun sensor(type: String, tNs: Long, values: FloatArray, count: Int, accuracy: Int) {
        if (!running) return
        val sample = pool.poll()
        if (sample == null) { dropCount.incrementAndGet(); return }
        sample.type = type
        sample.tNs = tNs
        sample.count = if (count < MAX_VALUES) count else MAX_VALUES
        for (index in 0 until sample.count) sample.values[index] = values[index]
        sample.accuracy = accuracy
        if (!queue.offer(sample)) {
            pool.offer(sample)
            dropCount.incrementAndGet()
        }
    }

    /** Low-rate structured records: poses, GNSS epochs, native state, model measurements. */
    fun document(record: JSONObject) {
        if (!running) return
        if (!queue.offer(record)) dropCount.incrementAndGet()
    }

    // ------------------------------------------------------------------ writer thread

    private fun drain() {
        var lastFlush = System.nanoTime()
        try {
            while (true) {
                val entry = queue.poll(200, TimeUnit.MILLISECONDS)
                if (entry == null) {
                    if (!running && queue.isEmpty()) break
                } else {
                    write(entry)
                }
                val now = System.nanoTime()
                if (now - lastFlush > FLUSH_INTERVAL_NS) {
                    writer.flush()
                    lastFlush = now
                    onProgress(recordCount.get(), dropCount.get())
                }
            }
            writer.flush()
        } catch (error: Exception) {
            failure = error
            running = false
            onError(error)
        }
    }

    private fun write(entry: Any) {
        if (entry is Sample) {
            builder.setLength(0)
            builder.append("{\"type\":\"").append(entry.type).append("\",\"tNs\":").append(entry.tNs).append(",\"values\":[")
            for (index in 0 until entry.count) {
                if (index > 0) builder.append(',')
                appendNumber(builder, entry.values[index])
            }
            builder.append("],\"accuracy\":").append(entry.accuracy).append('}')
            writer.append(builder).append('\n')
            recordCount.incrementAndGet()
            entry.type = ""
            pool.offer(entry)
            return
        }
        val record = entry as JSONObject
        writer.append(record.toString()).append('\n')
        recordCount.incrementAndGet()
        val type = record.optString("type")
        if (type == "pose" || type == "native_pose") {
            derive(type)?.let {
                writer.append(it.toString()).append('\n')
                recordCount.incrementAndGet()
            }
        }
    }

    override fun close() {
        if (!running) { runCatching { thread.join(CLOSE_TIMEOUT_MS) }; return }
        running = false
        runCatching { thread.join(CLOSE_TIMEOUT_MS) }
        failure?.let { throw it }
    }

    companion object {
        private const val CAPACITY = 4096
        private const val MAX_VALUES = 6
        private const val FLUSH_INTERVAL_NS = 1_000_000_000L
        private const val CLOSE_TIMEOUT_MS = 4000L

        /**
         * Reproduces `org.json.JSONObject.numberToString` for a float, so the recorder's output is
         * identical to the previous `JSONArray(values.toList())` encoding: whole values render as
         * integers, negative zero renders as `-0`, everything else as `Float.toString`.
         */
        internal fun appendNumber(builder: StringBuilder, value: Float) {
            val wide = value.toDouble()
            if (wide == 0.0 && 1.0 / wide < 0.0) { builder.append("-0"); return }
            val whole = wide.toLong()
            if (wide == whole.toDouble()) builder.append(whole) else builder.append(value)
        }
    }
}
