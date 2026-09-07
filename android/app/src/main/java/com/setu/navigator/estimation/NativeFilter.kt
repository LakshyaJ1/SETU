package com.setu.navigator.estimation

class NativeFilter : AutoCloseable {
    private var handle = nativeCreate().also { check(it != 0L) { "Could not allocate native filter" } }

    @Synchronized
    fun reset(rotation: DoubleArray, position: DoubleArray, velocity: DoubleArray,
              deviations: DoubleArray = doubleArrayOf(0.05, 0.5, 5.0, 0.02, 0.10, 0.05), scale: Double = 1.7467) {
        check(handle != 0L) { "Filter is closed" }
        require(nativeReset(handle, rotation, position, velocity, deviations, scale) == 1) { "Invalid filter initialization" }
    }

    @Synchronized
    fun propagate(acceleration: DoubleArray, angularRate: DoubleArray, seconds: Double, noiseScale: Double = 1.0) {
        check(handle != 0L) { "Filter is closed" }
        require(nativePropagate(handle, acceleration, angularRate, seconds, noiseScale) == 1) { "Invalid IMU interval or sample" }
    }

    @Synchronized
    fun update(kind: Measurement, values: DoubleArray, deviations: DoubleArray): Update {
        check(handle != 0L) { "Filter is closed" }
        val result = nativeUpdate(handle, kind.ordinal, values, deviations)
        require(result != null && result[0] >= 0) { "Invalid measurement or covariance" }
        return Update(result[0] == 1.0, result[1])
    }

    @Synchronized
    fun snapshot(): DoubleArray {
        check(handle != 0L) { "Filter is closed" }
        return checkNotNull(nativeSnapshot(handle)) { "Filter has not been initialized" }
    }

    @Synchronized
    override fun close() {
        if (handle != 0L) nativeDestroy(handle)
        handle = 0L
    }

    enum class Measurement { POSITION, VELOCITY, FORWARD_SPEED, NHC, ZUPT, SVO_FREQUENCY, POSITION_2D, ALTITUDE, VELOCITY_2D }
    data class Update(val accepted: Boolean, val nis: Double)

    private external fun nativeCreate(): Long
    private external fun nativeDestroy(handle: Long)
    private external fun nativeReset(handle: Long, rotation: DoubleArray, position: DoubleArray, velocity: DoubleArray, deviations: DoubleArray, scale: Double): Int
    private external fun nativePropagate(handle: Long, acceleration: DoubleArray, angularRate: DoubleArray, seconds: Double, noiseScale: Double): Int
    private external fun nativeUpdate(handle: Long, kind: Int, values: DoubleArray, deviations: DoubleArray): DoubleArray?
    private external fun nativeSnapshot(handle: Long): DoubleArray?

    companion object {
        init { System.loadLibrary("setu_jni") }
    }
}
