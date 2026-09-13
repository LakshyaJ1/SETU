package com.setu.navigator.ui

import android.content.Intent
import android.net.Uri
import android.os.SystemClock
import android.provider.Settings
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.outlined.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.setu.navigator.BuildConfig
import com.setu.navigator.SetuViewModel
import kotlinx.coroutines.delay

@Composable
fun SettingsScreen(model: SetuViewModel) {
    val context = LocalContext.current
    val settings by model.settings.collectAsStateWithLifecycle()
    val maps by model.activeMap.collectAsStateWithLifecycle()
    var choice by remember { mutableStateOf<String?>(null) }
    var showBackgroundHelp by remember { mutableStateOf(false) }
    Column(Modifier.fillMaxSize().verticalScroll(rememberScrollState())) {
        PageHeader("Make it yours", "A few preferences. A lot of open road.")
        Column(Modifier.padding(horizontal = 24.dp)) {
            Surface(shape = SetuShape.card, color = MaterialTheme.colorScheme.primaryContainer,
                onClick = { model.overlay = "offline" }) {
                Row(Modifier.fillMaxWidth().padding(20.dp), verticalAlignment = Alignment.CenterVertically,
                    horizontalArrangement = Arrangement.spacedBy(16.dp)) {
                    Icon(Icons.Outlined.Map, null, Modifier.size(36.dp))
                    Column(Modifier.weight(1f)) {
                        Text(maps.region.name, style = MaterialTheme.typography.titleMedium)
                        Text("Active offline map", Modifier.padding(top = 4.dp), style = MaterialTheme.typography.bodySmall)
                    }
                    Icon(Icons.Outlined.ChevronRight, null)
                }
            }
            // Grouped by what a person is trying to do. "Device diagnostics" and "Model
            // integration" used to sit directly under the everyday preferences, which made the
            // whole screen read like a lab bench; they are still one tap away, under a heading that
            // says who they are for.
            SectionTitle("Your drive")
            PreferenceRow("Vehicle", settings.vehicle, Icons.Outlined.DirectionsCar) { choice = "Vehicle" }
            PreferenceRow("Speed units", settings.units, Icons.Outlined.Speed) { choice = "Speed units" }
            ListItem(headlineContent = { Text("Keep screen awake") }, supportingContent = { Text("During navigation and replay") },
                leadingContent = { Icon(Icons.Outlined.WbSunny, null) },
                trailingContent = { Switch(settings.keepScreenOn, { model.updateSettings(settings.copy(keepScreenOn = it)) }) },
                colors = ListItemDefaults.colors(containerColor = Color.Transparent))

            SectionTitle("Appearance")
            PreferenceRow("Theme", settings.theme, Icons.Outlined.Palette) { choice = "Appearance" }

            SectionTitle("Recording")
            PreferenceRow("Background recording", "Stop battery settings pausing sensors", Icons.Outlined.BatteryChargingFull) { showBackgroundHelp = true }

            SectionTitle("About")
            PreferenceRow("About SETU", "What it is and how it works", Icons.Outlined.Info) { model.overlay = "about" }
            PreferenceRow("Offline maps", "Coverage, updates and attribution", Icons.Outlined.OfflinePin) { model.overlay = "offline" }

            SectionTitle("For developers")
            PreferenceRow("Sensor diagnostics", "Live sensor, GPS and capability readout", Icons.Outlined.GraphicEq) { model.overlay = "diagnostics" }
            PreferenceRow("Research model server", model.modelConnection.status, Icons.Outlined.Cable) { model.overlay = "models" }

            InformationNote("No account. No automatic uploads. Your drives stay on this phone until you choose to export them.")
            Spacer(Modifier.height(20.dp))
        }
    }
    if (showBackgroundHelp) AlertDialog(
        onDismissRequest = { showBackgroundHelp = false },
        title = { Text("Keep recording in the background") },
        text = { Text("Some phones pause SETU when you switch apps or lock the screen, even during recording. Open App info, then Battery usage, and enable Allow background activity or Unrestricted. Also turn off Battery saver in phone settings while recording; it can override app access. This uses more battery. Test a short recording before relying on screen-off capture. Battery access does not make GPS-free positioning accurate.") },
        confirmButton = { TextButton(onClick = {
            showBackgroundHelp = false
            runCatching { context.startActivity(Intent(Settings.ACTION_APPLICATION_DETAILS_SETTINGS, Uri.parse("package:${context.packageName}"))) }
                .onFailure { model.repository.reportError("Open SETU's App info in phone settings, then check Battery usage.") }
        }) { Text("Open app settings") } },
        dismissButton = { TextButton(onClick = { showBackgroundHelp = false }) { Text("Not now") } }
    )
    if (choice != null) {
        val options = when (choice) { "Appearance" -> listOf("System", "Light", "Dark"); "Speed units" -> listOf("km/h", "mph"); else -> listOf("Car", "Two-wheeler", "Heavy vehicle") }
        val current = when (choice) { "Appearance" -> settings.theme; "Speed units" -> settings.units; else -> settings.vehicle }
        AlertDialog(onDismissRequest = { choice = null }, title = { Text(choice!!) },
            text = {
                Column {
                    options.forEach { option ->
                        Row(Modifier.fillMaxWidth().testTag("preference-option-$option").clickable {
                            model.updateSettings(when (choice) {
                                "Appearance" -> settings.copy(theme = option)
                                "Speed units" -> settings.copy(units = option)
                                else -> settings.copy(vehicle = option)
                            }); choice = null
                        }.padding(vertical = 8.dp), verticalAlignment = Alignment.CenterVertically) {
                            RadioButton(selected = current == option, onClick = null)
                            Text(option, Modifier.padding(start = 12.dp))
                        }
                    }
                }
            }, confirmButton = { TextButton(onClick = { choice = null }) { Text("Cancel") } })
    }
}

@Composable
private fun PreferenceRow(title: String, detail: String, icon: ImageVector, onClick: () -> Unit) {
    ListItem(headlineContent = { Text(title, fontWeight = FontWeight.Medium) }, supportingContent = { Text(detail) },
        leadingContent = { Icon(icon, null, tint = MaterialTheme.colorScheme.onSurfaceVariant) },
        trailingContent = { Icon(Icons.Outlined.ChevronRight, null, Modifier.size(20.dp)) },
        modifier = Modifier.clickable(onClick = onClick), colors = ListItemDefaults.colors(containerColor = Color.Transparent))
    HorizontalDivider(color = MaterialTheme.colorScheme.outlineVariant)
}

@Composable
fun ModelSettingsScreen(model: SetuViewModel) {
    val settings by model.settings.collectAsStateWithLifecycle()
    var endpoint by remember(settings.modelEndpoint) { mutableStateOf(settings.modelEndpoint) }
    val connection = model.modelConnection
    val inference by model.modelInference.collectAsStateWithLifecycle()
    var confirmSharing by remember { mutableStateOf(false) }
    var nowNs by remember { mutableLongStateOf(SystemClock.elapsedRealtimeNanos()) }
    LaunchedEffect(Unit) { while (true) { nowNs = SystemClock.elapsedRealtimeNanos(); delay(500) } }
    val measurement = inference.recentMeasurement(nowNs)
    if (confirmSharing) AlertDialog(
        onDismissRequest = { confirmSharing = false },
        title = { Text("Share sensor windows with this server?") },
        text = { Column(Modifier.verticalScroll(rememberScrollState())) {
            Text("While recording, SETU sends accelerometer and gyroscope readings, monotonic timestamps and your vehicle type to ${settings.modelEndpoint}. This includes background recording. GPS coordinates and saved trips are not sent. The server can observe your IP address. Research results do not control navigation. Turn sharing off here to stop future requests; already-sent data cannot be recalled.")
        } },
        confirmButton = { TextButton(onClick = { confirmSharing = false; model.updateSettings(settings.copy(modelSharingAllowed = true)) }) { Text("Enable sharing") } },
        dismissButton = { TextButton(onClick = { confirmSharing = false }) { Text("Keep on phone") } },
    )
    Column(Modifier.fillMaxSize().verticalScroll(rememberScrollState()).navigationBarsPadding()) {
        PageHeader("Research model server", "Connect and inspect a learned-speed server. Navigation does not depend on it.", onBack = { model.overlay = null })
        Column(Modifier.padding(horizontal = 24.dp)) {
            Surface(shape = SetuShape.card, color = MaterialTheme.colorScheme.surfaceContainer) {
                Column(Modifier.fillMaxWidth().padding(20.dp)) {
                    Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                        Icon(Icons.Outlined.Cable, null)
                        Text(connection.status, style = MaterialTheme.typography.titleLarge)
                    }
                    Text(connection.detail, Modifier.padding(top = 12.dp), style = MaterialTheme.typography.bodyMedium)
                    connection.modelName?.let { Text(it, Modifier.padding(top = 8.dp), style = MaterialTheme.typography.labelMedium) }
                }
            }
            SectionTitle("Model server")
            Text("Connect a server that implements the SETU model v1 contract. Maps, recording and replay do not depend on it.",
                style = MaterialTheme.typography.bodyMedium, color = MaterialTheme.colorScheme.onSurfaceVariant)
            OutlinedTextField(endpoint, { endpoint = it }, label = { Text("Model-server URL") }, placeholder = { Text("https://your-model-server") },
                singleLine = true, shape = SetuShape.action,
                modifier = Modifier.fillMaxWidth().padding(top = 20.dp).testTag("model-endpoint"))
            Button(onClick = { model.updateSettings(settings.copy(modelEndpoint = endpoint)); model.checkModel() },
                enabled = endpoint.isNotBlank() && !connection.checking,
                modifier = Modifier.fillMaxWidth().padding(top = 14.dp).heightIn(min = 54.dp).testTag("check-model"), shape = SetuShape.action) {
                if (connection.checking) { CircularProgressIndicator(Modifier.size(18.dp), strokeWidth = 2.dp); Spacer(Modifier.width(10.dp)) }
                Text(if (connection.checking) "Checking connection…" else "Save & check connection")
            }
            SectionTitle("Sensor sharing")
            ListItem(
                headlineContent = { Text("Share during recordings") },
                supportingContent = { Text("Off by default. Sends live IMU windows, never GPS coordinates or saved trips.") },
                trailingContent = { Switch(settings.modelSharingAllowed, { enabled ->
                    if (enabled) confirmSharing = true else model.updateSettings(settings.copy(modelSharingAllowed = false))
                }, enabled = endpoint == settings.modelEndpoint && endpoint.isNotBlank(), modifier = Modifier
                    .semantics { contentDescription = "Share sensor windows during recording" }.testTag("model-sharing")) },
                colors = ListItemDefaults.colors(containerColor = Color.Transparent),
            )
            if (endpoint != settings.modelEndpoint) Text("Save the server address before enabling sharing. Changing servers turns sharing off.",
                style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
            SectionTitle("Live evaluation")
            Text(inference.status, style = MaterialTheme.typography.titleMedium, modifier = Modifier.testTag("model-inference-status"))
            Text(inference.detail, Modifier.padding(top = 8.dp), style = MaterialTheme.typography.bodyMedium)
            if (measurement != null) {
                ReadingRow("Model speed · not navigation", "%.2f m/s".format(measurement.speedMps), Icons.Outlined.Speed)
                ReadingRow("Reported sigma · unverified", "%.2f m/s".format(measurement.sigmaMps), Icons.Outlined.Science)
                ReadingRow("Model validity", "%.2f".format(measurement.validity), Icons.Outlined.VerifiedUser)
            } else if (inference.measurement != null) {
                Text("Last model result is stale; no current prediction.", Modifier.padding(top = 8.dp), style = MaterialTheme.typography.bodySmall)
            }
            inference.latencyMs?.let { ReadingRow("Last request latency", "$it ms", Icons.Outlined.Schedule) }
            inference.health?.reason?.let { InformationNote(it) }
            SectionTitle("What the handoff includes")
            ReadingRow("Protocol", "setu.model.v1", Icons.Outlined.DataObject)
            ReadingRow("Health endpoint", "GET /v1/health", Icons.Outlined.MonitorHeart)
            ReadingRow("Measurement endpoint", "POST /v1/measurements", Icons.Outlined.Sensors)
            InformationNote("Connection checks send no sensor data. Live results are recorded for evaluation, not fused into navigation. The remote model needs internet; GPS, local maps and recording do not. No on-device model is bundled.")
            if (BuildConfig.DEBUG) InformationNote("Emulator development: http://10.0.2.2:8765 reaches a server on your computer. Other servers require HTTPS.")
            Spacer(Modifier.height(24.dp))
        }
    }
}

@Composable
fun OfflineScreen(model: SetuViewModel) {
    MapRegionsScreen(model)
}

