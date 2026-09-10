package com.setu.navigator.ui

import android.os.SystemClock
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.outlined.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.layout.onSizeChanged
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.platform.LocalWindowInfo
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.stateDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.setu.navigator.SetuViewModel
import com.setu.navigator.data.*
import com.setu.navigator.estimation.navigationPose
import kotlinx.coroutines.delay
import org.maplibre.android.camera.CameraUpdateFactory
import org.maplibre.android.geometry.LatLng
import org.maplibre.android.maps.MapLibreMap
import kotlin.math.ceil
import kotlin.math.roundToInt
import java.util.Locale

@Composable
fun DriveScreen(model: SetuViewModel, withLocationPermission: (() -> Unit) -> Unit, dark: Boolean, onFinish: () -> Unit) {
    val gps by model.livePose.collectAsStateWithLifecycle()
    val native by model.nativeEstimate.collectAsStateWithLifecycle()
    val locationEnabled by model.locationEnabled.collectAsStateWithLifecycle()
    val settings by model.settings.collectAsStateWithLifecycle()
    val maps by model.activeMap.collectAsStateWithLifecycle()
    val recording by model.recording.collectAsStateWithLifecycle()
    var following by rememberSaveable(recording, model.replayTrip?.id) { mutableStateOf(recording) }
    var now by remember { mutableLongStateOf(SystemClock.elapsedRealtimeNanos()) }
    var sheetHeight by remember { mutableIntStateOf(0) }
    var map by remember { mutableStateOf<MapLibreMap?>(null) }
    val windowSize = LocalWindowInfo.current.containerSize
    val landscape = with(LocalDensity.current) { windowSize.width.toDp() >= 560.dp && windowSize.width > windowSize.height }
    LaunchedEffect(Unit) { while (true) { now = SystemClock.elapsedRealtimeNanos(); delay(1000) } }
    val currentNs = maxOf(now, SystemClock.elapsedRealtimeNanos())
    val fix = navigationPose(gps, native, settings.nativePositioning, currentNs)
    val fresh = model.hasLocationPermission && fix?.isFresh(currentNs) == true
    val usingNative = fix?.filterRadius95Meters != null
    val outsideArea = fix?.let { !maps.contains(it.point) } == true
    val pose = if (model.replayTrip != null) model.replayPose else fix?.takeIf { model.hasLocationPermission }
        ?.let { if (fresh) it else it.copy(bearing = null, accuracyMeters = null, filterRadius95Meters = null) }
    val demoFrame = model.positioningDemo?.frameAt(model.replayPositionMs.toLong())
    val trail = model.positioningDemo?.trailAt(model.replayPositionMs.toLong()) ?: if (recording) model.trackingTrail else emptyList()
    val status = when {
        demoFrame != null -> "Simulated sensors"
        fresh && fix?.filterRadius95Meters != null && !locationEnabled -> "Sensor estimate"
        model.replayTrip != null -> "Replay"
        !model.hasLocationPermission -> "Location off"
        fresh && usingNative && fix?.mock == true -> "Test estimate"
        fresh && usingNative -> if (!locationEnabled || native.gpsAgeSeconds!! > 2) "Inertial estimate" else "GPS + IMU"
        fresh && fix?.mock == true -> "Test location"
        fresh && settings.nativePositioning -> "GPS · calibrating"
        fresh -> "GPS ready"
        fix?.mock == true -> "Last test fix"
        fix != null -> "Last GPS fix"
        !locationEnabled -> "Location off"
        settings.nativePositioning && native.status == "Estimate withheld" -> "Reacquire GPS"
        else -> "Finding GPS"
    }
    Row(Modifier.fillMaxSize()) {
        BoxWithConstraints(Modifier.weight(1f).fillMaxHeight()) {
            val visibleMapHeight = maxHeight - if (landscape) 0.dp else with(LocalDensity.current) { sheetHeight.toDp() }
            val compactControls = visibleMapHeight < 320.dp
            NavigationMap(model.route, pose, if (landscape) 0 else sheetHeight, dark,
                Modifier.fillMaxSize(), maps = maps, reserveControls = true, originLabel = model.routeOriginLabel, onReady = { map = it },
                trail = trail, comparisonPose = demoFrame?.lastGps,
                recordedPath = model.replayTrip?.takeUnless { it.synthetic }?.points,
                followPosition = following, onFollowInterrupted = { following = false })
            Row(Modifier.fillMaxWidth().statusBarsPadding().padding(horizontal = 20.dp, vertical = 16.dp),
                verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.SpaceBetween) {
                Surface(shape = RoundedCornerShape(18.dp), color = MaterialTheme.colorScheme.surface) {
                    Row(Modifier.padding(horizontal = 14.dp, vertical = 10.dp), verticalAlignment = Alignment.CenterVertically) {
                        BridgeMark(Modifier.size(30.dp))
                        if (LocalDensity.current.fontScale < 1.5f) Text("SETU", Modifier.padding(start = 8.dp), fontSize = 23.sp, fontWeight = FontWeight.ExtraBold, letterSpacing = 1.sp)
                    }
                }
                Surface(onClick = { model.overlay = "diagnostics" }, shape = CircleShape,
                    color = MaterialTheme.colorScheme.surface, modifier = Modifier.testTag("status-diagnostics")) {
                    Row(Modifier.padding(horizontal = 14.dp, vertical = 14.dp), verticalAlignment = Alignment.CenterVertically,
                        horizontalArrangement = Arrangement.spacedBy(7.dp)) {
                        Icon(if (model.replayTrip != null) Icons.Outlined.PlayCircle else if (fresh) Icons.Outlined.GpsFixed else Icons.Outlined.LocationSearching,
                            null, Modifier.size(17.dp), tint = MaterialTheme.colorScheme.primary)
                        Text(status, style = MaterialTheme.typography.labelMedium)
                    }
                }
            }
            val controls: @Composable () -> Unit = {
                Surface(shape = RoundedCornerShape(18.dp), color = MaterialTheme.colorScheme.surface) {
                    Column(Modifier.width(52.dp)) {
                        IconButton(onClick = { map?.animateCamera(CameraUpdateFactory.zoomIn()) }) { Icon(Icons.Outlined.Add, "Zoom in") }
                        HorizontalDivider(Modifier.padding(horizontal = 12.dp))
                        IconButton(onClick = { map?.animateCamera(CameraUpdateFactory.zoomOut()) }) { Icon(Icons.Outlined.Remove, "Zoom out") }
                    }
                }
                FilledTonalIconButton(onClick = {
                    val recenter: () -> Unit = {
                        val location = model.navigationFix()?.point
                        if (recording || model.replayTrip != null) {
                            following = true
                            if (pose == null) model.notify("Waiting for a position to follow.")
                        } else {
                            val target = location?.takeIf(maps::contains) ?: maps.center
                            map?.animateCamera(CameraUpdateFactory.newLatLngZoom(LatLng(target.latitude, target.longitude), 15.0))
                            if (location == null) model.notify("Waiting for a GPS fix. Showing ${maps.region.name}.")
                            else if (!maps.contains(location)) model.notify("Your location is outside ${maps.region.name}. Showing the active offline area.")
                        }
                    }
                    if (model.replayTrip != null) recenter() else withLocationPermission(recenter)
                }, modifier = Modifier.size(52.dp).testTag("follow-position")) {
                    Icon(if (following) Icons.Outlined.GpsFixed else Icons.Outlined.MyLocation,
                        if (recording || model.replayTrip != null) "Follow position" else "Find my location")
                }
            }
            val controlPosition = Modifier.align(Alignment.TopEnd).padding(end = 16.dp,
                top = if (compactControls) 116.dp else ((visibleMapHeight - 160.dp) / 2).coerceAtLeast(116.dp))
            if (compactControls) Row(controlPosition, horizontalArrangement = Arrangement.spacedBy(10.dp),
                verticalAlignment = Alignment.CenterVertically) { controls() }
            else Column(controlPosition, verticalArrangement = Arrangement.spacedBy(10.dp)) { controls() }
            if (!landscape) {
                Column(Modifier.align(Alignment.BottomCenter).fillMaxWidth().onSizeChanged { sheetHeight = it.height }) {
                    MapAttribution(model)
                    DriveTaskPanel(model, withLocationPermission, fix, fresh, outsideArea, onFinish)
                }
            } else MapAttribution(model, Modifier.align(Alignment.BottomStart))
        }
        if (landscape) Surface(Modifier.width(360.dp).fillMaxHeight(), color = MaterialTheme.colorScheme.surface) {
            Box(Modifier.statusBarsPadding()) { DriveTaskPanel(model, withLocationPermission, fix, fresh, outsideArea, onFinish) }
        }
    }
}

@Composable
private fun MapAttribution(model: SetuViewModel, modifier: Modifier = Modifier) {
    val maps by model.activeMap.collectAsStateWithLifecycle()
    Row(modifier.fillMaxWidth().padding(horizontal = 18.dp, vertical = 8.dp),
        horizontalArrangement = Arrangement.SpaceBetween, verticalAlignment = Alignment.CenterVertically) {
        Surface(shape = RoundedCornerShape(6.dp), color = MaterialTheme.colorScheme.surface.copy(alpha = 0.94f),
            modifier = Modifier.clickable { model.overlay = "about" }) {
            Box(Modifier.heightIn(min = 48.dp).padding(horizontal = 8.dp), contentAlignment = Alignment.Center) {
                Text(maps.region.attribution, style = MaterialTheme.typography.bodySmall, maxLines = 2)
            }
        }
        Surface(shape = RoundedCornerShape(6.dp), color = MaterialTheme.colorScheme.surface.copy(alpha = 0.94f),
            modifier = Modifier.clickable { model.overlay = "offline" }) {
            Row(Modifier.heightIn(min = 48.dp).padding(horizontal = 8.dp), verticalAlignment = Alignment.CenterVertically) {
                Icon(Icons.Outlined.OfflinePin, null, Modifier.size(13.dp))
                Text(" Offline map", style = MaterialTheme.typography.bodySmall)
            }
        }
    }
}

@Composable
private fun DriveTaskPanel(model: SetuViewModel, withLocationPermission: (() -> Unit) -> Unit, fix: Pose?, fresh: Boolean, outsideArea: Boolean, onFinish: () -> Unit) {
    val maps by model.activeMap.collectAsStateWithLifecycle()
    val recording by model.recording.collectAsStateWithLifecycle()
    Surface(shape = RoundedCornerShape(topStart = 28.dp, topEnd = 28.dp), color = MaterialTheme.colorScheme.surface) {
        Column(Modifier.fillMaxWidth().heightIn(max = 460.dp).verticalScroll(rememberScrollState()).padding(24.dp)) {
            when {
                model.routeLoading -> Row(Modifier.padding(vertical = 32.dp), verticalAlignment = Alignment.CenterVertically,
                    horizontalArrangement = Arrangement.spacedBy(16.dp)) {
                    CircularProgressIndicator(Modifier.size(24.dp), strokeWidth = 2.dp)
                    Text("Preparing your journey…", style = MaterialTheme.typography.bodyMedium)
                }
                model.replayTrip != null -> ReplayControls(model)
                model.navigating -> {
                    val active = model.route
                    val progress = active?.let { route -> fix?.let { routeProgress(route, it.point) } }
                    val maneuver = active?.maneuvers?.firstOrNull { it.index > (progress?.segment ?: 0) }
                    Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(16.dp)) {
                        Icon(when (maneuver?.direction) { "left" -> Icons.Outlined.TurnLeft; "right" -> Icons.Outlined.TurnRight; else -> Icons.Outlined.Straight },
                            null, Modifier.size(40.dp), tint = MaterialTheme.colorScheme.primary)
                        Text(when {
                            !fresh -> "Position unavailable"
                            (progress?.distanceFromRoad ?: 0.0) > 40 -> "Join the blue route"
                            else -> maneuver?.text ?: "Follow the blue route"
                        },
                            style = MaterialTheme.typography.titleLarge, modifier = Modifier.weight(1f))
                    }
                    Text(if (fresh) "${if (fix?.filterRadius95Meters != null) "Estimated sensor position" else "GPS guidance"} · recording locally" else "The route stays available offline. No reliable current position is available.",
                        Modifier.padding(top = 12.dp), style = MaterialTheme.typography.bodyMedium,
                        color = MaterialTheme.colorScheme.onSurfaceVariant)
                    SensorFallbackReadiness(model)
                    FilledTonalButton(onClick = onFinish, Modifier.fillMaxWidth().padding(top = 20.dp).heightIn(min = 52.dp)) {
                        Icon(Icons.Outlined.Flag, null, Modifier.size(20.dp)); Spacer(Modifier.width(8.dp)); Text("Finish drive")
                    }
                }
                recording -> LiveTrackingPanel(model, fix, fresh, outsideArea)
                model.destination != null && model.route != null -> {
                    Row(verticalAlignment = Alignment.Top) {
                        Column(Modifier.weight(1f)) {
                            Text(model.destination!!.name, style = MaterialTheme.typography.headlineSmall)
                            Text(model.destination!!.detail, Modifier.padding(top = 4.dp), style = MaterialTheme.typography.bodyMedium,
                                color = MaterialTheme.colorScheme.onSurfaceVariant)
                        }
                        IconButton(onClick = model::clearRoute) { Icon(Icons.Outlined.Close, "Clear destination") }
                    }
                    Row(Modifier.padding(top = 18.dp, bottom = 14.dp), verticalAlignment = Alignment.CenterVertically,
                        horizontalArrangement = Arrangement.spacedBy(12.dp)) {
                        Text(distanceLabel(model.route!!.distanceMeters), style = MaterialTheme.typography.titleLarge)
                        Text("≈ ${ceil(model.route!!.distanceMeters / 500).toInt().coerceAtLeast(1)} min", color = MaterialTheme.colorScheme.onSurfaceVariant)
                        Icon(Icons.Outlined.OfflinePin, "Available offline", Modifier.size(18.dp), tint = MaterialTheme.colorScheme.primary)
                    }
                    Button(onClick = { withLocationPermission(model::startDrive) },
                        enabled = (fresh && !outsideArea) || !model.hasLocationPermission,
                        modifier = Modifier.fillMaxWidth().heightIn(min = 54.dp).testTag("start-drive"), shape = RoundedCornerShape(16.dp)) {
                        Icon(Icons.Outlined.Navigation, null, Modifier.size(20.dp)); Spacer(Modifier.width(10.dp))
                        Text(when {
                            !model.hasLocationPermission -> "Enable location"
                            outsideArea -> "Outside offline area"
                            !fresh -> "Waiting for GPS"
                            else -> "Start drive & record"
                        })
                    }
                    if (outsideArea) InformationNote("Your last position is outside ${maps.region.name}. You can browse this preview, but cannot start a drive here.")
                    if (model.route!!.startOffsetMeters > 10 || model.route!!.destinationOffsetMeters > 10) {
                        InformationNote("Dashed links connect your pins to mapped roads, not verified driving lanes. Start gap: ${distanceLabel(model.route!!.startOffsetMeters)}; destination gap: ${distanceLabel(model.route!!.destinationOffsetMeters)}.")
                    }
                    SensorFallbackReadiness(model)
                    InformationNote("Origin: ${model.routeOriginLabel}. Time assumes 30 km/h, not live traffic. Starting recalculates from fresh GPS. Check road signs; turn restrictions are not included yet.")
                }
                else -> {
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        Text("Your journey, in view.", style = MaterialTheme.typography.headlineMedium, modifier = Modifier.weight(1f))
                        Icon(Icons.Outlined.NorthEast, null, Modifier.size(26.dp), tint = MaterialTheme.colorScheme.primary)
                    }
                    Text("Follow your position. Keep a record of every journey.", Modifier.padding(top = 6.dp, bottom = 18.dp),
                        style = MaterialTheme.typography.bodyMedium, color = MaterialTheme.colorScheme.onSurfaceVariant)
                    Button(onClick = { withLocationPermission(model::startTracking) },
                        modifier = Modifier.fillMaxWidth().padding(bottom = 10.dp).heightIn(min = 54.dp).testTag("start-tracking"),
                        shape = RoundedCornerShape(16.dp)) {
                        Icon(Icons.Outlined.MyLocation, null, Modifier.size(20.dp)); Spacer(Modifier.width(10.dp)); Text("Track my position")
                    }
                    FilledTonalButton(onClick = { model.overlay = "search" }, modifier = Modifier.fillMaxWidth().heightIn(min = 56.dp).testTag("destination-search"),
                        shape = RoundedCornerShape(16.dp), contentPadding = PaddingValues(horizontal = 18.dp)) {
                        Icon(Icons.Outlined.Search, null, Modifier.size(23.dp)); Spacer(Modifier.width(12.dp))
                        Text("Search a destination", Modifier.weight(1f), style = MaterialTheme.typography.bodyLarge)
                        Icon(Icons.Outlined.ArrowForward, null, Modifier.size(20.dp))
                    }
                    TextButton(onClick = model::openPositioningDemo, modifier = Modifier.fillMaxWidth().padding(top = 8.dp)
                        .heightIn(min = 48.dp).testTag("positioning-demo")) {
                        Icon(Icons.Outlined.PlayCircle, null, Modifier.size(20.dp)); Spacer(Modifier.width(8.dp)); Text("Demo GPS loss & recovery")
                    }
                    TextButton(onClick = model::openDemo, modifier = Modifier.fillMaxWidth().heightIn(min = 48.dp).testTag("open-demo")) { Text("Explore a sample route") }
                }
            }
        }
    }
}

@Composable
private fun SensorFallbackReadiness(model: SetuViewModel) {
    val settings by model.settings.collectAsStateWithLifecycle()
    val native by model.nativeEstimate.collectAsStateWithLifecycle()
    val locationEnabled by model.locationEnabled.collectAsStateWithLifecycle()
    val now = SystemClock.elapsedRealtimeNanos()
    val estimate = native.currentPose(now)
    val ready = settings.nativePositioning && estimate != null && locationEnabled &&
        (native.gpsAgeSeconds ?: Double.POSITIVE_INFINITY) <= 1.5 && (native.radius95Meters ?: 150.0) < 50.0
    Row(Modifier.fillMaxWidth().padding(top = 12.dp), verticalAlignment = Alignment.CenterVertically) {
        Column(Modifier.weight(1f).padding(end = 12.dp)) {
            Text(when {
                !settings.nativePositioning -> "Sensor fallback is off"
                ready -> "Sensor fallback initialized"
                estimate != null -> "Sensor estimate active"
                native.status == "Estimate withheld" -> "Sensor prediction limit reached"
                !locationEnabled -> "GPS off · no initialized sensor position"
                else -> "Keep GPS on · calibration needed"
            }, style = MaterialTheme.typography.titleSmall, modifier = Modifier.testTag("fallback-readiness"))
            Text(when {
                !settings.nativePositioning -> "Enable to use phone motion when calibrated."
                ready -> "Keep recording when testing GPS loss. Ten seconds is a ceiling, not a guaranteed duration."
                estimate != null -> "Prediction stops at the uncertainty or sampling limit, never beyond 10 seconds without GPS."
                !locationEnabled -> "Re-enable Location to align or recover. Internet is not needed."
                else -> native.calibrationHint ?: native.detail
            }, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
        }
        Switch(settings.nativePositioning, { model.updateSettings(settings.copy(nativePositioning = it)) },
            modifier = Modifier.semantics { contentDescription = "Sensor fallback" }.testTag("drive-fusion-toggle"))
    }
    if (settings.nativePositioning && !ready && estimate == null && locationEnabled) {
        TextButton(onClick = { model.overlay = "diagnostics" }, modifier = Modifier.heightIn(min = 48.dp)) { Text("Check calibration details") }
    }
}

@Composable
private fun LiveTrackingPanel(model: SetuViewModel, fix: Pose?, fresh: Boolean, outsideArea: Boolean) {
    val settings by model.settings.collectAsStateWithLifecycle()
    val native by model.nativeEstimate.collectAsStateWithLifecycle()
    val locationEnabled by model.locationEnabled.collectAsStateWithLifecycle()
    Text("Live positioning", style = MaterialTheme.typography.headlineSmall)
    Text(when {
        !fresh && !locationEnabled -> "Location is off · sensors are still recording"
        !fresh -> "Waiting for a fresh position"
        fix?.mock == true -> "Test location · recording locally"
        fix?.filterRadius95Meters != null -> "Sensor fusion · recording locally"
        else -> "GPS tracking · recording locally"
    }, Modifier.padding(top = 6.dp).testTag("tracking-source"), color = MaterialTheme.colorScheme.onSurfaceVariant,
        style = MaterialTheme.typography.bodyMedium)
    ReadingRow("Position", fix?.let { "%.5f, %.5f".format(Locale.US, it.point.latitude, it.point.longitude) } ?: "Not initialized", Icons.Outlined.MyLocation)
    ReadingRow("Speed", if (fresh) fix?.speedMps?.let {
        "%.1f %s".format(it * if (settings.units == "mph") 2.236936 else 3.6, settings.units)
    } ?: "Not provided" else "Unavailable", Icons.Outlined.Speed)
    val radius = fix?.filterRadius95Meters ?: fix?.accuracyMeters
    ReadingRow(if (fix?.filterRadius95Meters != null) "95% filter radius" else "GPS accuracy",
        if (fresh && radius != null) "%.1f m".format(radius) else "Unavailable", Icons.Outlined.GpsFixed)
    SensorFallbackReadiness(model)
    if (outsideArea) InformationNote("Position tracking continues here. Street detail is only available inside your downloaded offline area.")
    if (settings.nativePositioning) Text(when {
        !fresh && !locationEnabled -> "Turn Location on for a starting fix or to realign. Internet is not required. Keep this recording running when testing GPS loss."
        !fresh -> native.detail
        fix?.filterRadius95Meters == null -> native.detail
        native.gpsAgeSeconds?.let { it > 2 } == true || !locationEnabled -> "Sensors are predicting this path. Prediction stops after 10 seconds without GPS or excessive uncertainty; turn Location on to recover."
        else -> "Sensor fallback is initialized. Keep recording while testing GPS loss. The uncertainty ring is a model estimate, not verified road accuracy."
    },
        style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
    Button(onClick = model::stopTracking, modifier = Modifier.fillMaxWidth().padding(top = 12.dp)
        .heightIn(min = 52.dp).testTag("stop-tracking"), shape = RoundedCornerShape(16.dp)) {
        Icon(Icons.Outlined.Stop, null, Modifier.size(20.dp)); Spacer(Modifier.width(8.dp)); Text("Stop & save journey")
    }
}

@Composable
private fun ReplayControls(model: SetuViewModel) {
    val trip = model.replayTrip ?: return
    val demonstration = model.positioningDemo
    val frame = demonstration?.frameAt(model.replayPositionMs.toLong())
    Row(verticalAlignment = Alignment.CenterVertically) {
        Column(Modifier.weight(1f)) {
            Text(if (demonstration != null) "SIMULATED SENSOR INPUTS" else if (trip.synthetic) "DEMO REPLAY" else "SAVED DRIVE", style = MaterialTheme.typography.labelMedium,
                color = MaterialTheme.colorScheme.primary)
            Text(trip.name, Modifier.padding(top = 6.dp), style = MaterialTheme.typography.titleLarge)
        }
        IconButton(onClick = model::closeReplay) { Icon(Icons.Outlined.Close, "Exit replay") }
    }
    if (frame != null) {
        Text(when {
            !frame.gpsAvailable -> "GPS withheld · IMU tracking"
            frame.elapsedMs >= 14000 && (frame.estimate.gpsAgeSeconds ?: Double.MAX_VALUE) < 1 -> "GPS reacquired"
            else -> "GPS + motion"
        }, Modifier.padding(top = 12.dp).testTag("position-demo-stage"), style = MaterialTheme.typography.titleMedium,
            color = MaterialTheme.colorScheme.primary)
        Text("GPS age %.1f s · filter radius %.1f m (95%%)".format(frame.estimate.gpsAgeSeconds, frame.estimate.radius95Meters),
            Modifier.padding(top = 4.dp), style = MaterialTheme.typography.bodySmall)
        Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(4.dp)) {
            listOf("Lock" to 2000L, "GPS loss" to 10000L, "Recovery" to 18000L).forEach { (label, position) ->
                TextButton(onClick = {
                    if (model.playing) model.togglePlayback()
                    model.seekReplay(position.toFloat() / demonstration!!.durationMs)
                }, modifier = Modifier.weight(1f).heightIn(min = 48.dp).testTag("demo-phase-$position")) { Text(label) }
            }
        }
    }
    Row(Modifier.padding(top = 14.dp), verticalAlignment = Alignment.CenterVertically) {
        FilledIconButton(onClick = model::togglePlayback, modifier = Modifier.size(52.dp).testTag("replay-play-pause")) {
            Icon(if (model.playing) Icons.Outlined.Pause else Icons.Outlined.PlayArrow, if (model.playing) "Pause replay" else "Play replay")
        }
        Slider(value = model.replayPositionMs / trip.durationMs.coerceAtLeast(1), onValueChange = model::seekReplay,
            modifier = Modifier.weight(1f).padding(horizontal = 10.dp).testTag("replay-timeline").semantics {
                contentDescription = "Replay position"
                stateDescription = "${durationLabel(model.replayPositionMs.toLong())} of ${durationLabel(trip.durationMs)}"
            })
        TextButton(onClick = model::cycleReplaySpeed) { Text("${model.replaySpeed.roundToInt()}×") }
    }
    Row(Modifier.fillMaxWidth().padding(top = 6.dp), horizontalArrangement = Arrangement.SpaceBetween) {
        Text("${durationLabel(model.replayPositionMs.toLong())} / ${durationLabel(trip.durationMs)}", style = MaterialTheme.typography.labelMedium)
        Text(distanceLabel(trip.distanceMeters), style = MaterialTheme.typography.labelMedium)
    }
    if (demonstration != null) {
        Text("Green: reference · Blue: estimate · Amber: last GPS", Modifier.padding(top = 10.dp), style = MaterialTheme.typography.bodySmall)
        InformationNote("Simulated GPS + IMU; on-device native-engine output. An 8-second GPS gap, not a field-accuracy result.")
    } else InformationNote(when {
        trip.synthetic -> "Synthetic journey on real map data. Not a live drive or an accuracy benchmark."
        trip.points.any { it.filterRadius95Meters != null } -> "Recorded GPS + sensor estimates. Unobserved gaps stay blank; this is not live navigation or verified ground truth."
        else -> "Recorded GPS replay. Unobserved gaps stay blank. Not live navigation."
    })
}

@Composable
fun DestinationSearch(model: SetuViewModel) {
    val maps by model.activeMap.collectAsStateWithLifecycle()
    var query by remember { mutableStateOf("") }
    Column(Modifier.fillMaxSize()) {
        PageHeader("Where are we headed?", onBack = { model.overlay = null })
        OutlinedTextField(query, { query = it }, modifier = Modifier.fillMaxWidth().padding(horizontal = 24.dp).testTag("place-query"),
            placeholder = { Text("Search ${maps.region.name}") }, singleLine = true,
            leadingIcon = { Icon(Icons.Outlined.Search, null) }, shape = RoundedCornerShape(16.dp))
        Column(Modifier.fillMaxWidth().weight(1f).verticalScroll(rememberScrollState()).padding(horizontal = 24.dp)) {
            SectionTitle(if (query.isBlank()) "A few places to start" else "Matching places")
            val results = maps.places.filter { it.name.contains(query, ignoreCase = true) || it.detail.contains(query, ignoreCase = true) }
            if (results.isEmpty()) InformationNote("No match in this offline area. Try a nearby landmark or a shorter name.")
            results.forEach { place ->
                ListItem(headlineContent = { Text(place.name, fontWeight = FontWeight.SemiBold) },
                    supportingContent = { Text(place.detail) },
                    leadingContent = { Icon(Icons.Outlined.Place, null, tint = MaterialTheme.colorScheme.primary) },
                    trailingContent = { Icon(Icons.Outlined.NorthEast, null, Modifier.size(19.dp)) },
                    modifier = Modifier.clickable { model.chooseDestination(place) }.testTag("place-${place.id}"),
                    colors = ListItemDefaults.colors(containerColor = Color.Transparent))
                HorizontalDivider(color = MaterialTheme.colorScheme.outlineVariant)
            }
            InformationNote("${maps.region.name} is available offline. Destinations come from this map pack, not your current location.")
        }
    }
}
