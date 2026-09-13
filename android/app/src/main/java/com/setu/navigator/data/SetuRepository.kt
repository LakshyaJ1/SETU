package com.setu.navigator.data

import android.content.Context
import android.os.SystemClock
import com.setu.navigator.estimation.navigationPose
import com.setu.navigator.model.HttpModelProvider
import com.setu.navigator.model.OnDeviceModelProvider
import com.setu.navigator.model.LiveModelSession
import com.setu.navigator.model.ModelInferenceState
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.currentCoroutineContext
import kotlinx.coroutines.ensureActive
import kotlinx.coroutines.launch
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.collectLatest
import org.json.JSONObject
import java.io.BufferedWriter
import java.util.UUID

class SetuRepository(private val context: Context) {
    var uiVisible = false
    val hub = SensorHub(context)
    val mapPacks = MapPackStore(context)
    val maps get() = mapPacks.activeMap.value
    val tripStore = TripStore(context)
    private val preferences = context.getSharedPreferences("setu-settings", Context.MODE_PRIVATE)
    private val mutableSettings = MutableStateFlow(readSettings())
    val settings = mutableSettings.asStateFlow()
    private val mutableTrips = MutableStateFlow<List<Trip>>(emptyList())
    val trips = mutableTrips.asStateFlow()
    private val mutableRecording = MutableStateFlow(false)
    val recording = mutableRecording.asStateFlow()
    private val mutableRecordCount = MutableStateFlow(0L)
    val recordCount = mutableRecordCount.asStateFlow()
    private val mutableError = MutableStateFlow<String?>(null)
    val error = mutableError.asStateFlow()
    private val mutableModelInference = MutableStateFlow(ModelInferenceState())
    val modelInference = mutableModelInference.asStateFlow()
    private var modelGeneration = 0L
    var recordingStartedNs = 0L
        private set
    private var recordingStartedMs = 0L
    @Volatile private var recordingId = ""
    private var recordingName = ""
    private var writer: BufferedWriter? = null
    private var recorder: LogRecorder? = null
    private val trackLock = Any()
    private val recordedPoses = mutableListOf<Pose>()
    private val storageScope = CoroutineScope(SupervisorJob() + Dispatchers.IO)

    init {
        refreshModelSession()
        storageScope.launch {
            mapPacks.restore()
            val count = tripStore.recoverIncomplete { recordingId }
            refreshTrips()
            if (count > 0) mutableError.value = "Recovered $count interrupted recording(s). Find them in Trips."
        }
        // Load and index the active region's routing graph in the background so the first
        // destination search does not pay for it. A failure here is not surfaced: the route call
        // will retry the same work and report properly if it still fails.
        storageScope.launch {
            mapPacks.activeMap.collectLatest { map ->
                // Captured here so the blocking warm-up can check cancellation from its own thread
                // when the active region changes underneath it.
                val operation = currentCoroutineContext()
                runCatching { map.warmUp { operation.ensureActive() } }
            }
        }
    }

    @Synchronized
    fun updateSettings(requested: AppSettings) {
        val previous = mutableSettings.value
        val updated = if (requested.modelEndpoint != previous.modelEndpoint) requested.copy(modelSharingAllowed = false) else requested
        preferences.edit().putString("theme", updated.theme).putString("units", updated.units)
            .putString("vehicle", updated.vehicle).putBoolean("keepScreenOn", updated.keepScreenOn)
            .putString("modelEndpoint", updated.modelEndpoint)
            .putBoolean("onDeviceSpeedModel", updated.onDeviceSpeedModel)
            .putBoolean("modelSharingAllowed", updated.modelSharingAllowed)
            .putInt("modelSharingConsentVersion", if (updated.modelSharingAllowed) 1 else 0).apply()
        preferences.edit().putBoolean("nativePositioning", updated.nativePositioning).apply()
        mutableSettings.value = updated
        if (previous.modelEndpoint != updated.modelEndpoint || previous.vehicle != updated.vehicle ||
            previous.modelSharingAllowed != updated.modelSharingAllowed ||
            previous.onDeviceSpeedModel != updated.onDeviceSpeedModel) refreshModelSession()
    }

    private fun readSettings() = AppSettings(
        preferences.getString("theme", "System") ?: "System",
        preferences.getString("units", "km/h") ?: "km/h",
        preferences.getString("vehicle", "Car") ?: "Car",
        preferences.getBoolean("keepScreenOn", true),
        preferences.getString("modelEndpoint", AppSettings().modelEndpoint) ?: AppSettings().modelEndpoint,
        preferences.getInt("modelSharingConsentVersion", 0) == 1 && preferences.getBoolean("modelSharingAllowed", false),
        preferences.getBoolean("nativePositioning", false),
        preferences.getBoolean("onDeviceSpeedModel", AppSettings().onDeviceSpeedModel),
    )

    @Synchronized
    fun beginRecording(name: String) {
        if (mutableRecording.value) return
        recordingId = UUID.randomUUID().toString()
        recordingName = name.ifBlank { "My drive" }.take(100)
        recordingStartedNs = SystemClock.elapsedRealtimeNanos()
        recordingStartedMs = System.currentTimeMillis()
        mutableError.value = null
        mutableRecordCount.value = 0
        synchronized(trackLock) { recordedPoses.clear() }
        val output = tripStore.logFile(recordingId).bufferedWriter()
        writer = output
        output.appendLine(JSONObject().put("schema", "setu.log.v1").put("name", recordingName)
            .put("startedAtMs", recordingStartedMs).put("startedAtNs", recordingStartedNs).put("synthetic", false)
            .put("trajectoryStream", "track_pose")
            .put("device", "${android.os.Build.MANUFACTURER} ${android.os.Build.MODEL}")
            .put("clock", "elapsedRealtimeNanos").put("units", "SI").toString())
        output.flush()
        // Serialisation, buffering and flushing move to the recorder's own thread so the sensor
        // callback never allocates, never blocks on this monitor and never touches disk.
        val active = LogRecorder(output, ::deriveTrackPose, { count, dropped ->
            mutableRecordCount.value = count
            if (dropped > 0) mutableError.value = "$dropped sensor record(s) were dropped because storage could not keep up."
        }, { failure ->
            storageScope.launch {
                mutableError.value = "Recording could not be written: ${failure.message}"
                finishRecording()
            }
        })
        recorder = active
        mutableRecording.value = true
        hub.record = active::document
        hub.sensorSink = active
        refreshModelSession()
        hub.start()
    }

    /**
     * Chooses the trajectory sample that follows a raw `pose` or `native_pose` record. Runs on the
     * recorder thread, so the pose list it appends to is guarded separately from this class's
     * monitor and never blocks acquisition.
     */
    private fun deriveTrackPose(type: String): JSONObject? {
        val now = SystemClock.elapsedRealtimeNanos()
        val pose = navigationPose(hub.pose.value, hub.nativeEstimate.value, settings.value.nativePositioning, now)
            ?.takeIf { it.isFresh(now) && it.timestampNs >= recordingStartedNs } ?: return null
        synchronized(trackLock) {
            val previous = recordedPoses.lastOrNull()
            if (previous != null && pose.timestampNs <= previous.timestampNs) return null
            recordedPoses.add(pose)
        }
        return TripStore.encodePose(pose).put("type", "track_pose")
    }

    private fun refreshModelSession() {
        val generation = ++modelGeneration
        hub.modelSession?.close()
        hub.modelSession = null
        val configuration = settings.value
        // The on-device model is the navigation path and takes precedence. The remote server stays
        // available as a research tool, still behind explicit consent and still only while
        // recording, because that one does send sensor data off the phone.
        val onDevice = configuration.onDeviceSpeedModel
        if (!onDevice && !configuration.modelSharingAllowed) {
            mutableModelInference.value = ModelInferenceState()
            return
        }
        if (!onDevice && !recording.value) {
            mutableModelInference.value = ModelInferenceState("Ready for recording", "Sensor sharing runs only during an active recording or recorded drive.")
            return
        }
        try {
            mutableModelInference.value = ModelInferenceState("Collecting sensor window", "Waiting for four continuous seconds of accelerometer and gyroscope data.")
            val provider = if (onDevice) OnDeviceModelProvider(context) else HttpModelProvider(configuration.modelEndpoint)
            hub.modelSession = LiveModelSession(provider, configuration.vehicle,
                SystemClock::elapsedRealtimeNanos,
                { state -> synchronized(this) { if (generation == modelGeneration) mutableModelInference.value = state } },
                { state -> synchronized(this) {
                    if (generation != modelGeneration) return@synchronized
                    val measurement = state.measurement
                    // Fuse it. A measurement that never reaches the filter is a readout, not a
                    // navigation input, and running the model on the phone is pointless otherwise.
                    // Validity is zero unless every gate in the provider passed, so a rejected
                    // window contributes nothing rather than contributing badly.
                    var applied = false
                    if (onDevice && measurement != null && measurement.validity > 0.0) {
                        hub.applyModelSpeed(measurement.timestampNs, measurement.speedMps, measurement.sigmaMps)
                        applied = true
                    }
                    if (recording.value) {
                        appendRecord(JSONObject().put("type", "model_measurement").put("tNs", state.receivedAtNs)
                            .put("model", state.health?.name).put("status", state.status).put("detail", state.detail)
                            .put("measurementTimestampNs", measurement?.timestampNs ?: JSONObject.NULL)
                            .put("speedMps", measurement?.speedMps ?: JSONObject.NULL)
                            .put("sigmaMps", measurement?.sigmaMps ?: JSONObject.NULL)
                            .put("validity", measurement?.validity ?: JSONObject.NULL)
                            .put("latencyMs", state.latencyMs ?: JSONObject.NULL).put("navigationApplied", applied))
                    }
                } })
        } catch (error: Exception) {
            mutableModelInference.value = ModelInferenceState("Model configuration needs attention", error.message ?: "Check the server URL.")
        }
    }

    private fun appendRecord(record: JSONObject) {
        recorder?.document(record)
    }

    @Synchronized
    fun finishRecording(): Trip? {
        if (!mutableRecording.value) {
            runCatching { writer?.close() }
            writer = null
            return null
        }
        hub.record = null
        hub.sensorSink = null
        val active = recorder
        recorder = null
        // Draining the recorder first guarantees every queued sample is on disk before the end
        // marker, and joins its thread so the writer below is unshared.
        val drainFailure = runCatching { active?.close() }.exceptionOrNull()
        val finishedAtNs = SystemClock.elapsedRealtimeNanos()
        var written = active?.records ?: 0L
        try {
            if (drainFailure != null) throw drainFailure
            writer?.appendLine(JSONObject().put("type", "end").put("tNs", finishedAtNs).toString())
            written++
            writer?.flush()
            writer?.close()
            writer = null
            val poses = synchronized(trackLock) { recordedPoses.toList() }
            val trip = Trip(recordingId, recordingName, recordingStartedMs,
                (finishedAtNs - recordingStartedNs) / 1_000_000,
                trajectoryDistance(poses), written, poses)
            tripStore.save(trip)
            mutableRecordCount.value = written
            refreshTrips()
            return trip
        } catch (error: Exception) {
            mutableError.value = "The recording was interrupted: ${error.message}. Its raw log is kept for recovery."
            return null
        } finally {
            runCatching { writer?.close() }
            writer = null
            mutableRecording.value = false
            refreshModelSession()
        }
    }

    fun refreshTrips() { mutableTrips.value = tripStore.all() }
    fun clearError() { mutableError.value = null }
    fun reportError(message: String) { mutableError.value = message }
}
