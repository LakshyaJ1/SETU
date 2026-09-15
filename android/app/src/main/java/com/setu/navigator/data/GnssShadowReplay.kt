package com.setu.navigator.data

import android.content.Context
import android.hardware.Sensor
import com.setu.navigator.estimation.LiveEstimator
import org.json.JSONObject

class GnssShadowReplay(
    private val context: Context,
    private val warmupSeconds: Int = DEFAULT_WARMUP_SECONDS,
    private val outageSeconds: Int = 30,
    private val outputIntervalMs: Int = 1000,
) : CollectionReplay {
    init {
        require(warmupSeconds in 1..600 && outageSeconds in 1..600)
        require(outputIntervalMs in 100..1000)
    }

    override val protocolDescription = "Independent native replay: reset each ${warmupSeconds + outageSeconds} s, " +
        "GNSS aid first $warmupSeconds s, withhold next $outageSeconds s; " +
        "output interval $outputIntervalMs ms; no learned speed input"
    private var estimator: LiveEstimator? = null
    private var cycleStart = -1L
    private var lastSensor = 0L
    private var lastOutput = 0L
    private var result: JSONObject? = null
    private var walkingStepMeters: Double? = null
    private var vehicle = "Car"
    private val types = mapOf("accelerometer" to Sensor.TYPE_ACCELEROMETER,
        "gyroscope" to Sensor.TYPE_GYROSCOPE, "magnetometer" to Sensor.TYPE_MAGNETIC_FIELD,
        "rotation_vector" to Sensor.TYPE_ROTATION_VECTOR, "game_rotation_vector" to Sensor.TYPE_GAME_ROTATION_VECTOR,
        "step_detector" to Sensor.TYPE_STEP_DETECTOR)

    override fun accept(record: JSONObject): JSONObject? {
        result = null
        if (record.optString("schema") == "setu.log.v1") {
            val metadata = record.optJSONObject("collection")
            vehicle = metadata?.optString("vehicle", "Car") ?: "Car"
            if (metadata?.optString("vehicle") == "Walking") {
                val length = metadata.optDouble("walkingStepLengthMeters", 0.70)
                require(length.isFinite() && length in 0.3..1.2)
                walkingStepMeters = length
            }
            return null
        }
        val timestamp = record.getLong("tNs")
        val type = record.optString("type")
        types[type]?.let { sensorType ->
            lastSensor = maxOf(lastSensor, timestamp)
            val cycleNs = (warmupSeconds + outageSeconds) * 1_000_000_000L
            if (cycleStart < 0 || timestamp - cycleStart >= cycleNs) {
                estimator?.close()
                cycleStart = if (cycleStart < 0) timestamp else cycleStart +
                    ((timestamp - cycleStart) / cycleNs) * cycleNs
                estimator = LiveEstimator(context, { estimate ->
                    if (lastSensor - lastOutput >= outputIntervalMs * 1_000_000L) {
                        lastOutput = lastSensor
                        result = JSONObject().put("tNs", lastSensor).put("cycleStartNs", cycleStart)
                            .put("gpsCutoffNs", cycleStart + warmupSeconds * 1_000_000_000L)
                            .put("phase", if (lastSensor - cycleStart < warmupSeconds * 1_000_000_000L) "gps_aided_warmup" else "gps_withheld")
                            .put("status", estimate.status).put("hasEstimate", estimate.pose != null)
                            .put("detail", estimate.detail)
                            .put("pose", estimate.pose?.let(TripStore::encodePose) ?: JSONObject.NULL)
                            .put("acceptedGps", estimate.accepted).put("resets", estimate.resets)
                            .put("pairedSamples", estimate.pairedSamples).put("pairingDrops", estimate.pairingDrops)
                            .put("headingSource", estimate.headingSource ?: JSONObject.NULL)
                            .put("radius95Meters", estimate.radius95Meters ?: JSONObject.NULL)
                    }
                }, {}, { Long.MAX_VALUE }, walkingStepMeters = walkingStepMeters, vehicle = vehicle)
            }
            val values = record.getJSONArray("values")
            estimator?.sensor(sensorType, timestamp, FloatArray(values.length()) { values.getDouble(it).toFloat() }, record.optInt("accuracy"))
        }
        if (type == "gnss_reference" && cycleStart >= 0 &&
            acceptsReference(cycleStart, lastSensor, timestamp, record.optLong("receivedAtNs", lastSensor), warmupSeconds) &&
            TrainingArchive.referenceIssues(record).isEmpty()) {
            estimator?.gnss(TripStore.decodePose(record), record.getLong("wallTimeMs"))
        }
        return result
    }

    override fun close() { estimator?.close(); estimator = null }

    companion object {
        const val DEFAULT_WARMUP_SECONDS = 120
        fun acceptsReference(cycleStart: Long, sensorTime: Long, timestamp: Long, receivedAt: Long,
                             warmupSeconds: Int = DEFAULT_WARMUP_SECONDS): Boolean {
            require(warmupSeconds in 1..600)
            val cutoff = cycleStart + warmupSeconds * 1_000_000_000L
            return timestamp in cycleStart until cutoff && sensorTime < cutoff && receivedAt in timestamp until cutoff
        }
    }
}
