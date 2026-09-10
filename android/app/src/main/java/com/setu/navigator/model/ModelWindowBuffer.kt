package com.setu.navigator.model

class ModelWindowBuffer(private val vehicle: String) {
    private val samples = ArrayDeque<ImuSample>()
    private var lastEmissionNs = 0L

    fun append(timestampNs: Long, acceleration: DoubleArray, angularRate: DoubleArray): ModelWindow? {
        if (timestampNs <= 0 || acceleration.size != 3 || angularRate.size != 3 ||
            acceleration.any { !it.isFinite() } || angularRate.any { !it.isFinite() }) return null
        val previous = samples.lastOrNull()
        if (previous != null && timestampNs <= previous.timestampNs) return null
        if (previous != null && timestampNs - previous.timestampNs > 50_000_000L) {
            samples.clear()
            lastEmissionNs = 0L
        }
        samples.addLast(ImuSample(timestampNs, acceleration.toList(), angularRate.toList()))
        while (samples.size > 2048 || samples.size > 2 && timestampNs - samples[1].timestampNs >= 4_000_000_000L) {
            samples.removeFirst()
        }
        val span = timestampNs - samples.first().timestampNs
        if (span < 4_000_000_000L || timestampNs - lastEmissionNs < 1_000_000_000L) return null
        lastEmissionNs = timestampNs
        return ModelWindow(samples.toList(), (samples.size - 1) * 1_000_000_000.0 / span, vehicle)
    }
}
