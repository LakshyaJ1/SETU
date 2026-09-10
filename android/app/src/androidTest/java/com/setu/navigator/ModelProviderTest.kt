package com.setu.navigator

import com.setu.navigator.model.*
import kotlinx.coroutines.*
import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test
import java.io.ByteArrayOutputStream
import java.net.InetAddress
import java.net.ServerSocket
import java.util.concurrent.CopyOnWriteArrayList
import kotlin.concurrent.thread

class ModelProviderTest {
    private val window = ModelWindow(listOf(ImuSample(1_000_000_000, listOf(0.0, 0.0, 9.80665), listOf(0.0, 0.0, 0.0))), 200.0, "Car")
    private val prediction = """{"schema":"setu.model.v1","tNs":1000000000,"speedMps":12.0,"sigmaMps":2.0,"validity":0.0}"""

    @Test
    fun healthPreservesExperimentalWarningAndInferenceContainsNoLocation() = runBlocking {
        serve(listOf("""{"schema":"setu.model.v1","status":"ready","model":"Research","capabilities":["speed"],"reason":"Validity zero; not navigation."}""", prediction)) { endpoint, requests ->
            val provider = HttpModelProvider(endpoint)
            val health = provider.health()
            assertTrue(health.ready)
            assertEquals("Validity zero; not navigation.", health.reason)
            val result = checkNotNull(provider.infer(window).measurement)
            assertEquals(0.0, result.validity, 0.0)
            assertTrue(requests.first().first.startsWith("GET /v1/health "))
            assertNull(requests.first().second)
            val body = checkNotNull(requests.last().second)
            assertEquals(setOf("schema", "vehicle", "rateHz", "samples"), body.keys().asSequence().toSet())
            val sample = body.getJSONArray("samples").getJSONObject(0)
            assertEquals(setOf("tNs", "accelerationMps2", "angularRateRps"), sample.keys().asSequence().toSet())
            assertEquals(9.80665, sample.getJSONArray("accelerationMps2").getDouble(2), 1e-10)
        }
    }

    @Test
    fun unavailableRetainsReasonRatherThanPretendingTheVehicleStopped() = runBlocking {
        serve(listOf("""{"schema":"setu.model.v1","status":"unavailable","reason":"Unsupported vehicle"}""")) { endpoint, _ ->
            val result = HttpModelProvider(endpoint).infer(window)
            assertNull(result.measurement)
            assertEquals("Unsupported vehicle", result.reason)
        }
    }

    @Test
    fun malformedAndOutOfWindowMeasurementsAreRejected() = runBlocking {
        val responses = listOf(
            prediction.replace("setu.model.v1", "wrong"),
            prediction.replace("1000000000", "999999999"),
            prediction.replace("1000000000", "1000000000.5"),
            prediction.replace("\"speedMps\":12.0", "\"speedMps\":\"12.0\""),
            prediction.replace("\"speedMps\":12.0", "\"speedMps\":-1"),
            prediction.replace("\"speedMps\":12.0", "\"speedMps\":101"),
            prediction.replace("\"sigmaMps\":2.0", "\"sigmaMps\":0"),
            prediction.replace("\"validity\":0.0", "\"validity\":1.1"),
            prediction.replace("\"validity\":0.0", "\"validity\":-0.1"),
        )
        serve(responses) { endpoint, _ ->
            val provider = HttpModelProvider(endpoint)
            responses.forEach { assertTrue(runCatching { provider.infer(window) }.isFailure) }
        }
    }

    @Test
    fun redirectsOversizedResponsesAndUnknownHealthAreRejected() = runBlocking {
        serve(listOf("{}"), "302 Found", "Location: https://example.invalid/\r\n") { endpoint, _ ->
            assertTrue(runCatching { HttpModelProvider(endpoint).health() }.exceptionOrNull()?.message.orEmpty().contains("302"))
        }
        serve(listOf(" ".repeat(65537))) { endpoint, _ ->
            assertTrue(runCatching { HttpModelProvider(endpoint).health() }.exceptionOrNull()?.message.orEmpty().contains("size limit"))
        }
        serve(listOf("""{"schema":"setu.model.v1","status":"mystery"}""")) { endpoint, _ ->
            assertTrue(runCatching { HttpModelProvider(endpoint).health() }.isFailure)
        }
    }

    @Test
    fun urlAndWindowValidationHappenBeforeNetworkTraffic() = runBlocking {
        listOf("http://example.com", "https://user:password@example.com", "https://example.com?token=secret", "https://example.com#fragment").forEach {
            assertTrue(runCatching { HttpModelProvider(it) }.isFailure)
        }
        val provider = HttpModelProvider("https://example.invalid")
        listOf(
            window.copy(samples = emptyList()),
            window.copy(rateHz = Double.NaN),
            window.copy(vehicle = ""),
            window.copy(samples = window.samples + window.samples),
            window.copy(samples = listOf(window.samples.first().copy(timestampNs = -1))),
            window.copy(samples = listOf(window.samples.first().copy(accelerationMps2 = listOf(Double.NaN, 0.0, 0.0)))),
        ).forEach { assertTrue(runCatching { provider.infer(it) }.exceptionOrNull() is IllegalArgumentException) }
    }

    @Test
    fun cancellingADownloadDoesNotWaitForTheReadTimeout() = runBlocking {
        ServerSocket(0, 1, InetAddress.getByName("127.0.0.1")).use { server ->
            val accepted = CompletableDeferred<Unit>()
            val worker = thread(isDaemon = true) {
                runCatching { server.accept().use { socket ->
                    socket.soTimeout = 2000
                    accepted.complete(Unit)
                    val input = socket.getInputStream()
                    while (input.read() >= 0) { }
                } }
            }
            val request = launch { HttpModelProvider("http://127.0.0.1:${server.localPort}").health() }
            withTimeout(3000) { accepted.await() }
            withTimeout(2000) { request.cancelAndJoin() }
            worker.join(2500)
            assertFalse(worker.isAlive)
        }
    }

    private suspend fun serve(
        responses: List<String>, status: String = "200 OK", extra: String = "",
        block: suspend (String, List<Pair<String, JSONObject?>>) -> Unit,
    ) {
        ServerSocket(0, responses.size, InetAddress.getByName("127.0.0.1")).use { server ->
            server.soTimeout = 5000
            val requests = CopyOnWriteArrayList<Pair<String, JSONObject?>>()
            val failures = CopyOnWriteArrayList<Throwable>()
            val worker = thread(isDaemon = true) {
                runCatching {
                    responses.forEach { response -> server.accept().use { socket ->
                        socket.soTimeout = 3000
                        val input = socket.getInputStream().buffered()
                        val header = ByteArrayOutputStream()
                        var tail = ""
                        while (!tail.endsWith("\r\n\r\n")) {
                            val value = input.read()
                            check(value >= 0 && header.size() < 8192)
                            header.write(value)
                            tail = (tail + value.toChar()).takeLast(4)
                        }
                        val lines = header.toString("UTF-8").split("\r\n")
                        val length = lines.firstOrNull { it.startsWith("Content-Length:", true) }?.substringAfter(':')?.trim()?.toInt() ?: 0
                        val bytes = ByteArray(length)
                        var offset = 0
                        while (offset < length) { val read = input.read(bytes, offset, length - offset); check(read > 0); offset += read }
                        requests.add(lines.first() to if (length > 0) JSONObject(bytes.toString(Charsets.UTF_8)) else null)
                        val body = response.toByteArray()
                        socket.getOutputStream().apply {
                            write("HTTP/1.1 $status\r\nContent-Type: application/json\r\nContent-Length: ${body.size}\r\n${extra}Connection: close\r\n\r\n".toByteArray())
                            write(body)
                            flush()
                        }
                    } }
                }.exceptionOrNull()?.let(failures::add)
            }
            block("http://127.0.0.1:${server.localPort}", requests)
            worker.join(6000)
            assertFalse("Fixture server did not finish", worker.isAlive)
            assertTrue("Fixture failure: $failures", failures.isEmpty())
        }
    }
}
