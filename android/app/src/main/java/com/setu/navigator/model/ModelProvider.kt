package com.setu.navigator.model

import com.setu.navigator.BuildConfig
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import org.json.JSONArray
import org.json.JSONObject
import java.net.HttpURLConnection
import java.net.URI

data class ImuSample(val timestampNs: Long, val accelerationMps2: List<Double>, val angularRateRps: List<Double>)
data class ModelWindow(val samples: List<ImuSample>, val rateHz: Double, val vehicle: String)
data class ModelMeasurement(val timestampNs: Long, val speedMps: Double, val sigmaMps: Double, val validity: Double)
data class ModelHealth(val ready: Boolean, val name: String, val capabilities: List<String>)

interface ModelProvider {
    suspend fun health(): ModelHealth
    suspend fun infer(window: ModelWindow): ModelMeasurement?
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
        return ModelHealth(response.optString("status") == "ready", response.optString("model", "Unnamed model"),
            (0 until capabilities.length()).map { capabilities.getString(it) })
    }

    override suspend fun infer(window: ModelWindow): ModelMeasurement? {
        require(window.samples.isNotEmpty() && window.samples.size <= 2048)
        require(window.rateHz.isFinite() && window.rateHz > 0)
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
        if (response.optString("status") == "unavailable") return null
        val measurement = ModelMeasurement(response.getLong("tNs"), response.getDouble("speedMps"),
            response.getDouble("sigmaMps"), response.getDouble("validity"))
        require(measurement.speedMps.isFinite() && measurement.speedMps in 0.0..100.0)
        require(measurement.sigmaMps.isFinite() && measurement.sigmaMps > 0.0)
        require(measurement.validity.isFinite() && measurement.validity in 0.0..1.0)
        require(measurement.timestampNs in window.samples.first().timestampNs..window.samples.last().timestampNs)
        return measurement
    }

    private suspend fun request(path: String, payload: JSONObject? = null): JSONObject = withContext(Dispatchers.IO) {
        val connection = URI(base + path).toURL().openConnection() as HttpURLConnection
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
            JSONObject(response.toString(Charsets.UTF_8))
        } finally {
            connection.disconnect()
        }
    }
}
