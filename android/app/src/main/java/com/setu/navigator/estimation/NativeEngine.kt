package com.setu.navigator.estimation

import android.content.Context
import com.setu.navigator.data.GeoPoint
import com.setu.navigator.data.Pose
import java.io.File
import java.security.MessageDigest

class NativeEngine(directory: File) : AutoCloseable {
    private var handle = nativeCreate(directory.absolutePath).also { check(it != 0L) { "Native engine or WMM2025 data could not be loaded" } }

    @Synchronized
    fun imu(timestampNs: Long, acceleration: DoubleArray, angularRate: DoubleArray): Int {
        check(handle != 0L) { "Engine is closed" }
        return nativeImu(handle, timestampNs, acceleration, angularRate)
    }

    @Synchronized
    fun attitude(timestampNs: Long, rotation: DoubleArray, sigma: Double): Int {
        check(handle != 0L) { "Engine is closed" }
        return nativeAttitude(handle, timestampNs, rotation, sigma)
    }

    @Synchronized
    fun gnss(pose: Pose): Int {
        check(handle != 0L) { "Engine is closed" }
        val values = doubleArrayOf(pose.point.latitude, pose.point.longitude, pose.altitudeMeters ?: Double.NaN,
            pose.accuracyMeters ?: Double.NaN, pose.verticalAccuracyMeters ?: Double.NaN, pose.speedMps ?: Double.NaN,
            pose.bearing ?: Double.NaN, pose.speedAccuracyMps ?: Double.NaN, pose.bearingAccuracyDegrees ?: Double.NaN,
            pose.mock?.let { if (it) 1.0 else 0.0 } ?: Double.NaN)
        return nativeGnss(handle, pose.timestampNs, values)
    }

    @Synchronized
    fun snapshot(): DoubleArray {
        check(handle != 0L) { "Engine is closed" }
        return checkNotNull(nativePoll(handle))
    }

    @Synchronized
    fun declination(year: Double, point: GeoPoint, altitude: Double): Double {
        check(handle != 0L) { "Engine is closed" }
        return nativeDeclination(handle, year, point.latitude, point.longitude, altitude)
    }

    @Synchronized
    fun magneticField(year: Double, point: GeoPoint, altitude: Double): DoubleArray? {
        check(handle != 0L) { "Engine is closed" }
        return nativeMagneticField(handle, year, point.latitude, point.longitude, altitude)
    }

    @Synchronized
    override fun close() {
        if (handle != 0L) nativeDestroy(handle)
        handle = 0
    }

    private external fun nativeCreate(directory: String): Long
    private external fun nativeDestroy(handle: Long)
    private external fun nativeImu(handle: Long, timestampNs: Long, acceleration: DoubleArray, angularRate: DoubleArray): Int
    private external fun nativeAttitude(handle: Long, timestampNs: Long, rotation: DoubleArray, sigma: Double): Int
    private external fun nativeGnss(handle: Long, timestampNs: Long, values: DoubleArray): Int
    private external fun nativePoll(handle: Long): DoubleArray?
    private external fun nativeDeclination(handle: Long, year: Double, latitude: Double, longitude: Double, altitude: Double): Double
    private external fun nativeMagneticField(handle: Long, year: Double, latitude: Double, longitude: Double, altitude: Double): DoubleArray?

    companion object {
        init { System.loadLibrary("setu_jni") }

        @Synchronized
        fun magneticData(context: Context): File {
            val directory = File(context.filesDir, "geophysics").apply { check(isDirectory || mkdirs()) }
            listOf("wmm2025.wmm", "wmm2025.wmm.cof").forEach { name ->
                val expected = context.assets.open("geophysics/$name").use { it.readBytes() }
                val file = File(directory, name)
                val hash = MessageDigest.getInstance("SHA-256")
                if (!file.isFile || !hash.digest(file.readBytes()).contentEquals(hash.digest(expected))) file.writeBytes(expected)
            }
            return directory
        }
    }
}
