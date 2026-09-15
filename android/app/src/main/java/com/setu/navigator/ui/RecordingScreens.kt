package com.setu.navigator.ui

import android.content.Intent
import android.net.Uri
import android.os.SystemClock
import android.provider.Settings
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.foundation.selection.toggleable
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.outlined.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.Path
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.setu.navigator.SetuViewModel
import com.setu.navigator.data.*
import kotlinx.coroutines.delay
import kotlin.math.*

@Composable
fun RecordScreen(model: SetuViewModel, withLocationPermission: (() -> Unit) -> Unit) {
    val sensors by model.sensors.collectAsStateWithLifecycle()
    val recording by model.recording.collectAsStateWithLifecycle()
    val records by model.recordCount.collectAsStateWithLifecycle()
    val fix by model.livePose.collectAsStateWithLifecycle()
    var name by rememberSaveable { mutableStateOf("") }
    var fixedMount by rememberSaveable { mutableStateOf(false) }
    val settings by model.settings.collectAsStateWithLifecycle()
    var elapsed by remember { mutableLongStateOf(0) }
    var nowNs by remember { mutableLongStateOf(SystemClock.elapsedRealtimeNanos()) }
    val context = LocalContext.current
    LaunchedEffect(recording) {
        while (true) {
            nowNs = SystemClock.elapsedRealtimeNanos()
            elapsed = if (recording) (nowNs - model.repository.recordingStartedNs) / 1_000_000 else 0
            delay(500)
        }
    }
    Column(Modifier.fillMaxSize().imePadding()) {
      Column(Modifier.weight(1f).fillMaxWidth().verticalScroll(rememberScrollState())) {
        PageHeader("Capture the road.", "Save a drive to replay it later, or to check how SETU held your position.", action = {
            IconButton(onClick = { model.overlay = "diagnostics" }) { Icon(Icons.Outlined.GraphicEq, "Open diagnostics") }
        })
        Column(Modifier.padding(horizontal = 24.dp)) {
            Surface(shape = SetuShape.card, color = MaterialTheme.colorScheme.primaryContainer) {
                Column(Modifier.fillMaxWidth().padding(24.dp)) {
                    Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                        Icon(if (recording) Icons.Outlined.FiberManualRecord else Icons.Outlined.RadioButtonChecked, null, Modifier.size(20.dp))
                        Text(if (recording) "Recording on this phone" else "Your phone. Your field kit.", style = MaterialTheme.typography.labelLarge)
                    }
                    Text(if (recording) durationLabel(elapsed) else "Ready when\nyou are.",
                        Modifier.padding(top = 20.dp, bottom = 12.dp), style = MaterialTheme.typography.displaySmall)
                    Text(if (recording) "${"%,d".format(records)} timestamped records · raw sensors + GPS"
                        else "Capture motion, satellite measurements and your path in one synchronized recording.",
                        style = MaterialTheme.typography.bodyMedium)
                }
            }
            SectionTitle("Device readiness")
            ReadingRow("Accelerometer", if (sensors.hasAccelerometer) "Detected" else "Not available", Icons.Outlined.Sensors)
            ReadingRow("Gyroscope", if (sensors.hasGyroscope) "Detected" else "Not available", Icons.Outlined.ScreenRotation)
            ReadingRow("Achieved IMU rate", if (sensors.achievedHz > 0) "%.0f Hz · Tier %s".format(sensors.achievedHz, sensors.tier) else "Measuring…", Icons.Outlined.GraphicEq)
            ReadingRow("GPS position", when {
                !model.hasLocationPermission -> "Permission needed"
                fix == null -> "Waiting for a fix"
                fix?.isFresh(maxOf(nowNs, SystemClock.elapsedRealtimeNanos())) == true -> "Fresh fix"
                else -> "Last fix · waiting for GPS"
            }, Icons.Outlined.GpsFixed)
            if (!model.hasLocationPermission) TextButton(onClick = {
                context.startActivity(Intent(Settings.ACTION_APPLICATION_DETAILS_SETTINGS, Uri.parse("package:${context.packageName}")))
            }) { Text("Manage app permissions") }
            if (!recording) OutlinedTextField(name, { name = it.take(100) }, label = { Text("Drive name (optional)") },
                placeholder = { Text("Evening loop, tunnel trial…") }, singleLine = true, shape = SetuShape.action,
                modifier = Modifier.fillMaxWidth().padding(top = 16.dp).testTag("recording-name"))
            SectionTitle("Training collection")
            ReadingRow("Activity label", settings.vehicle, Icons.Outlined.DirectionsCar)
            if (settings.vehicle == "Walking") InformationNote("Walking mode uses detected steps, not the car speed model. Hold the phone pointing along travel. Calibrate step length in Settings; raw IMU and step events stay in your recording.")
            if (!recording && settings.vehicle != "Walking") Row(Modifier.fillMaxWidth().testTag("fixed-mount")
                .toggleable(value = fixedMount, role = Role.Checkbox, onValueChange = { fixedMount = it }), verticalAlignment = Alignment.CenterVertically) {
                Checkbox(fixedMount, null)
                Text("Phone is secured in a fixed mount", style = MaterialTheme.typography.bodyMedium)
            }
            if (!recording && settings.vehicle != "Walking" && !fixedMount) {
                InformationNote("Mount not confirmed: this recording can be reviewed, but is excluded from model training. Confirm only a securely attached phone; a pocket or loose storage compartment is not a fixed mount.")
            }
            InformationNote("For training, leave GPS on for the whole drive. Save first, then open Trips → Export training bundle. SETU compares full-rate IMU with GPS every second and separately replays GPS gaps without changing live navigation. Missing or poor GPS is flagged, never invented.")
            InformationNote("Recordings stay on this phone. If enabled in Model integration, live IMU windows are shared with your server. Secure the phone and start before driving. Export is always your choice.")
            InformationNote("Recording with the screen off? Check Background recording in Settings first. Battery saver and background restrictions can pause sensor capture.")
            Spacer(Modifier.height(16.dp))
        }
      }
      Surface(color = MaterialTheme.colorScheme.surface) {
        Column(Modifier.fillMaxWidth().padding(horizontal = 24.dp, vertical = 12.dp)) {
            Text("Keep SETU visible for this demo. The screen stays on while recording.",
                Modifier.padding(bottom = 8.dp), style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant)
            Button(onClick = {
                if (recording) model.stopRecording() else withLocationPermission { model.startRecording(name.ifBlank { "My drive" }, fixedMount) }
            }, modifier = Modifier.fillMaxWidth().heightIn(min = 56.dp).testTag("record-toggle"),
                shape = SetuShape.action) {
                Icon(if (recording) Icons.Outlined.Stop else Icons.Outlined.FiberManualRecord, null, Modifier.size(20.dp))
                Spacer(Modifier.width(10.dp)); Text(if (recording) "Stop & save recording" else "Start recording")
            }
        }
      }
    }
}

@Composable
fun DiagnosticsScreen(model: SetuViewModel) {
    val state by model.sensors.collectAsStateWithLifecycle()
    val pose by model.livePose.collectAsStateWithLifecycle()
    var nowNs by remember { mutableLongStateOf(SystemClock.elapsedRealtimeNanos()) }
    LaunchedEffect(Unit) { while (true) { nowNs = SystemClock.elapsedRealtimeNanos(); delay(1000) } }
    val observationNowNs = maxOf(nowNs, SystemClock.elapsedRealtimeNanos())
    val history = remember { mutableStateListOf<Float>() }
    LaunchedEffect(state.lastSampleNs) {
        if (state.lastSampleNs > 0) {
            history.add((sqrt(state.accelerometer.sumOf { (it * it).toDouble() }) - 9.80665).toFloat())
            if (history.size > 80) history.removeAt(0)
        }
    }
    Column(Modifier.fillMaxSize()) {
        PageHeader("Under the hood", "The measurements behind your position.", onBack = { model.overlay = null })
        Column(Modifier.weight(1f).verticalScroll(rememberScrollState()).navigationBarsPadding().padding(horizontal = 24.dp)) {
            Surface(shape = SetuShape.card, color = MaterialTheme.colorScheme.primaryContainer) {
                Row(Modifier.fillMaxWidth().padding(22.dp), verticalAlignment = Alignment.CenterVertically) {
                    Column(Modifier.weight(1f)) {
                        Text("CAPABILITY TIER", style = MaterialTheme.typography.labelMedium)
                        Text(if (state.achievedHz > 0) "Tier ${state.tier}" else "Measuring", style = MaterialTheme.typography.headlineMedium,
                            modifier = Modifier.padding(top = 8.dp))
                        Text(if (state.achievedHz > 0) "%.1f Hz achieved".format(state.achievedHz) else "Waiting for sensor timestamps", style = MaterialTheme.typography.bodyMedium)
                    }
                    Icon(Icons.Outlined.Sensors, null, Modifier.size(44.dp))
                }
            }
            SectionTitle("Motion, right now")
            Text("Acceleration magnitude minus gravity · m/s²", style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant)
            SensorChart(history.toList(), Modifier.fillMaxWidth().height(100.dp).padding(vertical = 12.dp))
            AxisReadings("Accelerometer", state.accelerometer, "m/s²", state.hasAccelerometer && state.lastSampleNs > 0)
            AxisReadings("Gyroscope", state.gyroscope, "rad/s", state.hasGyroscope && state.lastSampleNs > 0)
            Text("Gyroscope values are turn rate, not the angle turned. A fast turn can produce a large reading without forward motion.",
                style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
            ReadingRow("Pressure", state.pressure?.let { "%.1f hPa".format(it) } ?: "Not available", Icons.Outlined.Height)
            SectionTitle("Satellite reception")
            ReadingRow("Satellites used / seen", "${state.satellitesUsed} / ${state.satellites}", Icons.Outlined.SatelliteAlt)
            ReadingRow("Mean signal strength", state.meanCn0?.let { "%.1f dB-Hz".format(it) } ?: "No measurements", Icons.Outlined.SignalCellularAlt)
            SectionTitle("Latest GPS observation")
            if (pose?.mock == true) Text("Test location · not live GPS", style = MaterialTheme.typography.labelLarge,
                color = MaterialTheme.colorScheme.primary, modifier = Modifier.padding(bottom = 8.dp))
            val age = when {
                pose == null -> "No fix"
                pose!!.isFresh(observationNowNs) -> "Fresh fix"
                observationNowNs < pose!!.timestampNs -> "Invalid timestamp"
                else -> "Last fix · ${(observationNowNs - pose!!.timestampNs) / 1_000_000_000L} s ago"
            }
            ReadingRow("Observation age", age, Icons.Outlined.Schedule)
            ReadingRow("GPS accuracy estimate", pose?.accuracyMeters?.let { "±${it.roundToInt()} m" } ?: "Not provided", Icons.Outlined.GpsFixed)
            val settings by model.settings.collectAsStateWithLifecycle()
            ReadingRow("GPS speed", pose?.speedMps?.let { "%.1f %s".format(it * if (settings.units == "mph") 2.236936 else 3.6, settings.units) } ?: "Not provided", Icons.Outlined.Speed)
            ReadingRow("Course over ground", pose?.bearing?.let { "${it.roundToInt()}°" } ?: "Not provided", Icons.Outlined.Explore)
            ReadingRow("Altitude (WGS84)", pose?.altitudeMeters?.let { "${it.roundToInt()} m" } ?: "Not provided", Icons.Outlined.Height)
            Text("Values belong to this observation, not necessarily your position now. Missing measurements are not zero.",
                style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant,
                modifier = Modifier.padding(vertical = 12.dp))
            SectionTitle("Estimation channels")
            val inference by model.modelInference.collectAsStateWithLifecycle()
            val learned = inference.recentMeasurement(observationNowNs)
            ReadingRow("Model speed · not measured motion", learned?.let { "%.2f m/s".format(it.speedMps) } ?: "No usable model speed", Icons.Outlined.Science)
            Text(inference.detail, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
            OutlinedButton(onClick = { model.overlay = "models" }, modifier = Modifier.fillMaxWidth().padding(top = 16.dp)) {
                Text("Research model server")
            }
            SectionTitle("Native estimator")
            val native by model.nativeEstimate.collectAsStateWithLifecycle()
            val currentNative = native.currentPose(observationNowNs)
            Text(if (native.pose != null && currentNative == null) "Waiting for fresh IMU" else native.status,
                style = MaterialTheme.typography.titleLarge, modifier = Modifier.testTag("live-native-status"))
            Text(native.detail, style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant, modifier = Modifier.padding(top = 8.dp, bottom = 12.dp))
            if (native.pose?.mock == true) Text("Test-provider inputs · not a road drive", style = MaterialTheme.typography.labelMedium)
            ReadingRow("Paired IMU samples", native.pairedSamples.toString(), Icons.Outlined.Sensors)
            ReadingRow("Heading alignment", native.headingSource ?: "Not initialized", Icons.Outlined.Explore)
            ReadingRow("GPS accepted / gated", "${native.accepted} / ${native.gated}", Icons.Outlined.GpsFixed)
            ReadingRow("Delayed fixes replayed", native.delayedCorrections.toString(), Icons.Outlined.History)
            ReadingRow("Last GPS aid", native.gpsAgeSeconds?.takeIf { currentNative != null }?.let { "%.1f s ago".format(it) } ?: "Unavailable", Icons.Outlined.Schedule)
            ReadingRow("Sensor resets / unpaired", "${native.resets} / ${native.pairingDrops}", Icons.Outlined.Sync)
            if (settings.vehicle == "Walking") {
                ReadingRow("Step detector", if (state.stepDetectorActive) "Active" else if (state.hasStepDetector) "Needs physical activity permission" else "Not available", Icons.Outlined.Sensors)
                ReadingRow("Positioned / rejected steps", "${native.walkingSteps} / ${native.rejectedSteps}", Icons.Outlined.DirectionsWalk)
                ReadingRow("Step length", "%.2f m".format(settings.walkingStepLengthMeters), Icons.Outlined.Straighten)
            } else {
                ReadingRow("Vehicle mount calibration", if (!native.vehicleConstraintsEnabled) "Car constraints not applied" else if (native.vehicleCalibrated) "Aligned from motion" else "Not calibrated · 10 s ceiling", Icons.Outlined.DirectionsCar)
                ReadingRow("Stop / turn / vibration updates", "${native.zupts} / ${native.turnSpeedUpdates} / ${native.spectralUpdates}", Icons.Outlined.Sensors)
            }
            ReadingRow(if (settings.vehicle == "Walking") "Step-based speed" else "Native speed", currentNative?.speedMps?.let { "%.1f %s".format(it * if (settings.units == "mph") 2.236936 else 3.6, settings.units) } ?: "Unavailable", Icons.Outlined.Speed)
            ReadingRow(if (settings.vehicle == "Walking") "Model radius · unvalidated" else "95% filter radius", native.radius95Meters?.takeIf { currentNative != null }?.let { "%.1f m".format(it) } ?: "Unavailable", Icons.Outlined.RadioButtonUnchecked)
            Row(Modifier.fillMaxWidth().padding(vertical = 12.dp), verticalAlignment = Alignment.CenterVertically) {
                Column(Modifier.weight(1f).padding(end = 12.dp)) {
                    Text("Use native positioning", style = MaterialTheme.typography.titleSmall)
                    Text("Experimental · GPS fallback", style = MaterialTheme.typography.bodySmall)
                }
                Switch(settings.nativePositioning, { model.updateSettings(settings.copy(nativePositioning = it)) },
                    modifier = Modifier.testTag("native-positioning-toggle").semantics { contentDescription = "Use native positioning" })
            }
            InformationNote("Experimental positioning, not verified accuracy. No road matching. Walking requires detected steps and calibrated step length; no steps means no new displacement. Vehicle mode requires a secured phone and motion calibration. The radius is a model estimate, not measured coverage.")
            SectionTitle("Synthetic integration check")
            Text("16-state RI-EKF · C++20 / Eigen 3.4", style = MaterialTheme.typography.bodyMedium)
            Text(model.nativeCoreStatus.message, style = MaterialTheme.typography.titleMedium,
                modifier = Modifier.padding(top = 12.dp).testTag("native-core-status"))
            Text(model.nativeCoreStatus.detail, style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant, modifier = Modifier.padding(top = 6.dp))
            OutlinedButton(onClick = model::verifyNativeCore, enabled = !model.nativeCoreStatus.running,
                modifier = Modifier.fillMaxWidth().padding(top = 12.dp).testTag("verify-native-core")) {
                Text(if (model.nativeCoreStatus.running) "Checking…" else "Run native integration check")
            }
            InformationNote("Tier describes available sensor rate, not validated accuracy. GPS accuracy is Android's estimate, not SETU's filter covariance.")
            Spacer(Modifier.height(20.dp))
        }
    }
}

@Composable
fun ReadingRow(label: String, value: String, icon: androidx.compose.ui.graphics.vector.ImageVector) {
    Row(Modifier.fillMaxWidth().testTag("reading-$label").padding(vertical = 12.dp), verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(12.dp)) {
        Icon(icon, null, Modifier.size(21.dp), tint = MaterialTheme.colorScheme.onSurfaceVariant)
        Text(label, style = MaterialTheme.typography.bodyMedium, modifier = Modifier.weight(1f))
        Text(value, style = MaterialTheme.typography.labelLarge, color = MaterialTheme.colorScheme.primary)
    }
    HorizontalDivider(color = MaterialTheme.colorScheme.outlineVariant)
}

@Composable
private fun AxisReadings(label: String, readings: List<Float>, unit: String, available: Boolean) {
    Column(Modifier.fillMaxWidth().padding(vertical = 12.dp)) {
        Text("$label · $unit", style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
        Row(Modifier.fillMaxWidth().padding(top = 6.dp), horizontalArrangement = Arrangement.SpaceBetween) {
            listOf("X", "Y", "Z").forEachIndexed { index, axis ->
                Text("$axis  ${if (available) "%+.2f".format(readings.getOrElse(index) { 0f }) else "—"}",
                    style = MaterialTheme.typography.titleMedium)
            }
        }
    }
}

@Composable
private fun SensorChart(values: List<Float>, modifier: Modifier) {
    val ink = MaterialTheme.colorScheme.primary
    val rule = MaterialTheme.colorScheme.outlineVariant
    Canvas(modifier) {
        drawLine(rule, Offset(0f, size.height / 2), Offset(size.width, size.height / 2), 1f)
        if (values.size > 1) {
            val scale = values.maxOf { abs(it) }.coerceAtLeast(0.5f)
            val path = Path()
            values.forEachIndexed { index, value ->
                val horizontal = size.width * index / (values.size - 1)
                val vertical = size.height / 2 - value / scale * size.height * 0.42f
                if (index == 0) path.moveTo(horizontal, vertical) else path.lineTo(horizontal, vertical)
            }
            drawPath(path, ink, style = Stroke(width = 2.dp.toPx()))
        }
    }
}
