package com.setu.navigator.data

import android.content.Context
import android.os.SystemClock
import com.setu.navigator.estimation.navigationPose
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
        storageScope.launch {
            mapPacks.restore()
            val count = tripStore.recoverIncomplete { recordingId }
            refreshTrips()
            if (count > 0) mutableError.value = "Recovered $count interrupted recording(s). Find them in Trips."
        }
    }

    fun updateSettings(updated: AppSettings) {
        preferences.edit().putString("theme", updated.theme).putString("units", updated.units)
            .putString("vehicle", updated.vehicle).putBoolean("keepScreenOn", updated.keepScreenOn)
            .putString("modelEndpoint", updated.modelEndpoint)
            .putBoolean("modelSharingAllowed", updated.modelSharingAllowed).apply()
        preferences.edit().putBoolean("nativePositioning", updated.nativePositioning).apply()
        mutableSettings.value = updated
    }

    private fun readSettings() = AppSettings(
        preferences.getString("theme", "System") ?: "System",
        preferences.getString("units", "km/h") ?: "km/h",
        preferences.getString("vehicle", "Car") ?: "Car",
        preferences.getBoolean("keepScreenOn", true),
        preferences.getString("modelEndpoint", "") ?: "",
        preferences.getBoolean("modelSharingAllowed", false),
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
        hub.start()
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
        }
    }

    fun refreshTrips() { mutableTrips.value = tripStore.all() }
    fun clearError() { mutableError.value = null }
    fun reportError(message: String) { mutableError.value = message }
}
