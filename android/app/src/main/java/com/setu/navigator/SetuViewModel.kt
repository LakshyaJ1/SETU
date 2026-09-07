package com.setu.navigator

import android.app.Application
import android.content.Intent
import android.net.Uri
import android.os.SystemClock
import androidx.compose.runtime.*
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import com.setu.navigator.data.*
import com.setu.navigator.model.HttpModelProvider
import com.setu.navigator.estimation.NativeCoreStatus
import com.setu.navigator.estimation.checkNativeCore
import com.setu.navigator.estimation.navigationPose
import com.setu.navigator.estimation.PositioningDemo
import com.setu.navigator.estimation.buildPositioningDemo
import kotlinx.coroutines.*
import kotlinx.coroutines.flow.MutableSharedFlow
import kotlinx.coroutines.flow.drop
import kotlinx.coroutines.flow.collectLatest
import kotlin.math.ceil

class SetuViewModel(application: Application) : AndroidViewModel(application) {
    val repository = (application as SetuApplication).repository
    val settings = repository.settings
    val trips = repository.trips
    val activeMap = repository.mapPacks.activeMap
    val regions = repository.mapPacks.regions
    var mapBusy by mutableStateOf(false)
        private set
    var mapMessage by mutableStateOf<String?>(null)
        private set
    var mapProgress by mutableStateOf<String?>(null)
        private set
    private var mapJob: Job? = null
    private var routeJob: Job? = null
    private var routeVersion = 0L
    val sensors = repository.hub.sensors
    val livePose = repository.hub.pose
    val nativeEstimate = repository.hub.nativeEstimate
    fun navigationFix(nowNs: Long = SystemClock.elapsedRealtimeNanos()) =
        navigationPose(livePose.value, nativeEstimate.value, settings.value.nativePositioning, nowNs)
    val recording = repository.recording
    val recordCount = repository.recordCount
    val messages = MutableSharedFlow<String>(extraBufferCapacity = 4)
    var tab by mutableStateOf("Drive")
    var overlay by mutableStateOf<String?>(null)
    var destination by mutableStateOf<Place?>(null)
        private set
    var route by mutableStateOf<DriveRoute?>(null)
        private set
    var routeOriginLabel by mutableStateOf("MG Road preview")
        private set
    var routeLoading by mutableStateOf(false)
        private set
    var navigating by mutableStateOf(false)
        private set
    var selectedTrip by mutableStateOf<Trip?>(null)
    var replayTrip by mutableStateOf<Trip?>(null)
        private set
    var replayPose by mutableStateOf<Pose?>(null)
        private set
    var replayPositionMs by mutableFloatStateOf(0f)
        private set
    var playing by mutableStateOf(false)
        private set
    var positioningDemo by mutableStateOf<PositioningDemo?>(null)
        private set
    var trackingTrail by mutableStateOf<List<Pose>>(emptyList())
        private set
    var replaySpeed by mutableFloatStateOf(1f)
        private set
    var modelConnection by mutableStateOf(ModelConnection())
        private set
    var nativeCoreStatus by mutableStateOf(NativeCoreStatus())
        private set
    var hasLocationPermission by mutableStateOf(repository.hub.hasLocationPermission())
        private set
    var busy by mutableStateOf(false)
        private set
    private var replayJob: Job? = null

    fun verifyNativeCore() {
        if (nativeCoreStatus.running) return
        nativeCoreStatus = NativeCoreStatus(running = true, message = "Checking native core…")
        viewModelScope.launch {
            nativeCoreStatus = try {
                withContext(Dispatchers.Default) { checkNativeCore() }
            } catch (cancelled: CancellationException) {
                throw cancelled
            } catch (_: LinkageError) {
                NativeCoreStatus(message = "Native core unavailable", detail = "This installation could not load its native library. GPS and recording remain available.")
            } catch (failure: Exception) {
                NativeCoreStatus(message = "Native check failed", detail = failure.message ?: "The kernel did not pass its synthetic integration check.")
            }
        }
    }

    init {
        viewModelScope.launch {
            recording.collectLatest { active ->
                if (!active) navigating = false
                if (active) {
                    trackingTrail = emptyList()
                    while (isActive) {
                        val now = SystemClock.elapsedRealtimeNanos()
                        trackingTrail = appendTrackingPose(trackingTrail,
                            navigationFix(now).takeIf { repository.hub.hasLocationPermission() }, now, repository.recordingStartedNs)
                        delay(250)
                    }
                }
            }
        }
        viewModelScope.launch {
            activeMap.drop(1).collect {
                routeVersion++
                routeJob?.cancel()
                closeReplay()
                route = null
                destination = null
                routeLoading = false
                routeOriginLabel = it.region.previewLabel
            }
        }
        viewModelScope.launch {
            repository.error.collect { error ->
                if (error != null) {
                    if (!recording.value) navigating = false
                    messages.emit(error)
                    repository.clearError()
                }
            }
        }
    }

    fun refreshPermissions() {
        hasLocationPermission = repository.hub.hasLocationPermission()
        repository.hub.start()
    }

    fun chooseDestination(place: Place) {
        if (navigating || mapBusy) return
        val maps = repository.maps
        val version = ++routeVersion
        routeJob?.cancel()
        closeReplay()
        destination = place
        overlay = null
        routeLoading = true
        routeJob = viewModelScope.launch {
            try {
                val fresh = navigationFix()?.takeIf {
                    hasLocationPermission && it.isFresh(SystemClock.elapsedRealtimeNanos()) && maps.contains(it.point)
                }
                val start = fresh?.point ?: maps.demonstrationStart
                routeOriginLabel = if (fresh == null) maps.region.previewLabel else if (fresh.filterRadius95Meters != null) "Native estimate start" else "GPS start"
                route = withContext(Dispatchers.Default) { maps.route(start, place.point) }
            } catch (cancelled: CancellationException) {
                throw cancelled
            } catch (error: Exception) {
                messages.emit(error.message ?: "This route could not be planned.")
                route = null
            } finally { if (routeVersion == version) routeLoading = false }
        }
    }

    fun clearRoute() { if (!navigating) { routeVersion++; routeJob?.cancel(); routeLoading = false; destination = null; route = null } }

    fun startDrive() {
        if (mapBusy || navigating) return
        val maps = repository.maps
        val fix = navigationFix()
        if (!hasLocationPermission || fix?.isFresh(SystemClock.elapsedRealtimeNanos()) != true) {
            notify("Waiting for a fresh GPS fix. You can explore the demo meanwhile.")
            return
        }
        if (!maps.contains(fix.point)) {
            notify("Your position is outside ${maps.region.name}. You can still explore route previews.")
            return
        }
        val target = destination ?: run { notify("Choose a destination first."); return }
        routeLoading = true
        val version = ++routeVersion
        routeJob?.cancel()
        routeJob = viewModelScope.launch {
            try {
                route = withContext(Dispatchers.Default) { maps.route(fix.point, target.point) }
                routeOriginLabel = if (fix.filterRadius95Meters != null) "Native estimate start" else "GPS start"
                if (route!!.distanceMeters < 20) {
                    messages.emit("You are already near this destination.")
                } else {
                    navigating = true
                    startRecording("Drive to ${target.name}")
                }
            } catch (cancelled: CancellationException) {
                throw cancelled
            } catch (error: Exception) {
                messages.emit(error.message ?: "The route from your location could not be planned.")
            } finally { if (routeVersion == version) routeLoading = false }
        }
    }

    fun endDrive() {
        stopRecording()
        navigating = false
        destination = null
        route = null
        tab = "Trips"
    }

    fun startRecording(name: String = "My drive") {
        if (mapBusy) { notify("Finish or cancel the map operation before recording."); return }
        if (recording.value) return
        if (!repository.hub.hasLocationPermission()) { notify("Allow precise location to record GPS alongside sensors."); return }
        if (replayTrip != null) closeReplay()
        val context = getApplication<Application>()
        try {
            context.startForegroundService(Intent(context, RecordingService::class.java).putExtra("name", name))
        } catch (error: Exception) { navigating = false; notify("Recording could not start: ${error.message}") }
    }

    fun stopRecording() {
        val context = getApplication<Application>()
        context.startService(Intent(context, RecordingService::class.java).setAction("STOP"))
    }

    fun startTracking() {
        if (navigating || mapBusy || recording.value) return
        clearRoute()
        tab = "Drive"
        startRecording("Position tracking")
    }

    fun stopTracking() {
        stopRecording()
        overlay = null
        tab = "Trips"
    }

    fun openPositioningDemo() {
        if (mapBusy || navigating || routeLoading) return
        if (recording.value) { notify("Stop and save your recording before starting the presentation demo."); return }
        closeReplay()
        destination = null
        val maps = repository.maps
        val version = ++routeVersion
        routeJob?.cancel()
        routeLoading = true
        routeJob = viewModelScope.launch {
            try {
                val operation = currentCoroutineContext()
                val demonstration = withContext(Dispatchers.Default) {
                    buildPositioningDemo(getApplication(), maps.demonstrationStart) { operation.ensureActive() }
                }
                val poses = demonstration.frames.mapNotNull { it.estimate.pose }
                val distance = demonstration.frames.zipWithNext().sumOf { (previous, current) -> previous.reference.distanceTo(current.reference) }
                playTrip(Trip("positioning-demo", "Through the GPS gap", 0, demonstration.durationMs, distance,
                    poses.size.toLong(), poses, synthetic = true))
                positioningDemo = demonstration
                route = DriveRoute(demonstration.frames.map { it.reference }, distance, emptyList())
                routeOriginLabel = "Simulation start"
                updateReplayPose()
            } catch (cancelled: CancellationException) { throw cancelled }
            catch (_: LinkageError) { messages.emit("The native positioning engine could not load. Try the route demo or reinstall this build.") }
            catch (failure: Exception) { messages.emit(failure.message ?: "The positioning demo could not start. Try again.") }
            finally { if (routeVersion == version) routeLoading = false }
        }
    }

    fun openDemo() {
        if (mapBusy || navigating) return
        if (recording.value) { notify("Stop recording before opening a replay."); return }
        val maps = repository.maps
        val version = ++routeVersion
        routeJob?.cancel()
        routeLoading = true
        routeJob = viewModelScope.launch {
            try {
                val demonstration = withContext(Dispatchers.Default) {
                    maps.route(maps.demonstrationStart, maps.places.first { it.id == maps.region.demoDestination }.point)
                }
                val velocity = 8.33
                val duration = ceil(demonstration.distanceMeters / velocity).toInt()
                val cumulative = mutableListOf(0.0)
                demonstration.points.zipWithNext().forEach { (previous, current) -> cumulative.add(cumulative.last() + previous.distanceTo(current)) }
                var segment = 0
                val samples = (0..duration).map { second ->
                    val distance = (second * velocity).coerceAtMost(cumulative.last())
                    while (segment < cumulative.lastIndex - 1 && cumulative[segment + 1] < distance) segment++
                    val length = (cumulative[segment + 1] - cumulative[segment]).coerceAtLeast(0.01)
                    val from = demonstration.points[segment]
                    val to = demonstration.points[segment + 1]
                    Pose(from.interpolate(to, (distance - cumulative[segment]) / length), velocity,
                        from.bearingTo(to), null, second * 1_000_000_000L, "Synthetic replay")
                }
                route = demonstration
                routeOriginLabel = "Demo start"
                destination = null
                playTrip(Trip("demo", if (maps.region.id == "bengaluru-central") "A little Bengaluru loop" else "Explore ${maps.region.name}", 0, duration * 1000L,
                    demonstration.distanceMeters, samples.size.toLong(), samples, synthetic = true))
            } catch (cancelled: CancellationException) { throw cancelled }
            catch (error: Exception) { messages.emit(error.message ?: "The sample route could not be loaded.") }
            finally { if (routeVersion == version) routeLoading = false }
        }
    }

    fun playTrip(trip: Trip) {
        if (mapBusy || navigating) { notify("Finish the current map operation or navigation before replaying a trip."); return }
        if (trip.points.size < 2) { notify("This recording has fewer than two GPS positions. Raw sensor data can still be exported."); return }
        if (recording.value) { notify("Stop recording before opening a replay."); return }
        replayJob?.cancel()
        positioningDemo = null
        val replay = trip.copy(durationMs = (trip.points.last().timestampNs - trip.points.first().timestampNs) / 1_000_000)
        replayTrip = replay
        if (!trip.synthetic) {
            route = DriveRoute(trip.points.map { it.point }, trip.distanceMeters, emptyList())
            routeOriginLabel = "Recording start"
        }
        replayPositionMs = 0f
        playing = true
        overlay = null
        tab = "Drive"
        replayJob = viewModelScope.launch {
            var previous = SystemClock.elapsedRealtime()
            while (isActive) {
                val now = SystemClock.elapsedRealtime()
                if (playing) {
                    replayPositionMs = (replayPositionMs + (now - previous) * replaySpeed).coerceAtMost(replay.durationMs.toFloat())
                    if (replayPositionMs >= replay.durationMs) playing = false
                }
                previous = now
                updateReplayPose()
                delay(50)
            }
        }
    }

    private fun updateReplayPose() {
        val trip = replayTrip ?: return
        positioningDemo?.let {
            replayPose = it.frameAt(replayPositionMs.toLong()).estimate.pose
            return
        }
        val target = trip.points.first().timestampNs + (replayPositionMs * 1_000_000).toLong()
        val insertion = trip.points.binarySearchBy(target) { it.timestampNs }
        val index = (if (insertion >= 0) insertion else -insertion - 2).coerceIn(0, trip.points.lastIndex - 1)
        val previous = trip.points[index]
        val next = trip.points[index + 1]
        val fraction = (target - previous.timestampNs).toDouble() / (next.timestampNs - previous.timestampNs).coerceAtLeast(1)
        replayPose = previous.copy(point = previous.point.interpolate(next.point, fraction), timestampNs = target,
            source = if (trip.synthetic) "Synthetic replay" else "Recorded GPS")
    }

    fun seekReplay(fraction: Float) {
        replayPositionMs = fraction.coerceIn(0f, 1f) * (replayTrip?.durationMs ?: 0)
        updateReplayPose()
    }
    fun togglePlayback() {
        if (replayPositionMs >= (replayTrip?.durationMs ?: 0)) replayPositionMs = 0f
        playing = !playing
    }
    fun cycleReplaySpeed() { replaySpeed = when (replaySpeed) { 1f -> 2f; 2f -> 4f; else -> 1f } }
    fun closeReplay() {
        replayJob?.cancel()
        replayJob = null
        replayTrip = null
        replayPose = null
        positioningDemo = null
        playing = false
        route = null
    }

    fun updateSettings(updated: AppSettings) {
        if (updated.modelEndpoint != settings.value.modelEndpoint) modelConnection = ModelConnection()
        repository.updateSettings(updated)
    }
    fun notify(message: String) { messages.tryEmit(message) }

    fun checkModel() {
        val configuration = settings.value
        if (configuration.modelEndpoint.isBlank()) { notify("Enter your team's model-server URL first."); return }
        modelConnection = ModelConnection("Checking server", "Checking protocol and capabilities…", checking = true)
        viewModelScope.launch {
            modelConnection = try {
                val health = HttpModelProvider(configuration.modelEndpoint).health()
                ModelConnection(if (health.ready) "Server ready" else "Model unavailable",
                    if (health.ready) "Protocol verified. Capabilities: ${health.capabilities.joinToString()}." else "The server is reachable but no model is loaded.", health.name)
            } catch (error: Exception) {
                ModelConnection("Connection failed", error.message ?: "Check the URL and your network.")
            }
        }
    }

    fun exportTrip(trip: Trip, uri: Uri) {
        viewModelScope.launch {
            try {
                withContext(Dispatchers.IO) {
                    getApplication<Application>().contentResolver.openOutputStream(uri)?.use { repository.tripStore.export(trip, it) }
                        ?: error("The selected location cannot be written.")
                }
                messages.emit("Recording exported.")
            } catch (error: Exception) { messages.emit("Export failed: ${error.message}") }
        }
    }
    fun importTrip(uri: Uri) {
        busy = true
        viewModelScope.launch {
            try {
                val trip = withContext(Dispatchers.IO) {
                    getApplication<Application>().contentResolver.openInputStream(uri)?.use(repository.tripStore::import)
                        ?: error("The selected file cannot be opened.")
                }
                repository.refreshTrips()
                selectedTrip = trip
                overlay = "trip"
                messages.emit("Recording imported to this phone.")
            } catch (error: Exception) { messages.emit("Import failed: ${error.message}") }
            finally { busy = false }
        }
    }
    fun deleteTrip(trip: Trip) {
        viewModelScope.launch {
            try {
                withContext(Dispatchers.IO) { repository.tripStore.delete(trip); repository.refreshTrips() }
                selectedTrip = null
                overlay = null
                messages.emit("Recording deleted from this phone.")
            } catch (error: Exception) { messages.emit(error.message ?: "The recording could not be deleted.") }
        }
    }

    fun importMap(uri: Uri) = mapOperation("Checking map pack…") { checkpoint ->
        val region = getApplication<Application>().contentResolver.openInputStream(uri)?.use { repository.mapPacks.import(it, checkpoint) }
            ?: error("The selected map file cannot be opened.")
        "${region.name} revision ${region.revision} installed. Select Use this map to switch."
    }

    fun downloadMap(url: String, checksum: String) = mapOperation("Downloading map…") { checkpoint ->
        val region = repository.mapPacks.download(url, checksum, { received, total ->
            mapProgress = if (total > 0) "Downloaded ${received * 100 / total}%" else "Downloaded ${received / 1024} KB"
        }, checkpoint)
        "${region.name} revision ${region.revision} installed and checksum verified."
    }

    fun activateMap(key: String) = mapOperation("Opening offline map…") { checkpoint ->
        checkpoint()
        repository.mapPacks.activate(key)
        "${repository.maps.region.name} is now your active offline map."
    }

    fun removeMap(key: String) = mapOperation("Removing offline map…") { checkpoint ->
        checkpoint()
        repository.mapPacks.remove(key)
        "Map removed from this phone. Recordings are unchanged."
    }

    fun cancelMapOperation() { mapJob?.cancel(); mapProgress = "Cancelling…" }

    private fun mapOperation(label: String, action: (() -> Unit) -> String) {
        if (mapBusy) return
        if (recording.value || navigating || replayTrip != null) {
            mapMessage = "Finish recording, navigation or replay before managing maps."
            return
        }
        clearRoute()
        mapBusy = true
        mapMessage = null
        mapProgress = label
        mapJob = viewModelScope.launch {
            try {
                val operationContext = currentCoroutineContext()
                mapMessage = withContext(Dispatchers.IO) { action { operationContext.ensureActive() } }
            } catch (cancelled: CancellationException) {
                mapMessage = "Map operation cancelled. Your active map is unchanged unless switching already finished."
                throw cancelled
            } catch (failure: Exception) {
                mapMessage = when (failure) {
                    is java.util.zip.ZipException -> "This file is not a complete .setumap archive. Choose another file."
                    is org.json.JSONException, is android.util.MalformedJsonException -> "This map contains invalid data. Ask the publisher for a new map pack."
                    else -> failure.message ?: "The map operation could not finish. Try again."
                }
            } finally { mapBusy = false; mapProgress = null }
        }
    }
}
