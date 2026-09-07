package com.setu.navigator.estimation

import kotlin.math.abs

data class NativeCoreStatus(
    val running: Boolean = false,
    val message: String = "Native check not run",
    val detail: String = "Checks the mathematical kernel with synthetic inputs. Live native positioning has a separate status and opt-in above.",
)

fun checkNativeCore(): NativeCoreStatus {
    NativeFilter().use { filter ->
        filter.reset(doubleArrayOf(1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0), DoubleArray(3), DoubleArray(3))
        val acceleration = doubleArrayOf(0.0, 0.0, 9.80665)
        val angularRate = DoubleArray(3)
        repeat(1000) { filter.propagate(acceleration, angularRate, 0.005) }
        val stationary = filter.snapshot()
        check(stationary.all(Double::isFinite))
        check((9..14).all { abs(stationary[it]) < 1e-9 })
        check(abs(stationary[22] - 5.0) < 1e-9)
        check(filter.update(NativeFilter.Measurement.POSITION, doubleArrayOf(1.0, -0.5, 0.1), doubleArrayOf(1.0, 1.0, 1.0)).accepted)
        check(!filter.update(NativeFilter.Measurement.POSITION, doubleArrayOf(10000.0, 10000.0, 10000.0), doubleArrayOf(1.0, 1.0, 1.0)).accepted)
    }
    return NativeCoreStatus(message = "Native check passed",
        detail = "1,000 synthetic IMU intervals, a position correction and an outlier rejection ran through JNI. This checks kernel integration, not real-drive accuracy.")
}
