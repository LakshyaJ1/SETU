package com.setu.navigator.data

import android.content.Context
import android.os.SystemClock
import com.setu.navigator.estimation.navigationPose
import com.setu.navigator.model.HttpModelProvider
import com.setu.navigator.model.LiveModelSession
import com.setu.navigator.model.ModelInferenceState
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.launch
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.asStateFlow
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
    private val recordedPoses = mutableListOf<Pose>()
    private var records = 0L
    private var lastFlushNs = 0L
    private val storageScope = CoroutineScope(SupervisorJob() + Dispatchers.IO)

    init {
        refreshModelSession()
        storageScope.launch {
            mapPacks.restore()
            val count = tripStore.recoverIncomplete { recordingId }
            refreshTrips()
            if (count > 0) mutableError.value = "Recovered $count interrupted recording(s). Find them in Trips."
        }
    }

    @Synchronized
    fun updateSettings(requested: AppSettings) {
        val previous = mutableSettings.value
        val updated = if (requested.modelEndpoint != previous.modelEndpoint) requested.copy(modelSharingAllowed = false) else requested
        preferences.edit().putString("theme", updated.theme).putString("units", updated.units)
            .putString("vehicle", updated.vehicle).putBoolean("keepScreenOn", updated.keepScreenOn)
            .putString("modelEndpoint", updated.modelEndpoint)
            .putBoolean("modelSharingAllowed", updated.modelSharingAllowed)
            .putInt("modelSharingConsentVersion", if (updated.modelSharingAllowed) 1 else 0).apply()
        preferences.edit().putBoolean("nativePositioning", updated.nativePositioning).apply()
        mutableSettings.value = updated
        if (previous.modelEndpoint != updated.modelEndpoint || previous.vehicle != updated.vehicle ||
            previous.modelSharingAllowed != updated.modelSharingAllowed) refreshModelSession()
    }

    private fun readSettings() = AppSettings(
        preferences.getString("theme", "System") ?: "System",
        preferences.getString("units", "km/h") ?: "km/h",
        preferences.getString("vehicle", "Car") ?: "Car",
        preferences.getBoolean("keepScreenOn", true),
        preferences.getString("modelEndpoint", AppSettings().modelEndpoint) ?: AppSettings().modelEndpoint,
        preferences.getInt("modelSharingConsentVersion", 0) == 1 && preferences.getBoolean("modelSharingAllowed", false),
        preferences.getBoolean("nativePositioning", false),
    )

    @Synchronized
    fun beginRecording(name: String) {
        if (mutableRecording.value) return
        recordingId = UUID.randomUUID().toString()
        recordingName = name.ifBlank { "My drive" }.take(100)
        recordingStartedNs = SystemClock.elapsedRealtimeNanos()
        recordingStartedMs = System.currentTimeMillis()
        records = 0
        lastFlushNs = recordingStartedNs
        mutableError.value = null
        mutableRecordCount.value = 0
        recordedPoses.clear()
        writer = tripStore.logFile(recordingId).bufferedWriter()
        writer!!.appendLine(JSONObject().put("schema", "setu.log.v1").put("name", recordingName)
            .put("startedAtMs", recordingStartedMs).put("startedAtNs", recordingStartedNs).put("synthetic", false)
            .put("trajectoryStream", "track_pose")
            .put("device", "${android.os.Build.MANUFACTURER} ${android.os.Build.MODEL}")
            .put("clock", "elapsedRealtimeNanos").put("units", "SI").toString())
        writer!!.flush()
        mutableRecording.value = true
        hub.record = ::appendRecord
        refreshModelSession()
        hub.start()
    }

    private fun refreshModelSession() {
        val generation = ++modelGeneration
        hub.modelSession?.close()
        hub.modelSession = null
        val configuration = settings.value
        if (!configuration.modelSharingAllowed) {
            mutableModelInference.value = ModelInferenceState()
            return
        }
        if (!recording.value) {
            mutableModelInference.value = ModelInferenceState("Ready for recording", "Sensor sharing runs only during an active recording or recorded drive.")
            return
        }
        try {
            mutableModelInference.value = ModelInferenceState("Collecting sensor window", "Waiting for four continuous seconds of accelerometer and gyroscope data.")
            hub.modelSession = LiveModelSession(HttpModelProvider(configuration.modelEndpoint), configuration.vehicle,
                SystemClock::elapsedRealtimeNanos,
                { state -> synchronized(this) { if (generation == modelGeneration) mutableModelInference.value = state } },
                { state -> synchronized(this) {
                    if (generation == modelGeneration && recording.value) {
                        val measurement = state.measurement
                        appendRecord(JSONObject().put("type", "model_measurement").put("tNs", state.receivedAtNs)
                            .put("model", state.health?.name).put("status", state.status).put("detail", state.detail)
                            .put("measurementTimestampNs", measurement?.timestampNs ?: JSONObject.NULL)
                            .put("speedMps", measurement?.speedMps ?: JSONObject.NULL)
                            .put("sigmaMps", measurement?.sigmaMps ?: JSONObject.NULL)
                            .put("validity", measurement?.validity ?: JSONObject.NULL)
                            .put("latencyMs", state.latencyMs ?: JSONObject.NULL).put("navigationApplied", false))
                    }
                } })
        } catch (error: Exception) {
            mutableModelInference.value = ModelInferenceState("Model configuration needs attention", error.message ?: "Check the server URL.")
        }
    }

    @Synchronized
    private fun appendRecord(record: JSONObject) {
        val output = writer ?: return
        try {
            output.appendLine(record.toString())
            records++
            if (record.optString("type") in listOf("pose", "native_pose")) {
                val now = SystemClock.elapsedRealtimeNanos()
                val pose = navigationPose(hub.pose.value, hub.nativeEstimate.value, settings.value.nativePositioning, now)
                    ?.takeIf { it.isFresh(now) && it.timestampNs >= recordingStartedNs }
                val previous = recordedPoses.lastOrNull()
                if (pose != null && (previous == null || pose.timestampNs > previous.timestampNs)) {
                    output.appendLine(TripStore.encodePose(pose).put("type", "track_pose").toString())
                    records++
                    recordedPoses.add(pose)
                }
            }
            val now = SystemClock.elapsedRealtimeNanos()
            if (now - lastFlushNs > 1_000_000_000L) {
                output.flush()
                lastFlushNs = now
                mutableRecordCount.value = records
            }
        } catch (error: Exception) {
            mutableError.value = "Recording could not be written: ${error.message}"
            hub.record = null
            finishRecording()
        }
    }

    @Synchronized
    fun finishRecording(): Trip? {
        if (!mutableRecording.value) {
            runCatching { writer?.close() }
            writer = null
            return null
        }
        hub.record = null
        val finishedAtNs = SystemClock.elapsedRealtimeNanos()
        try {
            writer?.appendLine(JSONObject().put("type", "end").put("tNs", finishedAtNs).toString())
            writer?.flush()
            writer?.close()
            writer = null
            val distance = trajectoryDistance(recordedPoses)
            val trip = Trip(recordingId, recordingName, recordingStartedMs,
                (finishedAtNs - recordingStartedNs) / 1_000_000,
                distance, records, recordedPoses.toList())
            tripStore.save(trip)
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
