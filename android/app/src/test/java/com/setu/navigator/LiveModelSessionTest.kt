package com.setu.navigator

import com.setu.navigator.model.*
import kotlinx.coroutines.*
import kotlinx.coroutines.flow.first
import org.junit.Assert.*
import org.junit.Test
import java.util.concurrent.CopyOnWriteArrayList
import java.util.concurrent.atomic.AtomicLong

class LiveModelSessionTest {
    private val clock = AtomicLong(1_000_000_000L)
    private val records = CopyOnWriteArrayList<ModelInferenceState>()

    private class Provider(
        private val availability: ModelHealth = ModelHealth(true, "Research model", listOf("speed"), "Experimental; validity zero."),
        private val predict: suspend (ModelWindow) -> ModelResult = { window ->
            ModelResult(ModelMeasurement(window.samples.last().timestampNs, 12.0, 2.0, 0.0))
        },
    ) : ModelProvider {
        val requests = CopyOnWriteArrayList<ModelWindow>()
        override suspend fun health() = availability
        override suspend fun infer(window: ModelWindow): ModelResult { requests.add(window); return predict(window) }
    }

    private fun session(provider: ModelProvider) = LiveModelSession(provider, "Car", clock::get, {}, records::add, 5)

    private fun feed(session: LiveModelSession, start: Long = 1_000_000_000L, count: Int = 401) {
        repeat(count) { index ->
            val timestamp = start + index * 10_000_000L
            clock.set(timestamp)
            session.acceleration(timestamp, doubleArrayOf(0.0, 0.0, 9.80665))
            session.gyroscope(timestamp, DoubleArray(3))
        }
        clock.set(start + count * 10_000_000L)
        session.acceleration(clock.get(), doubleArrayOf(0.0, 0.0, 9.80665))
    }

    @Test
    fun realAlignedWindowsReachProviderAndZeroValidityRemainsResearchOnly() = runBlocking {
        val provider = Provider()
        session(provider).use { stream ->
            feed(stream)
            val result = withTimeout(3000) { stream.state.first { it.measurement != null } }
            assertEquals("Research prediction", result.status)
            assertEquals(0.0, result.measurement!!.validity, 0.0)
            assertEquals("Experimental; validity zero.", result.health!!.reason)
            assertEquals(100.0, provider.requests.single().rateHz, 1e-10)
            assertEquals(401, provider.requests.single().samples.size)
            assertNotNull(result.recentMeasurement(clock.get()))
            assertNull(result.recentMeasurement(clock.get() + 3_000_000_000L))
        }
    }

    @Test
    fun unavailableHealthNeverSendsSensorPayloads() = runBlocking {
        val provider = Provider(ModelHealth(false, "Unavailable", emptyList(), "No weights loaded"))
        session(provider).use { stream ->
            feed(stream)
            val result = withTimeout(3000) { stream.state.first { it.status == "Model unavailable" } }
            assertEquals("No weights loaded", result.detail)
            assertTrue(provider.requests.isEmpty())
        }
    }

    @Test
    fun missingCapabilityAndUnavailableMeasurementKeepTheirReasons() = runBlocking {
        val missing = Provider(ModelHealth(true, "Other model", emptyList()))
        session(missing).use { stream ->
            feed(stream)
            withTimeout(3000) { stream.state.first { it.status == "Model unavailable" } }
            assertTrue(missing.requests.isEmpty())
        }
        session(Provider { ModelResult(reason = "Unsupported vehicle") }).use { stream ->
            feed(stream)
            val result = withTimeout(3000) { stream.state.first { it.status == "Model unavailable" } }
            assertEquals("Unsupported vehicle", result.detail)
        }
    }

    @Test
    fun delayedResponsesAreWithheldAndOnlyTheLatestWaitingWindowIsRetained() = runBlocking {
        val entered = CompletableDeferred<Unit>()
        val release = CompletableDeferred<Unit>()
        var calls = 0
        val provider = Provider { window ->
            if (++calls == 1) { entered.complete(Unit); release.await() }
            ModelResult(ModelMeasurement(window.samples.last().timestampNs, 12.0, 2.0, 0.0))
        }
        session(provider).use { stream ->
            feed(stream)
            withTimeout(3000) { entered.await() }
            feed(stream, 5_020_000_000L, 1200)
            release.complete(Unit)
            withTimeout(3000) { stream.state.first { it.measurement != null } }
            assertEquals(2, provider.requests.size)
            assertTrue(records.any { it.status == "Response too old" && it.measurement == null })
            assertTrue(provider.requests.last().samples.last().timestampNs >= 16_000_000_000L)
        }
    }

    @Test
    fun closingCancelsInFlightWorkAndIgnoresLateResults() = runBlocking {
        val entered = CompletableDeferred<Unit>()
        val release = CompletableDeferred<Unit>()
        val exited = CompletableDeferred<Unit>()
        val provider = Provider { window ->
            entered.complete(Unit)
            withContext(NonCancellable) { release.await() }
            exited.complete(Unit)
            ModelResult(ModelMeasurement(window.samples.last().timestampNs, 12.0, 2.0, 0.0))
        }
        val stream = session(provider)
        feed(stream)
        withTimeout(3000) { entered.await() }
        stream.close()
        release.complete(Unit)
        withTimeout(3000) { exited.await() }
        delay(30)
        feed(stream, 6_000_000_000L)
        assertTrue(records.isEmpty())
        assertNull(stream.state.value.measurement)
        assertEquals(1, provider.requests.size)
    }

    @Test
    fun connectionFailuresDoNotEndTheStream() = runBlocking {
        var calls = 0
        val provider = Provider { window ->
            if (++calls == 1) error("Offline")
            ModelResult(ModelMeasurement(window.samples.last().timestampNs, 8.0, 2.0, 0.0))
        }
        session(provider).use { stream ->
            feed(stream)
            withTimeout(3000) { stream.state.first { it.status == "Model connection interrupted" } }
            feed(stream, 5_020_000_000L, 200)
            withTimeout(3000) { stream.state.first { it.measurement != null } }
            assertEquals(2, provider.requests.size)
        }
    }
}
