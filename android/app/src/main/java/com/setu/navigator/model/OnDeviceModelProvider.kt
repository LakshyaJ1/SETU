package com.setu.navigator.model

import android.content.Context
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import kotlinx.coroutines.withContext
import org.json.JSONObject
import org.tensorflow.lite.Interpreter
import java.io.Closeable
import java.nio.ByteBuffer
import java.nio.ByteOrder
import java.nio.channels.FileChannel
import java.security.MessageDigest
import kotlin.math.abs
import kotlin.math.exp
import kotlin.math.max
import kotlin.math.min

/**
 * Speed inference on the phone.
 *
 * REQ-F9 asks for inference on the device, and the product premise requires it: a tunnel has no
 * connectivity, so an HTTPS endpoint cannot be the path that carries a GNSS blackout. This loads
 * the bundled int8 model and runs it locally, behind the same [ModelProvider] interface the remote
 * one uses, so nothing above this layer has to know which is in play.
 *
 * The window arrives at whatever rate the phone achieved and is resampled **by timestamp** onto the
 * model's canonical grid. That is not a detail: the same motion sampled at 200 Hz and at 50 Hz has
 * to produce the same tensor, or the model is reading sample indices rather than time.
 */
class OnDeviceModelProvider(context: Context, private val assetDirectory: String = BUNDLE) : ModelProvider, Closeable {

    private class Bundle(
        val interpreter: Interpreter,
        val windowSamples: Int,
        val canonicalRateHz: Double,
        val sigmaScale: Double,
        val version: String,
        val coverage3Sigma: Double,
        val gateG4Pass: Boolean,
        val vehicles: Set<String>,
    )

    private val application = context.applicationContext
    private val mutex = Mutex()
    private var bundle: Bundle? = null
    private var failure: String? = null
    private var input: ByteBuffer? = null
    private var output: Array<FloatArray>? = null

    private fun load(): Bundle? {
        bundle?.let { return it }
        failure?.let { return null }
        try {
            val manifest = JSONObject(read("$assetDirectory/manifest.json").toString(Charsets.UTF_8))
            require(manifest.getString("schema") == "setu.model-bundle.v1") { "unsupported bundle schema" }

            // docs/05 §5.2: the runtime refuses to load on an input-spec mismatch rather than
            // silently producing a wrong speed. The hash covers channel order, units, window length
            // and the canonical rate, so a trainer/runtime disagreement fails loudly at startup.
            val spec = manifest.getJSONObject("input_spec")
            val declared = manifest.getString("input_spec_sha256")
            val actual = MessageDigest.getInstance("SHA-256")
                .digest(canonicalModelSpec(spec).toByteArray(Charsets.UTF_8))
                .joinToString("") { "%02x".format(it) }
            require(actual == declared) {
                "input spec hash mismatch: bundle declares $declared, computed $actual"
            }
            require(spec.getJSONArray("channels").length() == CHANNELS) { "expected $CHANNELS channels" }
            require(spec.getString("frame") == "phone_body") { "model expects phone-body samples" }

            val windowSamples = spec.getInt("window_samples")
            val rate = spec.getDouble("canonical_rate_hz")
            require(windowSamples in 1..4096 && rate > 0) { "implausible window spec" }

            val model = readMapped("$assetDirectory/speed_int8.tflite")
            val interpreter = Interpreter(model, Interpreter.Options().apply { numThreads = 2 })
            interpreter.resizeInput(0, intArrayOf(1, windowSamples, CHANNELS))
            interpreter.allocateTensors()

            val calibration = JSONObject(read("$assetDirectory/calibration.json").toString(Charsets.UTF_8))
            val vehicles = mutableSetOf<String>()
            manifest.optJSONArray("vehicles")?.let { for (i in 0 until it.length()) vehicles.add(it.getString(i)) }

            input = ByteBuffer.allocateDirect(windowSamples * CHANNELS * 4).order(ByteOrder.nativeOrder())
            output = Array(1) { FloatArray(2) }
            return Bundle(
                interpreter = interpreter,
                windowSamples = windowSamples,
                canonicalRateHz = rate,
                sigmaScale = calibration.optDouble("sigma_scale", 1.0).takeIf { it.isFinite() && it > 0 } ?: 1.0,
                version = manifest.optString("version", "unknown"),
                coverage3Sigma = calibration.optJSONObject("test_coverage")?.optDouble("3_sigma", 0.0) ?: 0.0,
                gateG4Pass = calibration.optBoolean("gate_g4_pass", false),
                vehicles = if (vehicles.isEmpty()) setOf("Car") else vehicles,
            ).also { bundle = it }
        } catch (error: Throwable) {
            failure = error.message ?: error::class.java.simpleName
            return null
        }
    }

    override suspend fun health(): ModelHealth = withContext(Dispatchers.Default) {
        mutex.withLock {
            val loaded = load()
                ?: return@withLock ModelHealth(false, "On-device speed model", emptyList(),
                    "The bundled model could not be loaded: ${failure ?: "unknown reason"}.")
            ModelHealth(
                ready = true,
                name = "On-device speed ${loaded.version}",
                capabilities = listOf("speed"),
                reason = "Runs on this phone; no network. Trained on real drives, and its own " +
                    "calibration reports ${"%.1f".format(loaded.coverage3Sigma * 100)} % three-sigma " +
                    "coverage against a 98 % bar, so speed is fused with a wide uncertainty and " +
                    "never drives navigation on its own.",
            )
        }
    }

    override suspend fun infer(window: ModelWindow): ModelResult = withContext(Dispatchers.Default) {
        mutex.withLock {
            val loaded = load()
                ?: return@withLock ModelResult(reason = "Model unavailable: ${failure ?: "unknown reason"}.")
            if (window.vehicle !in loaded.vehicles) {
                return@withLock ModelResult(reason = "This model covers ${loaded.vehicles.joinToString()} only.")
            }
            val samples = window.samples
            if (samples.size < 2) return@withLock ModelResult(reason = "Not enough samples.")

            val firstNs = samples.first().timestampNs
            val lastNs = samples.last().timestampNs
            val spanSeconds = (lastNs - firstNs) / 1e9
            val neededSeconds = (loaded.windowSamples - 1) / loaded.canonicalRateHz
            if (spanSeconds < neededSeconds - 0.1) {
                return@withLock ModelResult(reason = "Needs ${"%.1f".format(neededSeconds)} s of continuous motion history.")
            }
            var largestGapNs = 0L
            for (index in 1 until samples.size) {
                largestGapNs = max(largestGapNs, samples[index].timestampNs - samples[index - 1].timestampNs)
            }
            val measuredRate = (samples.size - 1) / spanSeconds
            var saturated = false

            // Resample by timestamp onto the canonical grid, ending at the newest sample.
            val buffer = input ?: return@withLock ModelResult(reason = "Model buffers unavailable.")
            buffer.rewind()
            var cursor = 0
            for (step in 0 until loaded.windowSamples) {
                val offset = (loaded.windowSamples - 1 - step) / loaded.canonicalRateHz
                val target = lastNs - (offset * 1e9).toLong()
                while (cursor + 2 < samples.size && samples[cursor + 1].timestampNs < target) cursor++
                val before = samples[cursor]
                val after = samples[min(cursor + 1, samples.size - 1)]
                val gap = (after.timestampNs - before.timestampNs).toDouble()
                val fraction = if (gap > 0) ((target - before.timestampNs) / gap).coerceIn(0.0, 1.0) else 0.0
                for (channel in 0 until CHANNELS) {
                    val low = channelValue(before, channel)
                    val high = channelValue(after, channel)
                    val value = low + fraction * (high - low)
                    if (channel < 3 && abs(value) > ACCEL_SATURATION) saturated = true
                    if (channel >= 3 && abs(value) > GYRO_SATURATION) saturated = true
                    buffer.putFloat(value.toFloat())
                }
            }
            buffer.rewind()

            val result = output ?: return@withLock ModelResult(reason = "Model buffers unavailable.")
            try {
                loaded.interpreter.run(buffer, result)
            } catch (error: Throwable) {
                return@withLock ModelResult(reason = "Inference failed: ${error.message ?: "unknown"}.")
            }
            val speed = result[0][0].toDouble()
            val logVariance = result[0][1].toDouble().coerceIn(-6.0, 6.0)
            if (!speed.isFinite() || !logVariance.isFinite()) {
                return@withLock ModelResult(reason = "Model produced a non-finite value.")
            }
            val sigma = max(exp(0.5 * logVariance) * loaded.sigmaScale, 1e-3)

            // Validity is zero unless every gate passes; it is not a confidence score on its own.
            // A model whose own calibration misses the coverage bar never reaches full validity,
            // which is what keeps a 2.9 m/s mean error from being trusted like a wheel sensor.
            val reasons = mutableListOf<String>()
            if (measuredRate < MINIMUM_RATE_HZ || measuredRate > MAXIMUM_RATE_HZ) reasons += "sample rate outside the supported range"
            if (largestGapNs > MAXIMUM_GAP_NS) reasons += "a gap in the motion history"
            if (saturated) reasons += "sensor saturation"
            if (sigma > MAXIMUM_SIGMA_MPS) reasons += "uncertainty above the usable bound"
            if (speed < 0 || speed > MAXIMUM_SPEED_MPS) reasons += "speed outside the plausible range"
            val ceiling = if (loaded.gateG4Pass) 1.0 else UNCALIBRATED_VALIDITY_CEILING
            val validity = if (reasons.isNotEmpty()) 0.0
            else min(ceiling, max(0.0, 1.0 - sigma / MAXIMUM_SIGMA_MPS))

            ModelResult(
                measurement = ModelMeasurement(lastNs, max(0.0, speed), sigma, validity),
                reason = reasons.takeIf { it.isNotEmpty() }?.joinToString(", "),
            )
        }
    }

    override fun close() {
        bundle?.interpreter?.close()
        bundle = null
    }

    private fun channelValue(sample: ImuSample, channel: Int): Double =
        if (channel < 3) sample.accelerationMps2[channel] else sample.angularRateRps[channel - 3]

    private fun read(path: String): ByteArray = application.assets.open(path).use { it.readBytes() }

    private fun readMapped(path: String): ByteBuffer = application.assets.openFd(path).use { descriptor ->
        descriptor.createInputStream().use { stream ->
            stream.channel.map(FileChannel.MapMode.READ_ONLY, descriptor.startOffset, descriptor.declaredLength)
        }
    }

    private companion object {
        const val BUNDLE = "models/setu-speed-v1"
        const val CHANNELS = 6
        const val MINIMUM_RATE_HZ = 25.0
        const val MAXIMUM_RATE_HZ = 500.0
        const val MAXIMUM_GAP_NS = 50_000_000L
        const val MAXIMUM_SIGMA_MPS = 6.0
        const val MAXIMUM_SPEED_MPS = 60.0
        const val ACCEL_SATURATION = 78.0
        const val GYRO_SATURATION = 16.0

        /**
         * A model whose reported three-sigma coverage misses the 98 % gate is useful but not
         * trustworthy enough to be treated as a full-confidence measurement, so its validity is
         * capped. Raise this only when the bundle's own calibration says the gate passes.
         */
        const val UNCALIBRATED_VALIDITY_CEILING = 0.5
    }
}


/**
 * Reproduces `json.dumps(spec, sort_keys=True)` byte for byte.
 *
 * The trainer hashed the input spec that way (`notebooks/kaggle_train.py`), so the separators are
 * part of the contract: Python defaults to ", " between items and ": " after a key. Getting either
 * wrong makes the hash disagree and the model refuse to load — the correct failure, but an annoying
 * one to diagnose, so `OnDeviceModelSpecTest` pins it against the manifest actually shipped.
 *
 * Top-level rather than a private method so the test can exercise the shipping code instead of a
 * copy of it.
 */
internal fun canonicalModelSpec(value: Any?): String = when (value) {
    is JSONObject -> value.keys().asSequence().sorted()
        .joinToString(", ", "{", "}") { key -> "${quoteModelJson(key)}: ${canonicalModelSpec(value.get(key))}" }
    is org.json.JSONArray -> (0 until value.length())
        .joinToString(", ", "[", "]") { index -> canonicalModelSpec(value.get(index)) }
    is String -> quoteModelJson(value)
    is Boolean -> if (value) "true" else "false"
    is Number -> value.toString()
    else -> "null"
}

internal fun quoteModelJson(text: String): String = buildString {
    append('"')
    for (character in text) when (character) {
        '"' -> { append('\\'); append('"') }
        '\\' -> { append('\\'); append('\\') }
        '\n' -> { append('\\'); append('n') }
        else -> append(character)
    }
    append('"')
}
