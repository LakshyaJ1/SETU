package com.setu.navigator.data

import android.Manifest
import android.content.Context
import android.content.pm.PackageManager
import android.hardware.Sensor
import android.hardware.SensorEvent
import android.hardware.SensorEventListener
import android.hardware.SensorManager
import android.location.GnssMeasurementsEvent
import android.location.GnssStatus
import android.location.Location
import android.location.LocationListener
import android.location.LocationManager
import android.os.Handler
import android.os.HandlerThread
import android.os.Looper
import android.os.SystemClock
import androidx.core.location.LocationCompat
import com.setu.navigator.estimation.LiveEstimator
import com.setu.navigator.estimation.NativeEstimate
import com.setu.navigator.model.LiveModelSession
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import org.json.JSONArray
import org.json.JSONObject

class SensorHub(private val context: Context) : SensorEventListener, LocationListener {
    private val sensorManager = context.getSystemService(SensorManager::class.java)
    private val locationManager = context.getSystemService(LocationManager::class.java)
    private val accelerometer = sensorManager.getDefaultSensor(Sensor.TYPE_ACCELEROMETER)
    private val gyroscope = sensorManager.getDefaultSensor(Sensor.TYPE_GYROSCOPE)
    private val pressure = sensorManager.getDefaultSensor(Sensor.TYPE_PRESSURE)
    private val magnetometer = sensorManager.getDefaultSensor(Sensor.TYPE_MAGNETIC_FIELD)
    private val rotationVector = sensorManager.getDefaultSensor(Sensor.TYPE_ROTATION_VECTOR)
    private val gameRotationVector = sensorManager.getDefaultSensor(Sensor.TYPE_GAME_ROTATION_VECTOR)
    private val mutableNative = MutableStateFlow(NativeEstimate())
    val nativeEstimate = mutableNative.asStateFlow()
    @Volatile private var liveEstimator: LiveEstimator? = null
    @Volatile private var nativeGeneration = 0L
    private val mutableSensors = MutableStateFlow(SensorState(
        hasAccelerometer = accelerometer != null, hasGyroscope = gyroscope != null,
        hasBarometer = pressure != null, hasMagnetometer = magnetometer != null,
    ))
    private val mutablePose = MutableStateFlow<Pose?>(null)
    val sensors = mutableSensors.asStateFlow()
    val pose = mutablePose.asStateFlow()
    private val mutableLocationEnabled = MutableStateFlow(locationManager.isProviderEnabled(LocationManager.GPS_PROVIDER))
    val locationEnabled = mutableLocationEnabled.asStateFlow()
    @Volatile var record: ((JSONObject) -> Unit)? = null
    @Volatile var modelSession: LiveModelSession? = null
    @Volatile private var thread: HandlerThread? = null
    private var lastPublishNs = 0L
    private var rateStartNs = 0L
    private var rateSamples = 0
    private var sampleCount = 0L
    private var rate = 0.0
    private var acceleration = listOf(0f, 0f, 0f)
    private var angularRate = listOf(0f, 0f, 0f)
    private var pressureValue: Float? = null
    private var locationStarted = false

    private val satellites = object : GnssStatus.Callback() {
        override fun onSatelliteStatusChanged(status: GnssStatus) {
            val count = status.satelliteCount
            mutableSensors.update { previous -> previous.copy(
                satellites = count,
                satellitesUsed = (0 until count).count(status::usedInFix),
                meanCn0 = if (count > 0) (0 until count).map(status::getCn0DbHz).average().toFloat() else null,
            ) }
        }
    }
    private val rawGnss = object : GnssMeasurementsEvent.Callback() {
        override fun onGnssMeasurementsReceived(event: GnssMeasurementsEvent) {
            val measurements = JSONArray()
            event.measurements.forEach { measurement ->
                measurements.put(JSONObject().put("svid", measurement.svid)
                    .put("constellation", measurement.constellationType)
                    .put("cn0DbHz", measurement.cn0DbHz)
                    .put("pseudorangeRateMps", measurement.pseudorangeRateMetersPerSecond)
                    .put("pseudorangeRateSigmaMps", measurement.pseudorangeRateUncertaintyMetersPerSecond))
            }
            record?.invoke(JSONObject().put("type", "gnss_raw")
                .put("tNs", SystemClock.elapsedRealtimeNanos()).put("satellites", measurements))
        }
    }

    fun hasLocationPermission() = context.checkSelfPermission(Manifest.permission.ACCESS_FINE_LOCATION) == PackageManager.PERMISSION_GRANTED
    fun isLocationEnabled() = locationManager.isProviderEnabled(LocationManager.GPS_PROVIDER)

    @Synchronized
    fun start() {
        mutableLocationEnabled.value = isLocationEnabled()
        if (thread == null) {
            val worker = HandlerThread("setu-sensors").apply { start() }
            thread = worker
            rateStartNs = 0
            rateSamples = 0
            val handler = Handler(worker.looper)
            val generation = ++nativeGeneration
            handler.post {
                try {
                    val created = LiveEstimator(context, { estimate ->
                        if (nativeGeneration == generation) mutableNative.value = estimate
                    }, { document -> if (nativeGeneration == generation) record?.invoke(document) })
                    synchronized(this@SensorHub) {
                        if (nativeGeneration == generation) liveEstimator = created else created.close()
                    }
                } catch (_: LinkageError) {
                    mutableNative.value = NativeEstimate("Native library unavailable", "GPS and raw recording remain available.")
                } catch (_: Exception) {
                    mutableNative.value = NativeEstimate("Native initialization failed", "Could not load the packaged geophysics data. GPS remains available.")
                }
            }
            listOfNotNull(accelerometer, gyroscope, pressure, magnetometer, rotationVector, gameRotationVector).forEach { sensor ->
                sensorManager.registerListener(this, sensor, 5000, handler)
            }
        }
        startLocation()
    }

    @Suppress("MissingPermission")
    private fun startLocation() {
        if (locationStarted || !hasLocationPermission()) return
        try {
            locationManager.requestLocationUpdates(LocationManager.GPS_PROVIDER, 1000L, 0f, this, Looper.getMainLooper())
            locationManager.registerGnssStatusCallback(satellites, Handler(Looper.getMainLooper()))
            locationManager.registerGnssMeasurementsCallback(rawGnss, Handler(Looper.getMainLooper()))
            locationStarted = true
            locationManager.getLastKnownLocation(LocationManager.GPS_PROVIDER)?.let { location ->
                if (SystemClock.elapsedRealtimeNanos() - location.elapsedRealtimeNanos in 0 until 30_000_000_000L) onLocationChanged(location)
            }
        } catch (_: SecurityException) {
            locationStarted = false
        } catch (_: IllegalArgumentException) {
            locationStarted = false
        }
    }

    @Synchronized
    fun stop() {
        sensorManager.unregisterListener(this)
        locationManager.unregisterGnssMeasurementsCallback(rawGnss)
        locationManager.unregisterGnssStatusCallback(satellites)
        locationManager.removeUpdates(this)
        locationStarted = false
        val worker = thread
        val estimator = liveEstimator
        liveEstimator = null
        nativeGeneration++
        worker?.let { Handler(it.looper).post { estimator?.close() } }
        worker?.quitSafely()
        mutableNative.value = NativeEstimate("Native engine paused", "Reopens with fresh GPS and heading when sensing resumes.")
        thread = null
    }

    override fun onSensorChanged(event: SensorEvent) {
        if (Looper.myLooper() != thread?.looper) return
        liveEstimator?.sensor(event.sensor.type, event.timestamp, event.values, event.accuracy)
        sampleCount++
        val kind = when (event.sensor.type) {
            Sensor.TYPE_ACCELEROMETER -> {
                acceleration = event.values.take(3)
                modelSession?.acceleration(event.timestamp, event.values.take(3).map(Float::toDouble).toDoubleArray())
                if (rateStartNs == 0L) rateStartNs = event.timestamp
                rateSamples++
                val span = event.timestamp - rateStartNs
                if (span >= 1_000_000_000L) {
                    rate = (rateSamples - 1) * 1_000_000_000.0 / span
                    rateStartNs = event.timestamp
                    rateSamples = 1
                }
                "accelerometer"
            }
            Sensor.TYPE_GYROSCOPE -> {
                angularRate = event.values.take(3)
                modelSession?.gyroscope(event.timestamp, event.values.take(3).map(Float::toDouble).toDoubleArray())
                "gyroscope"
            }
            Sensor.TYPE_PRESSURE -> { pressureValue = event.values.firstOrNull(); "barometer" }
            Sensor.TYPE_MAGNETIC_FIELD -> "magnetometer"
            Sensor.TYPE_ROTATION_VECTOR -> "rotation_vector"
            Sensor.TYPE_GAME_ROTATION_VECTOR -> "game_rotation_vector"
            else -> return
        }
        record?.invoke(JSONObject().put("type", kind).put("tNs", event.timestamp)
            .put("values", JSONArray(event.values.toList())).put("accuracy", event.accuracy))
        if (event.timestamp - lastPublishNs >= 100_000_000L) {
            lastPublishNs = event.timestamp
            mutableSensors.update { previous -> previous.copy(
                accelerometer = acceleration, gyroscope = angularRate, pressure = pressureValue,
                achievedHz = rate, sampleCount = sampleCount, lastSampleNs = event.timestamp,
            ) }
        }
    }

    override fun onLocationChanged(location: Location) {
        val current = locationPose(location, SystemClock.elapsedRealtimeNanos()) ?: return
        if (current.timestampNs <= (mutablePose.value?.timestampNs ?: 0L)) return
        mutablePose.value = current
        thread?.let { worker -> Handler(worker.looper).post { if (thread == worker) liveEstimator?.gnss(current, location.time) } }
        record?.invoke(TripStore.encodePose(current))
    }

    override fun onProviderDisabled(provider: String) {
        if (provider == LocationManager.GPS_PROVIDER) {
            mutableLocationEnabled.value = false
            mutablePose.value = null
            record?.invoke(JSONObject().put("type", "location_state").put("tNs", SystemClock.elapsedRealtimeNanos()).put("enabled", false))
        }
    }

    override fun onProviderEnabled(provider: String) {
        if (provider == LocationManager.GPS_PROVIDER) {
            mutableLocationEnabled.value = true
            record?.invoke(JSONObject().put("type", "location_state").put("tNs", SystemClock.elapsedRealtimeNanos()).put("enabled", true))
        }
    }

    override fun onAccuracyChanged(sensor: Sensor?, accuracy: Int) = Unit
}

internal fun locationPose(location: Location, nowNs: Long): Pose? {
    if (!location.latitude.isFinite() || location.latitude !in -90.0..90.0 ||
        !location.longitude.isFinite() || location.longitude !in -180.0..180.0 ||
        location.elapsedRealtimeNanos <= 0 || location.elapsedRealtimeNanos > nowNs) return null
    val speed = location.speed.toDouble().takeIf { location.hasSpeed() && it.isFinite() && it >= 0 }
    val bearing = location.bearing.toDouble().takeIf { location.hasBearing() && it.isFinite() && it in 0.0..<360.0 }
    val altitude = location.altitude.takeIf { location.hasAltitude() && it.isFinite() }
    val mock = LocationCompat.isMock(location)
    return Pose(
        point = GeoPoint(location.latitude, location.longitude), speedMps = speed, bearing = bearing,
        accuracyMeters = location.accuracy.toDouble().takeIf { location.hasAccuracy() && it.isFinite() && it >= 0 },
        timestampNs = location.elapsedRealtimeNanos, source = if (mock) "Test location" else "GPS",
        altitudeMeters = altitude,
        verticalAccuracyMeters = location.verticalAccuracyMeters.toDouble().takeIf { altitude != null && location.hasVerticalAccuracy() && it.isFinite() && it >= 0 },
        speedAccuracyMps = location.speedAccuracyMetersPerSecond.toDouble().takeIf { speed != null && location.hasSpeedAccuracy() && it.isFinite() && it >= 0 },
        bearingAccuracyDegrees = location.bearingAccuracyDegrees.toDouble().takeIf { bearing != null && location.hasBearingAccuracy() && it.isFinite() && it >= 0 },
        mock = mock,
    )
}
