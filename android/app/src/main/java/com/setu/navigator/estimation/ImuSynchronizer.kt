package com.setu.navigator.estimation

class ImuSynchronizer(private val accept: (Long, DoubleArray, DoubleArray) -> Unit) {
    private data class Sample(val timestamp: Long, val values: DoubleArray)
    private val acceleration = ArrayDeque<Sample>()
    private val gyroscope = ArrayDeque<Sample>()
    private var lastAcceleration = 0L
    private var lastGyroscope = 0L
    var rejected = 0L
        private set

    fun acceleration(timestamp: Long, values: DoubleArray) = append(true, timestamp, values)
    fun gyroscope(timestamp: Long, values: DoubleArray) = append(false, timestamp, values)

    private fun append(isAcceleration: Boolean, timestamp: Long, values: DoubleArray) {
        if (timestamp <= (if (isAcceleration) lastAcceleration else lastGyroscope) ||
            values.size != 3 || values.any { !it.isFinite() }) { rejected++; return }
        if (isAcceleration) lastAcceleration = timestamp else lastGyroscope = timestamp
        val queue = if (isAcceleration) acceleration else gyroscope
        queue.addLast(Sample(timestamp, values.copyOf()))
        if (queue.size > 128) { queue.removeFirst(); rejected++ }
        while (gyroscope.isNotEmpty() && acceleration.size >= 2) {
            val sample = gyroscope.first()
            while (acceleration.size > 2 && acceleration[1].timestamp <= sample.timestamp) acceleration.removeFirst()
            val before = acceleration[0]
            val after = acceleration[1]
            if (sample.timestamp < before.timestamp) { gyroscope.removeFirst(); rejected++; continue }
            if (sample.timestamp > after.timestamp) return
            gyroscope.removeFirst()
            if (after.timestamp - before.timestamp > 50_000_000L) { rejected++; continue }
            val fraction = (sample.timestamp - before.timestamp).toDouble() / (after.timestamp - before.timestamp)
            val valuesAtGyro = DoubleArray(3) { axis -> before.values[axis] + fraction * (after.values[axis] - before.values[axis]) }
            accept(sample.timestamp, valuesAtGyro, sample.values)
        }
    }
}
