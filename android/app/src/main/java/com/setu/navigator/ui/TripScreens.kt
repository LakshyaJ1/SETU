package com.setu.navigator.ui

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
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.setu.navigator.SetuViewModel
import com.setu.navigator.data.*
import java.text.DateFormat
import java.util.Date

@Composable
fun TripsScreen(model: SetuViewModel, onImport: () -> Unit) {
    val trips by model.trips.collectAsStateWithLifecycle()
    Column(Modifier.fillMaxSize()) {
        PageHeader("Your drives", "Saved here. Ready to revisit.", action = {
            IconButton(onClick = onImport, enabled = !model.busy, modifier = Modifier.testTag("import-trip")) {
                Icon(Icons.Outlined.FileOpen, "Import a recording")
            }
        })
        if (model.busy) LinearProgressIndicator(Modifier.fillMaxWidth())
        if (trips.isEmpty()) Column(Modifier.fillMaxWidth().weight(1f).verticalScroll(rememberScrollState()).padding(32.dp),
            verticalArrangement = Arrangement.Center, horizontalAlignment = Alignment.CenterHorizontally) {
            Surface(shape = SetuShape.hero, color = MaterialTheme.colorScheme.primaryContainer) {
                Icon(Icons.Outlined.Route, null, Modifier.padding(26.dp).size(52.dp), tint = MaterialTheme.colorScheme.primary)
            }
            Text("Every drive has\na story.", Modifier.padding(top = 26.dp), style = MaterialTheme.typography.headlineMedium,
                textAlign = androidx.compose.ui.text.style.TextAlign.Center)
            Text("Record your first journey to replay its route and keep the original sensor data.",
                Modifier.padding(top = 12.dp, bottom = 24.dp), style = MaterialTheme.typography.bodyMedium,
                color = MaterialTheme.colorScheme.onSurfaceVariant, textAlign = androidx.compose.ui.text.style.TextAlign.Center)
            Button(onClick = { model.tab = "Record" }, modifier = Modifier.fillMaxWidth().heightIn(min = 54.dp), shape = SetuShape.action) {
                Icon(Icons.Outlined.RadioButtonChecked, null, Modifier.size(19.dp)); Spacer(Modifier.width(8.dp)); Text("Record a drive")
            }
            OutlinedButton(onClick = onImport, enabled = !model.busy, modifier = Modifier.fillMaxWidth().padding(top = 10.dp).heightIn(min = 52.dp), shape = SetuShape.action) {
                Text("Import a recording")
            }
            TextButton(onClick = model::openDemo, Modifier.padding(top = 8.dp)) { Text("Explore a sample replay") }
        } else Column(Modifier.weight(1f).verticalScroll(rememberScrollState()).padding(horizontal = 24.dp)) {
            Row(Modifier.fillMaxWidth().padding(bottom = 20.dp), horizontalArrangement = Arrangement.spacedBy(24.dp)) {
                Metric("Recordings", trips.size.toString(), Modifier.weight(1f))
                Metric("Distance", distanceLabel(trips.sumOf { it.distanceMeters }), Modifier.weight(1f))
            }
            trips.forEach { trip ->
                ListItem(headlineContent = { Text(trip.name, fontWeight = FontWeight.SemiBold) },
                    supportingContent = {
                        Text("${DateFormat.getDateInstance(DateFormat.MEDIUM).format(Date(trip.startedAtMs))} · ${DateFormat.getTimeInstance(DateFormat.SHORT).format(Date(trip.startedAtMs))}\n${durationLabel(trip.durationMs)} · ${distanceLabel(trip.distanceMeters)}${if (trip.recovered) " · Recovered" else ""}")
                    }, leadingContent = {
                        Surface(shape = SetuShape.action, color = MaterialTheme.colorScheme.primaryContainer) {
                            Icon(Icons.Outlined.Route, null, Modifier.padding(14.dp), tint = MaterialTheme.colorScheme.primary)
                        }
                    }, trailingContent = { Icon(Icons.Outlined.ChevronRight, null) },
                    modifier = Modifier.clickable { model.selectedTrip = trip; model.overlay = "trip" }.testTag("trip-${trip.id}"),
                    colors = ListItemDefaults.colors(containerColor = Color.Transparent))
                HorizontalDivider(color = MaterialTheme.colorScheme.outlineVariant)
            }
            InformationNote("Only recordings on this phone appear here. Nothing is uploaded automatically.")
        }
    }
}

@Composable
fun TripDetailScreen(model: SetuViewModel, trip: Trip, onExport: (Trip) -> Unit, onTrainingExport: (Trip) -> Unit = {}) {
    var confirmDelete by remember { mutableStateOf(false) }
    var confirmTrainingExport by remember { mutableStateOf(false) }
    val recording by model.recording.collectAsStateWithLifecycle()
    val hasEstimates = trip.points.any { it.filterRadius95Meters != null }
    val dark = MaterialTheme.colorScheme.background.red < 0.3f
    Column(Modifier.fillMaxSize().verticalScroll(rememberScrollState()).navigationBarsPadding()) {
        PageHeader("Drive details", onBack = { model.overlay = null }, action = {
            IconButton(onClick = { confirmDelete = true }) { Icon(Icons.Outlined.DeleteOutline, "Delete this recording") }
        })
        Column(Modifier.padding(horizontal = 24.dp)) {
            Text(trip.name, style = MaterialTheme.typography.headlineMedium)
            Text(DateFormat.getDateTimeInstance(DateFormat.MEDIUM, DateFormat.SHORT).format(Date(trip.startedAtMs)),
                Modifier.padding(top = 8.dp, bottom = 20.dp), style = MaterialTheme.typography.bodyMedium, color = MaterialTheme.colorScheme.onSurfaceVariant)
            if (trip.points.size >= 2) Surface(shape = SetuShape.card, modifier = Modifier.height(240.dp).fillMaxWidth()) {
                val maps by model.activeMap.collectAsStateWithLifecycle()
                NavigationMap(DriveRoute(trip.points.map { it.point }, trip.distanceMeters, emptyList()), trip.points.last(), 0, dark, Modifier.fillMaxSize(), maps = maps,
                    recordedPath = trip.points)
            } else Surface(shape = SetuShape.card, color = MaterialTheme.colorScheme.surfaceContainer) {
                Column(Modifier.fillMaxWidth().padding(24.dp), horizontalAlignment = Alignment.CenterHorizontally) {
                    Icon(Icons.Outlined.LocationOff, null, Modifier.size(36.dp))
                    Text("No position path to draw", Modifier.padding(top = 12.dp), style = MaterialTheme.typography.titleMedium)
                    Text("The raw sensor recording is still available to export.", Modifier.padding(top = 8.dp), style = MaterialTheme.typography.bodyMedium)
                }
            }
            Row(Modifier.padding(top = 24.dp, bottom = 8.dp), horizontalArrangement = Arrangement.spacedBy(24.dp)) {
                Metric("Duration", durationLabel(trip.durationMs), Modifier.weight(1f))
                Metric(if (hasEstimates) "Estimated distance" else "Distance", distanceLabel(trip.distanceMeters), Modifier.weight(1f))
            }
            ReadingRow("Timestamped records", "%,d".format(trip.sampleCount), Icons.Outlined.GraphicEq)
            ReadingRow(if (hasEstimates) "GPS + sensor positions" else "GPS positions", "%,d".format(trip.points.size), Icons.Outlined.GpsFixed)
            ReadingRow("Data source", if (trip.synthetic) "Synthetic sample" else "Recorded sensors", Icons.Outlined.FolderOpen)
            if (trip.recovered) InformationNote("Recovered after an interrupted recording. Only complete records can be replayed or exported.")
            Button(onClick = { model.playTrip(trip) }, enabled = trip.points.size >= 2,
                modifier = Modifier.fillMaxWidth().padding(top = 20.dp).heightIn(min = 54.dp).testTag("replay-trip"), shape = SetuShape.action) {
                Icon(Icons.Outlined.PlayArrow, null); Spacer(Modifier.width(8.dp)); Text("Replay drive")
            }
            OutlinedButton(onClick = { onExport(trip) }, modifier = Modifier.fillMaxWidth().padding(top = 10.dp).heightIn(min = 52.dp).testTag("export-trip"), shape = SetuShape.action) {
                Icon(Icons.Outlined.IosShare, null, Modifier.size(18.dp)); Spacer(Modifier.width(8.dp)); Text("Export original recording")
            }
            InformationNote("Export includes raw sensors, precise GPS observations and any sensor-estimated trajectory. Share only with someone you trust. Gaps are not interpolated; path distance is not a validated odometer reading.")
            OutlinedButton(onClick = { confirmTrainingExport = true }, enabled = !model.busy && !recording && !trip.synthetic,
                modifier = Modifier.fillMaxWidth().heightIn(min = 52.dp).testTag("export-training"), shape = SetuShape.action) {
                Text(if (model.busy) "Preparing training data…" else "Export training bundle")
            }
            Text("Full-rate sensors, a 1-second comparison and a separate GPS-withheld replay. GPS stays a noisy reference, not exact truth.",
                style = MaterialTheme.typography.bodySmall, modifier = Modifier.padding(top = 8.dp))
            model.trainingExportSummary?.let { InformationNote(it) }
            Spacer(Modifier.height(16.dp))
        }
    }
    if (confirmTrainingExport) AlertDialog(onDismissRequest = { confirmTrainingExport = false },
        title = { Text("Export location and sensor data?") },
        text = { Text("This ZIP contains your precise route, timestamps, device details and a random installation ID. Choose a trusted storage location. Nothing is uploaded automatically. Preparing the replay can take a few minutes; keep SETU open.") },
        confirmButton = { TextButton(onClick = { confirmTrainingExport = false; onTrainingExport(trip) }) { Text("Choose location") } },
        dismissButton = { TextButton(onClick = { confirmTrainingExport = false }) { Text("Cancel") } })
    if (confirmDelete) AlertDialog(onDismissRequest = { confirmDelete = false },
        title = { Text("Delete this recording?") },
        text = { Text("“${trip.name}” and its original sensor log will be removed from this phone. This cannot be undone.") },
        confirmButton = { TextButton(onClick = { confirmDelete = false; model.deleteTrip(trip) }) { Text("Delete", color = MaterialTheme.colorScheme.error) } },
        dismissButton = { TextButton(onClick = { confirmDelete = false }) { Text("Keep recording") } })
}

@Composable
fun Metric(label: String, value: String, modifier: Modifier = Modifier) {
    Column(modifier) {
        Text(value, style = MaterialTheme.typography.headlineSmall)
        Text(label, Modifier.padding(top = 4.dp), style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
    }
}
