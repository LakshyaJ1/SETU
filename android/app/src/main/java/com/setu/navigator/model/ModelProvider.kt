package com.setu.navigator.model

import com.setu.navigator.BuildConfig
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.coroutineScope
import kotlinx.coroutines.launch
import kotlinx.coroutines.suspendCancellableCoroutine
import org.json.JSONArray
import org.json.JSONObject
import java.net.HttpURLConnection
import java.net.URI
import kotlin.coroutines.resume
import kotlin.coroutines.resumeWithException

data class ImuSample(val timestampNs: Long, val accelerationMps2: List<Double>, val angularRateRps: List<Double>)
data class ModelWindow(val samples: List<ImuSample>, val rateHz: Double, val vehicle: String)
data class ModelMeasurement(val timestampNs: Long, val speedMps: Double, val sigmaMps: Double, val validity: Double)
data class ModelHealth(val ready: Boolean, val name: String, val capabilities: List<String>, val reason: String? = null)
data class ModelResult(val measurement: ModelMeasurement? = null, val reason: String? = null)

interface ModelProvider {
    suspend fun health(): ModelHealth
    suspend fun infer(window: ModelWindow): ModelResult
}

class HttpModelProvider(endpoint: String) : ModelProvider {
    private val base = endpoint.trim().trimEnd('/')
    init {
        val uri = URI(base)
        val localDebug = BuildConfig.DEBUG && uri.host in setOf("localhost", "127.0.0.1", "10.0.2.2")
        require(uri.scheme == "https" || uri.scheme == "http" && localDebug) {
            "Use HTTPS. Debug builds also allow localhost or 10.0.2.2 over HTTP."
        }
        require(!uri.host.isNullOrBlank() && uri.userInfo == null && uri.query == null && uri.fragment == null) {
            "Enter a server URL without credentials, query or fragment."
        }
    }

    override suspend fun health(): ModelHealth {
        val response = request("/v1/health")
        require(response.optString("schema") == "setu.model.v1") { "The server uses an incompatible model protocol." }
        val capabilities = response.optJSONArray("capabilities") ?: JSONArray()
        require(response.optString("status") in setOf("ready", "unavailable")) { "Unknown model availability status." }
        return ModelHealth(response.optString("status") == "ready", response.optString("model", "Unnamed model"),
            (0 until capabilities.length()).map { capabilities.getString(it) },
            response.optString("reason").takeIf { it.isNotBlank() })
    }

    override suspend fun infer(window: ModelWindow): ModelResult {
        require(window.samples.isNotEmpty() && window.samples.size <= 2048)
        require(window.rateHz.isFinite() && window.rateHz > 0)
        require(window.vehicle.isNotBlank() && window.vehicle.length <= 64)
        require(window.samples.first().timestampNs > 0)
        require(window.samples.zipWithNext().all { (previous, current) -> current.timestampNs > previous.timestampNs })
        val payload = JSONObject().put("schema", "setu.model.v1").put("rateHz", window.rateHz)
            .put("vehicle", window.vehicle).put("samples", JSONArray().apply {
                window.samples.forEach { sample ->
                    require(sample.accelerationMps2.size == 3 && sample.angularRateRps.size == 3)
                    require((sample.accelerationMps2 + sample.angularRateRps).all(Double::isFinite))
                    put(JSONObject().put("tNs", sample.timestampNs).put("accelerationMps2", JSONArray(sample.accelerationMps2))
                        .put("angularRateRps", JSONArray(sample.angularRateRps)))
                }
            })
        val response = request("/v1/measurements", payload)
        require(response.optString("schema") == "setu.model.v1") { "Incompatible model response." }
        if (response.optString("status") == "unavailable") return ModelResult(reason = response.optString("reason", "No measurement available."))
        require(!response.has("status")) { "Unknown model measurement status." }
        require(response.get("tNs") is Long || response.get("tNs") is Int) { "Model timestamps must be integer nanoseconds." }
        listOf("speedMps", "sigmaMps", "validity").forEach { field ->
            require(response.get(field) is Number) { "Model $field must be a number." }
        }
        val measurement = ModelMeasurement(response.getLong("tNs"), response.getDouble("speedMps"),
            response.getDouble("sigmaMps"), response.getDouble("validity"))
        require(measurement.speedMps.isFinite() && measurement.speedMps in 0.0..100.0)
        require(measurement.sigmaMps.isFinite() && measurement.sigmaMps > 0.0)
        require(measurement.validity.isFinite() && measurement.validity in 0.0..1.0)
        require(measurement.timestampNs in window.samples.first().timestampNs..window.samples.last().timestampNs)
        return ModelResult(measurement)
    }

    private suspend fun request(path: String, payload: JSONObject? = null): JSONObject = coroutineScope {
      suspendCancellableCoroutine { continuation ->
        val connection = URI(base + path).toURL().openConnection() as HttpURLConnection
        continuation.invokeOnCancellation { connection.disconnect() }
        launch(Dispatchers.IO) {
        try {
            connection.connectTimeout = 5000
            connection.readTimeout = 5000
            connection.instanceFollowRedirects = false
            connection.setRequestProperty("Accept", "application/json")
            if (payload != null) {
                connection.requestMethod = "POST"
                connection.doOutput = true
                connection.setRequestProperty("Content-Type", "application/json")
                connection.outputStream.use { it.write(payload.toString().toByteArray(Charsets.UTF_8)) }
            }
            require(connection.responseCode in 200..299) { "Model server returned HTTP ${connection.responseCode}." }
            val response = connection.inputStream.use { input ->
                val output = java.io.ByteArrayOutputStream()
                val buffer = ByteArray(4096)
                while (true) {
                    val count = input.read(buffer)
                    if (count < 0) break
                    require(output.size() + count <= 65536) { "Model response exceeds the size limit." }
                    output.write(buffer, 0, count)
                }
                output.toByteArray()
            }
            if (continuation.isActive) continuation.resume(JSONObject(response.toString(Charsets.UTF_8)))
        } catch (error: Exception) {
            if (continuation.isActive) continuation.resumeWithException(error)
        } finally {
            connection.disconnect()
        }
        }
      }
    }
}
