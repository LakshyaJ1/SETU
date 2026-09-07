package com.setu.navigator.ui

import android.content.Intent
import android.net.Uri
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
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.setu.navigator.BuildConfig
import com.setu.navigator.SetuViewModel

@Composable
fun SettingsScreen(model: SetuViewModel) {
    val settings by model.settings.collectAsStateWithLifecycle()
    val maps by model.activeMap.collectAsStateWithLifecycle()
    var choice by remember { mutableStateOf<String?>(null) }
    Column(Modifier.fillMaxSize().verticalScroll(rememberScrollState())) {
        PageHeader("Make it yours", "A few preferences. A lot of open road.")
        Column(Modifier.padding(horizontal = 24.dp)) {
            Surface(shape = RoundedCornerShape(20.dp), color = MaterialTheme.colorScheme.primaryContainer,
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
            SectionTitle("On the road")
            PreferenceRow("Appearance", settings.theme, Icons.Outlined.Palette) { choice = "Appearance" }
            PreferenceRow("Speed units", settings.units, Icons.Outlined.Speed) { choice = "Speed units" }
            PreferenceRow("Vehicle", settings.vehicle, Icons.Outlined.DirectionsCar) { choice = "Vehicle" }
            ListItem(headlineContent = { Text("Keep screen awake") }, supportingContent = { Text("During navigation and replay") },
                leadingContent = { Icon(Icons.Outlined.WbSunny, null) },
                trailingContent = { Switch(settings.keepScreenOn, { model.updateSettings(settings.copy(keepScreenOn = it)) }) },
                colors = ListItemDefaults.colors(containerColor = Color.Transparent))
            SectionTitle("Tools & trust")
            PreferenceRow("Device diagnostics", "Sensors, GPS and capability tier", Icons.Outlined.GraphicEq) { model.overlay = "diagnostics" }
            PreferenceRow("Model integration", model.modelConnection.status, Icons.Outlined.Cable) { model.overlay = "models" }
            PreferenceRow("Offline area", "Map coverage and attribution", Icons.Outlined.OfflinePin) { model.overlay = "offline" }
            PreferenceRow("About SETU", "Version ${BuildConfig.VERSION_NAME}", Icons.Outlined.Info) { model.overlay = "about" }
            InformationNote("No account. No automatic uploads. Your drive logs stay on this phone until you choose to export them.")
            Spacer(Modifier.height(20.dp))
        }
    }
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
    Column(Modifier.fillMaxSize().verticalScroll(rememberScrollState()).navigationBarsPadding()) {
        PageHeader("Model integration", "A clean handoff to your AI/ML teammate.", onBack = { model.overlay = null })
        Column(Modifier.padding(horizontal = 24.dp)) {
            Surface(shape = RoundedCornerShape(20.dp), color = MaterialTheme.colorScheme.surfaceContainer) {
                Column(Modifier.fillMaxWidth().padding(20.dp)) {
                    Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                        Icon(Icons.Outlined.Cable, null)
                        Text(connection.status, style = MaterialTheme.typography.titleLarge)
                    }
                    Text(connection.detail, Modifier.padding(top = 12.dp), style = MaterialTheme.typography.bodyMedium)
                    connection.modelName?.let { Text(it, Modifier.padding(top = 8.dp), style = MaterialTheme.typography.labelMedium) }
                }
            }
            SectionTitle("Development server")
            Text("Connect a server that implements the SETU model v1 contract. Maps, recording and replay do not depend on it.",
                style = MaterialTheme.typography.bodyMedium, color = MaterialTheme.colorScheme.onSurfaceVariant)
            OutlinedTextField(endpoint, { endpoint = it }, label = { Text("Model-server URL") }, placeholder = { Text("https://your-model-server") },
                singleLine = true, shape = RoundedCornerShape(16.dp),
                modifier = Modifier.fillMaxWidth().padding(top = 20.dp).testTag("model-endpoint"))
            Button(onClick = { model.updateSettings(settings.copy(modelEndpoint = endpoint)); model.checkModel() },
                enabled = endpoint.isNotBlank() && !connection.checking,
                modifier = Modifier.fillMaxWidth().padding(top = 14.dp).heightIn(min = 54.dp).testTag("check-model"), shape = RoundedCornerShape(16.dp)) {
                if (connection.checking) { CircularProgressIndicator(Modifier.size(18.dp), strokeWidth = 2.dp); Spacer(Modifier.width(10.dp)) }
                Text(if (connection.checking) "Checking connection…" else "Save & check connection")
            }
            SectionTitle("What the handoff includes")
            ReadingRow("Protocol", "setu.model.v1", Icons.Outlined.DataObject)
            ReadingRow("Health endpoint", "GET /v1/health", Icons.Outlined.MonitorHeart)
            ReadingRow("Measurement endpoint", "POST /v1/measurements", Icons.Outlined.Sensors)
            InformationNote("Connection checks send no sensor data. Inference remains disconnected until the team's provider is integrated with the navigation core. No trained model is bundled.")
            if (BuildConfig.DEBUG) InformationNote("Emulator development: http://10.0.2.2:8765 reaches a server on your computer. Other servers require HTTPS.")
            Spacer(Modifier.height(24.dp))
        }
    }
}

@Composable
fun OfflineScreen(model: SetuViewModel) {
    MapRegionsScreen(model)
}

@Composable
fun AboutScreen(model: SetuViewModel) {
    val context = LocalContext.current
    val maps by model.activeMap.collectAsStateWithLifecycle()
    Column(Modifier.fillMaxSize().verticalScroll(rememberScrollState()).navigationBarsPadding()) {
        PageHeader("The bridge, explained", onBack = { model.overlay = null })
        Column(Modifier.padding(horizontal = 24.dp)) {
            BridgeMark(Modifier.size(64.dp))
            Text("SETU", Modifier.padding(top = 16.dp), style = MaterialTheme.typography.displaySmall)
            Text("Seamless Egomotion Tracking under Unavailable-GNSS", Modifier.padding(top = 12.dp), style = MaterialTheme.typography.bodyLarge)
            Text("Version ${BuildConfig.VERSION_NAME} · Android development build", Modifier.padding(top = 12.dp), style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant)
            SectionTitle("Honest by design")
            Text("This development build includes GPS, experimental native GPS/IMU positioning, local recording, offline map packs and replay. Signal frontends, road matching and AI/ML consumption remain in progress. A synthetic replay does not demonstrate positioning accuracy.", style = MaterialTheme.typography.bodyMedium)
            SectionTitle("Your data stays yours")
            Text("There is no account, advertising SDK or automatic trajectory upload. Recording requires a deliberate start. Export includes precise location and raw sensor readings; the system file picker lets you choose where they go.", style = MaterialTheme.typography.bodyMedium)
            SectionTitle("Map credits")
            Text("Active area: ${maps.region.name}. ${maps.region.source} · ${maps.region.license}.", style = MaterialTheme.typography.bodyMedium)
            TextButton(onClick = { context.startActivity(Intent(Intent.ACTION_VIEW, Uri.parse(maps.region.sourceUrl))) }) { Text("Active map source & license") }
            Text("© OpenStreetMap contributors · Open Database License (ODbL) 1.0. Rendering by MapLibre Native. Bundled Noto Sans glyphs are supplied through OpenFreeMap.", style = MaterialTheme.typography.bodyMedium)
            TextButton(onClick = { context.startActivity(Intent(Intent.ACTION_VIEW, Uri.parse("https://www.openstreetmap.org/copyright"))) }) { Text("OpenStreetMap attribution") }
            TextButton(onClick = { context.startActivity(Intent(Intent.ACTION_VIEW, Uri.parse("https://maplibre.org/"))) }) { Text("MapLibre project") }
            Spacer(Modifier.height(24.dp))
        }
    }
}
