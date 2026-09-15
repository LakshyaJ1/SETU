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
import android.os.CancellationSignal
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
    private val stepDetector = sensorManager.getDefaultSensor(Sensor.TYPE_STEP_DETECTOR)
    @Volatile private var walkingStepMeters: Double? = null
    @Volatile private var activity = "Car"
    @Volatile private var stepRegistered = false
    private val mutableNative = MutableStateFlow(NativeEstimate())
    val nativeEstimate = mutableNative.asStateFlow()
    @Volatile private var liveEstimator: LiveEstimator? = null
    @Volatile private var nativeGeneration = 0L
    private val mutableSensors = MutableStateFlow(SensorState(
        hasAccelerometer = accelerometer != null, hasGyroscope = gyroscope != null,
        hasBarometer = pressure != null, hasMagnetometer = magnetometer != null,
        hasStepDetector = stepDetector != null,
    ))
    private val mutablePose = MutableStateFlow<Pose?>(null)
    val sensors = mutableSensors.asStateFlow()
    val pose = mutablePose.asStateFlow()
    private val mutableLocationEnabled = MutableStateFlow(anyProviderEnabled())
    val locationEnabled = mutableLocationEnabled.asStateFlow()
    @Volatile var record: ((JSONObject) -> Unit)? = null

    /**
     * Allocation-free destination for raw sensor samples. When set it replaces the per-callback
     * `JSONObject` encoding; when null (unit tests, no active recording) the JSON path still runs so
     * the observable behaviour is unchanged.
     */
    @Volatile var sensorSink: SensorSink? = null
    @Volatile var modelSession: LiveModelSession? = null

    /**
     * Hand a learned speed to the native estimator.
     *
     * Inference runs off the sensor thread, but the engine may only be touched from it, so the
     * application is posted there. A measurement that arrives while the estimator is being torn
     * down is dropped rather than queued: by the time a queue drained, it would be describing a
     * moment the filter has already left.
     */
    fun applyModelSpeed(timestampNs: Long, speedMps: Double, sigmaMps: Double, applied: (Boolean) -> Unit) {
        val worker = thread
        val generation = nativeGeneration
        val session = modelSession
        if (worker == null || session == null) { applied(false); return }
        val posted = Handler(worker.looper).post {
            val current = thread === worker && nativeGeneration == generation && modelSession === session
            applied(current && liveEstimator?.speed(timestampNs, speedMps, sigmaMps) == 1)
        }
        if (!posted) applied(false)
    }
    @Volatile private var thread: HandlerThread? = null
    private var lastPublishNs = 0L
    private var rateStartNs = 0L
    private var rateSamples = 0
    private var sampleCount = 0L
    private var rate = 0.0
    private var acceleration = listOf(0f, 0f, 0f)
    private var angularRate = listOf(0f, 0f, 0f)
    private val latestAcceleration = FloatArray(3)
    private val latestAngularRate = FloatArray(3)
    private val sampleScratch = DoubleArray(3)
    private var pressureValue: Float? = null
    private var locationStarted = false
    private val locationRequests = mutableListOf<CancellationSignal>()

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
    fun hasStepPermission() = android.os.Build.VERSION.SDK_INT < 29 ||
        context.checkSelfPermission(Manifest.permission.ACTIVITY_RECOGNITION) == PackageManager.PERMISSION_GRANTED
    fun isLocationEnabled() = anyProviderEnabled()

    @Synchronized
    fun configureActivity(settings: AppSettings) {
        val length = settings.walkingStepLengthMeters.takeIf { settings.vehicle == "Walking" }
        if (walkingStepMeters == length && activity == settings.vehicle) return
        walkingStepMeters = length
        activity = settings.vehicle
        mutableNative.value = NativeEstimate("Activity changed", "Waiting for fresh GPS and heading for ${settings.vehicle}.")
        thread?.let { initializeEstimator(Handler(it.looper)) }
    }

    private fun initializeEstimator(handler: Handler) {
        val generation = ++nativeGeneration
        val length = walkingStepMeters
        val vehicle = activity
        val previous = liveEstimator
        liveEstimator = null
        handler.post {
            previous?.close()
            if (nativeGeneration != generation) return@post
            try {
                val created = LiveEstimator(context, { estimate ->
                    if (nativeGeneration == generation) mutableNative.value = estimate
                }, { document -> if (nativeGeneration == generation) record?.invoke(document) }, walkingStepMeters = length,
                    stepSensorAvailable = { stepRegistered && hasStepPermission() }, vehicle = vehicle)
                synchronized(this@SensorHub) {
                    if (nativeGeneration == generation) liveEstimator = created else created.close()
                }
            } catch (_: LinkageError) {
                mutableNative.value = NativeEstimate("Native library unavailable", "GPS and raw recording remain available.")
            } catch (_: Exception) {
                mutableNative.value = NativeEstimate("Native initialization failed", "Could not load the packaged geophysics data. GPS remains available.")
            }
        }
    }

    // "Location is on" means any provider can answer, not specifically the satellite one. Keying
    // this to GPS_PROVIDER alone reported the service as off whenever the user had chosen
    // battery-saving location mode.
    private fun anyProviderEnabled(): Boolean =
        listOf(LocationManager.GPS_PROVIDER, LocationManager.NETWORK_PROVIDER)
            .any { provider -> runCatching { locationManager.isProviderEnabled(provider) }.getOrDefault(false) } ||
            (android.os.Build.VERSION.SDK_INT >= 31 &&
                runCatching { locationManager.isProviderEnabled(LocationManager.FUSED_PROVIDER) }.getOrDefault(false))

    @Synchronized
    fun start() {
        mutableLocationEnabled.value = isLocationEnabled()
        if (thread == null) {
            val worker = HandlerThread("setu-sensors").apply { start() }
            thread = worker
            rateStartNs = 0
            rateSamples = 0
            val handler = Handler(worker.looper)
            initializeEstimator(handler)
            // Only the inertial pair needs the full rate. Requesting 200 Hz from the magnetometer
            // and both fused rotation vectors doubled the callback volume and made Android run its
            // orientation fusion 400 times a second, for channels that seed attitude and check
            // compass health at a few hertz. The compass freshness checks allow 100 ms, so 50 Hz
            // keeps every existing gate satisfied with a wide margin.
            listOfNotNull(accelerometer, gyroscope).forEach { sensor ->
                sensorManager.registerListener(this, sensor, INERTIAL_PERIOD_US, handler)
            }
            listOfNotNull(magnetometer, rotationVector, gameRotationVector).forEach { sensor ->
                sensorManager.registerListener(this, sensor, ATTITUDE_PERIOD_US, handler)
            }
            pressure?.let { sensorManager.registerListener(this, it, BAROMETER_PERIOD_US, handler) }
        }
        if (!hasStepPermission() && stepRegistered) {
            stepDetector?.let { sensorManager.unregisterListener(this, it) }
            stepRegistered = false
        }
        if (!stepRegistered && stepDetector != null && hasStepPermission()) {
            stepRegistered = runCatching {
                sensorManager.registerListener(this, stepDetector, SensorManager.SENSOR_DELAY_NORMAL, Handler(checkNotNull(thread).looper))
            }.getOrDefault(false)
        }
        mutableSensors.update { it.copy(stepDetectorActive = stepRegistered) }
        startLocation()
    }

    /**
     * Providers to subscribe to, best first.
     *
     * Only GPS_PROVIDER used to be requested. That is the raw satellite provider: outdoors with a
     * warm almanac it is quick, but from cold, indoors, or in a street of tall buildings its first
     * fix takes minutes and may never arrive, which is why the app could sit on "Finding GPS" for
     * a quarter of an hour with location switched on and working. The fused provider answers in a
     * second or two from Wi-Fi and cell, and the platform upgrades it to satellite quality as soon
     * as that is available.
     */
    private fun locationProviders(): List<String> = buildList {
        if (android.os.Build.VERSION.SDK_INT >= 31) add(LocationManager.FUSED_PROVIDER)
        add(LocationManager.GPS_PROVIDER)
        add(LocationManager.NETWORK_PROVIDER)
    }.filter { provider -> provider in locationManager.allProviders }

    @Suppress("MissingPermission")
    private fun startLocation() {
        if (locationStarted || !hasLocationPermission()) return
        val main = Looper.getMainLooper()
        val providers = locationProviders()
        if (providers.isEmpty()) return
        try {
            val subscribed = providers.map { provider ->
                runCatching { locationManager.requestLocationUpdates(provider, 1000L, 0f, this, main) }.isSuccess
            }
            locationStarted = subscribed.any { it }
            if (!locationStarted) return
            // Raw GNSS and satellite status only exist on the satellite provider, and only matter
            // for the recorded log and the health readout, so a failure here must not stop the
            // position updates above.
            runCatching { locationManager.registerGnssStatusCallback(satellites, Handler(main)) }
            runCatching { locationManager.registerGnssMeasurementsCallback(rawGnss, Handler(main)) }

            // Show something immediately. The old code looked only at the satellite provider and
            // discarded anything over 30 s old, so on a normal cold start it almost always found
            // nothing and the screen stayed empty until a satellite fix landed. A minutes-old fix
            // is a far better answer than no answer: it is marked stale by Pose.isFresh, so the UI
            // already labels it "Last GPS fix" rather than claiming it is current.
            providers.asSequence()
                .mapNotNull { provider -> runCatching { locationManager.getLastKnownLocation(provider) }.getOrNull() }
                .filter { location ->
                    val age = SystemClock.elapsedRealtimeNanos() - location.elapsedRealtimeNanos
                    age in 0 until 600_000_000_000L
                }
                .maxByOrNull { location -> location.elapsedRealtimeNanos }
                ?.let(::onLocationChanged)

            // Actively drive one fresh fix rather than waiting for the periodic stream to produce
            // its first sample, which is what makes the difference between a few seconds and a few
            // minutes on a cold start.
            if (android.os.Build.VERSION.SDK_INT >= 30) {
                val generation = nativeGeneration
                providers.forEach { provider ->
                    runCatching {
                        val cancellation = CancellationSignal()
                        locationRequests.add(cancellation)
                        locationManager.getCurrentLocation(provider, cancellation, context.mainExecutor) { location ->
                            if (nativeGeneration == generation && location != null) onLocationChanged(location)
                        }
                    }
                }
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
        stepRegistered = false
        mutableSensors.update { it.copy(stepDetectorActive = false) }
        locationManager.unregisterGnssMeasurementsCallback(rawGnss)
        locationManager.unregisterGnssStatusCallback(satellites)
        locationManager.removeUpdates(this)
        locationRequests.forEach(CancellationSignal::cancel)
        locationRequests.clear()
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
        val values = event.values
        liveEstimator?.sensor(event.sensor.type, event.timestamp, values, event.accuracy)
        sampleCount++
        // Nothing on this path may allocate: it runs for every callback of five sensors, so roughly
        // a thousand times a second on a 200 Hz phone. Latest values are copied into reusable
        // scratch arrays and only turned into lists at the 10 Hz publish below.
        val kind = when (event.sensor.type) {
            Sensor.TYPE_ACCELEROMETER -> {
                if (values.size < 3) return
                latestAcceleration[0] = values[0]; latestAcceleration[1] = values[1]; latestAcceleration[2] = values[2]
                modelSession?.let { session ->
                    sampleScratch[0] = values[0].toDouble(); sampleScratch[1] = values[1].toDouble(); sampleScratch[2] = values[2].toDouble()
                    session.acceleration(event.timestamp, sampleScratch)
                }
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
                if (values.size < 3) return
                latestAngularRate[0] = values[0]; latestAngularRate[1] = values[1]; latestAngularRate[2] = values[2]
                modelSession?.let { session ->
                    sampleScratch[0] = values[0].toDouble(); sampleScratch[1] = values[1].toDouble(); sampleScratch[2] = values[2].toDouble()
                    session.gyroscope(event.timestamp, sampleScratch)
                }
                "gyroscope"
            }
            Sensor.TYPE_PRESSURE -> { pressureValue = values.firstOrNull(); "barometer" }
            Sensor.TYPE_MAGNETIC_FIELD -> "magnetometer"
            Sensor.TYPE_ROTATION_VECTOR -> "rotation_vector"
            Sensor.TYPE_GAME_ROTATION_VECTOR -> "game_rotation_vector"
            Sensor.TYPE_STEP_DETECTOR -> "step_detector"
            else -> return
        }
        val sink = sensorSink
        if (sink != null) sink.sensor(kind, event.timestamp, values, values.size, event.accuracy)
        else record?.invoke(JSONObject().put("type", kind).put("tNs", event.timestamp)
            .put("values", JSONArray(values.toList())).put("accuracy", event.accuracy))
        if (event.timestamp - lastPublishNs >= 100_000_000L) {
            lastPublishNs = event.timestamp
            acceleration = listOf(latestAcceleration[0], latestAcceleration[1], latestAcceleration[2])
            angularRate = listOf(latestAngularRate[0], latestAngularRate[1], latestAngularRate[2])
            mutableSensors.update { previous -> previous.copy(
                accelerometer = acceleration, gyroscope = angularRate, pressure = pressureValue,
                achievedHz = rate, sampleCount = sampleCount, lastSampleNs = event.timestamp,
            ) }
        }
    }

    override fun onLocationChanged(location: Location) {
        if (thread == null) return
        updateLocation(location)
    }

    internal fun updateLocation(location: Location) {
        val current = locationPose(location, SystemClock.elapsedRealtimeNanos()) ?: return
        record?.invoke(TripStore.encodePose(current).put("type", "gnss_reference")
            .put("provider", location.provider ?: JSONObject.NULL).put("wallTimeMs", location.time)
            .put("receivedAtNs", SystemClock.elapsedRealtimeNanos()))
        if (current.timestampNs <= (mutablePose.value?.timestampNs ?: 0L)) return
        mutablePose.value = current
        // A Wi-Fi or cell fix is worth showing - it answers "roughly where am I" in a second - but
        // it is not worth fusing: at a few hundred metres it would drag the filter around and undo
        // the dead-reckoning it is supposed to anchor. The engine rejects anything worse than 100 m
        // outright; this keeps the estimator on fixes that are actually satellite-grade.
        val usable = current.accuracyMeters?.let { it <= ESTIMATOR_ACCURACY_LIMIT_METRES } == true
        if (usable) {
            thread?.let { worker -> Handler(worker.looper).post { if (thread == worker) liveEstimator?.gnss(current, location.time) } }
        }
        record?.invoke(TripStore.encodePose(current).put("provider", location.provider ?: JSONObject.NULL)
            .put("wallTimeMs", location.time).put("receivedAtNs", SystemClock.elapsedRealtimeNanos()))
    }

    override fun onProviderDisabled(provider: String) {
        val enabled = anyProviderEnabled()
        if (mutableLocationEnabled.value == enabled) return
        mutableLocationEnabled.value = enabled
        if (!enabled) mutablePose.value = null
        record?.invoke(JSONObject().put("type", "location_state").put("tNs", SystemClock.elapsedRealtimeNanos()).put("enabled", enabled))
    }

    override fun onProviderEnabled(provider: String) {
        val enabled = anyProviderEnabled()
        if (mutableLocationEnabled.value == enabled) return
        mutableLocationEnabled.value = enabled
        record?.invoke(JSONObject().put("type", "location_state").put("tNs", SystemClock.elapsedRealtimeNanos()).put("enabled", enabled))
    }

    override fun onAccuracyChanged(sensor: Sensor?, accuracy: Int) = Unit

    private companion object {
        // Satellite fixes are typically 3-10 m; network fixes are hundreds. Anything coarser than
        // this is shown to the user but never fused.
        const val ESTIMATOR_ACCURACY_LIMIT_METRES = 35.0
        const val INERTIAL_PERIOD_US = 5_000    // 200 Hz: accelerometer and gyroscope
        const val ATTITUDE_PERIOD_US = 20_000   // 50 Hz: magnetometer and rotation vectors
        const val BAROMETER_PERIOD_US = 100_000 // 10 Hz: pressure
    }
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
