package com.setu.navigator.data

import kotlin.math.*

data class GeoPoint(val latitude: Double, val longitude: Double) {
    init {
        require(latitude.isFinite() && latitude in -90.0..90.0)
        require(longitude.isFinite() && longitude in -180.0..180.0)
    }

    fun distanceTo(other: GeoPoint): Double {
        val latitudeDelta = Math.toRadians(other.latitude - latitude)
        val longitudeDelta = Math.toRadians(other.longitude - longitude)
        val chord = sin(latitudeDelta / 2).pow(2) + cos(Math.toRadians(latitude)) *
            cos(Math.toRadians(other.latitude)) * sin(longitudeDelta / 2).pow(2)
        return 6_371_000.0 * 2 * atan2(sqrt(chord.coerceIn(0.0, 1.0)), sqrt((1 - chord).coerceIn(0.0, 1.0)))
    }

    fun bearingTo(other: GeoPoint): Double {
        val delta = Math.toRadians(other.longitude - longitude)
        val fromLatitude = Math.toRadians(latitude)
        val toLatitude = Math.toRadians(other.latitude)
        val east = sin(delta) * cos(toLatitude)
        val north = cos(fromLatitude) * sin(toLatitude) - sin(fromLatitude) * cos(toLatitude) * cos(delta)
        return (Math.toDegrees(atan2(east, north)) + 360) % 360
    }

    fun interpolate(other: GeoPoint, fraction: Double) = GeoPoint(
        latitude + (other.latitude - latitude) * fraction.coerceIn(0.0, 1.0),
        longitude + (other.longitude - longitude) * fraction.coerceIn(0.0, 1.0),
    )
}

data class Place(val id: String, val name: String, val detail: String, val point: GeoPoint)
data class Maneuver(val index: Int, val text: String, val direction: String, val distanceFromStart: Double)
data class DriveRoute(val points: List<GeoPoint>, val distanceMeters: Double, val maneuvers: List<Maneuver>,
                      val requestedStart: GeoPoint? = null, val requestedDestination: GeoPoint? = null) {
    val startOffsetMeters get() = requestedStart?.let { points.firstOrNull()?.distanceTo(it) } ?: 0.0
    val destinationOffsetMeters get() = requestedDestination?.let { points.lastOrNull()?.distanceTo(it) } ?: 0.0
}
data class Pose(
    val point: GeoPoint,
    val speedMps: Double? = null,
    val bearing: Double? = null,
    val accuracyMeters: Double? = null,
    val timestampNs: Long = 0,
    val source: String = "GPS",
    val altitudeMeters: Double? = null,
    val verticalAccuracyMeters: Double? = null,
    val speedAccuracyMps: Double? = null,
    val bearingAccuracyDegrees: Double? = null,
    val mock: Boolean? = null,
    val filterRadius95Meters: Double? = null,
) {
    fun isFresh(nowNs: Long): Boolean = timestampNs > 0 && nowNs >= timestampNs && nowNs - timestampNs < 3_000_000_000L
}

data class SensorState(
    val hasAccelerometer: Boolean = false,
    val hasGyroscope: Boolean = false,
    val hasBarometer: Boolean = false,
    val hasMagnetometer: Boolean = false,
    val accelerometer: List<Float> = listOf(0f, 0f, 0f),
    val gyroscope: List<Float> = listOf(0f, 0f, 0f),
    val pressure: Float? = null,
    val achievedHz: Double = 0.0,
    val satellites: Int = 0,
    val satellitesUsed: Int = 0,
    val meanCn0: Float? = null,
    val sampleCount: Long = 0,
    val lastSampleNs: Long = 0,
) {
    val tier: String get() = when {
        !hasGyroscope || achievedHz < 10 -> "D"
        achievedHz < 50 -> "C"
        achievedHz < 200 -> "B"
        else -> "A"
    }
}

data class Trip(
    val id: String,
    val name: String,
    val startedAtMs: Long,
    val durationMs: Long,
    val distanceMeters: Double,
    val sampleCount: Long,
    val points: List<Pose>,
    val synthetic: Boolean = false,
    val recovered: Boolean = false,
)

data class AppSettings(
    val theme: String = "System",
    val units: String = "km/h",
    val vehicle: String = "Car",
    val keepScreenOn: Boolean = true,
    val modelEndpoint: String = "https://setu-proj-sih.duckdns.org",
    val modelSharingAllowed: Boolean = false,
    val nativePositioning: Boolean = false,
    /**
     * Run the bundled speed model on this phone.
     *
     * On by default, and deliberately not behind the sharing consent that guards the research
     * server: nothing leaves the device, so there is nothing to consent to. REQ-F9 requires this
     * path anyway - a tunnel has no connectivity, so a remote endpoint cannot be what carries a
     * GNSS blackout.
     */
    val onDeviceSpeedModel: Boolean = true,
)

data class ModelConnection(
    val status: String = "Not connected",
    val detail: String = "Check the model server before enabling optional sensor sharing.",
    val modelName: String? = null,
    val checking: Boolean = false,
)

fun distanceLabel(meters: Double): String = if (meters < 1000) "${meters.roundToInt()} m" else "%.1f km".format(meters / 1000)
fun durationLabel(milliseconds: Long): String {
    val seconds = milliseconds / 1000
    return if (seconds >= 3600) "%d:%02d:%02d".format(seconds / 3600, seconds / 60 % 60, seconds % 60)
    else "%02d:%02d".format(seconds / 60, seconds % 60)
}

/**
 * Default name for a new recording.
 *
 * Every recording used to be called "Position tracking", so Trips showed four identical rows and
 * the list could not be read at a glance. Naming by time of day is what a person would write down
 * themselves, and it stays distinguishable without asking them to type anything.
 */
fun defaultDriveName(atMs: Long = System.currentTimeMillis()): String {
    val calendar = java.util.Calendar.getInstance().apply { timeInMillis = atMs }
    return when (calendar.get(java.util.Calendar.HOUR_OF_DAY)) {
        in 5..11 -> "Morning drive"
        in 12..16 -> "Afternoon drive"
        in 17..20 -> "Evening drive"
        else -> "Night drive"
    }
}
