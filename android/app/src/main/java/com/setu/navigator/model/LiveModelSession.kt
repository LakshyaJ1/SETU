package com.setu.navigator.model

import com.setu.navigator.estimation.ImuSynchronizer
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.channels.Channel
import kotlinx.coroutines.delay
import kotlinx.coroutines.ensureActive
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch

data class ModelInferenceState(
    val status: String = "Sharing off",
    val detail: String = "Sensor windows stay on this phone unless you enable model sharing.",
    val health: ModelHealth? = null,
    val measurement: ModelMeasurement? = null,
    val receivedAtNs: Long = 0L,
    val latencyMs: Long? = null,
) {
    fun recentMeasurement(nowNs: Long): ModelMeasurement? = measurement?.takeIf {
        nowNs >= it.timestampNs && nowNs - it.timestampNs <= 2_000_000_000L
    }
}

class LiveModelSession(
    private val provider: ModelProvider,
    vehicle: String,
    private val clockNs: () -> Long,
    private val publish: (ModelInferenceState) -> Unit,
    private val record: (ModelInferenceState) -> Unit,
    private val retryDelayMs: Long = 5_000,
) : AutoCloseable {
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.Default)
    private val windows = Channel<ModelWindow>(Channel.CONFLATED)
    private val buffer = ModelWindowBuffer(vehicle)
    private val mutableState = MutableStateFlow(ModelInferenceState("Collecting sensor window", "Waiting for four continuous seconds of accelerometer and gyroscope data."))
    val state = mutableState.asStateFlow()
    private val synchronizer = ImuSynchronizer { timestamp, acceleration, angularRate ->
        buffer.append(timestamp, acceleration, angularRate)?.let { windows.trySend(it) }
    }

    init {
        scope.launch {
            var health: ModelHealth? = null
            var failures = 0
            for (window in windows) {
                if (!isActive) break
                val newest = window.samples.last().timestampNs
                if (clockNs() - newest !in 0..500_000_000L) continue
                try {
                    if (health == null) {
                        health = provider.health()
                        ensureActive()
                        if (!health.ready || "speed" !in health.capabilities) {
                            emit(ModelInferenceState("Model unavailable", health.reason ?: "The server does not advertise a ready speed model.", health))
                            health = null
                            delay(retryDelayMs)
                            continue
                        }
                    }
                    if (clockNs() - newest !in 0..500_000_000L) continue
                    val started = clockNs()
                    val result = provider.infer(window)
                    ensureActive()
                    val finished = clockNs()
                    val measurement = result.measurement
                    val snapshot = when {
                        measurement == null -> ModelInferenceState("Model unavailable", result.reason ?: "No measurement for this window.", health)
                        finished < measurement.timestampNs || finished - measurement.timestampNs > 2_000_000_000L ->
                            ModelInferenceState("Response too old", "The delayed result was withheld. Live GPS and sensor capture continue.", health)
                        else -> ModelInferenceState(
                            if (measurement.validity == 0.0) "Research prediction" else "Shadow prediction",
                            if (measurement.validity == 0.0) "Validity is zero. This result is not used for navigation."
                            else "Recorded for evaluation only. Navigation fusion still requires calibrated model validation.",
                            health, measurement,
                        )
                    }.copy(receivedAtNs = finished, latencyMs = ((finished - started) / 1_000_000).coerceAtLeast(0))
                    emit(snapshot)
                    record(snapshot)
                    failures = 0
                } catch (cancelled: CancellationException) {
                    throw cancelled
                } catch (error: Exception) {
                    ensureActive()
                    health = null
                    failures = (failures + 1).coerceAtMost(6)
                    emit(ModelInferenceState("Model connection interrupted", "${error.message ?: "Request failed."} Retrying; GPS and local recording continue."))
                    delay(retryDelayMs * failures)
                }
            }
        }
    }

    private fun emit(value: ModelInferenceState) {
        mutableState.value = value
        publish(value)
    }

    @Synchronized
    fun acceleration(timestampNs: Long, values: DoubleArray) {
        if (scope.isActive) synchronizer.acceleration(timestampNs, values)
    }

    @Synchronized
    fun gyroscope(timestampNs: Long, values: DoubleArray) {
        if (scope.isActive) synchronizer.gyroscope(timestampNs, values)
    }

    override fun close() {
        windows.cancel()
        scope.cancel()
    }
}
