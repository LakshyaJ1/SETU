package com.setu.navigator.ui

import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.outlined.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.setu.navigator.BuildConfig
import com.setu.navigator.SetuViewModel
import com.setu.navigator.data.MapRegion

@Composable
fun MapRegionsScreen(model: SetuViewModel) {
    val maps by model.activeMap.collectAsStateWithLifecycle()
    val regions by model.regions.collectAsStateWithLifecycle()
    val recording by model.recording.collectAsStateWithLifecycle()
    val locked = model.mapBusy || recording || model.navigating || model.replayTrip != null
    val dark = MaterialTheme.colorScheme.background.red < 0.3f
    var downloadOpen by rememberSaveable { mutableStateOf(false) }
    var address by rememberSaveable { mutableStateOf("") }
    var checksum by rememberSaveable { mutableStateOf("") }
    var remove by remember { mutableStateOf<MapRegion?>(null) }
    val scroll = rememberScrollState()
    LaunchedEffect(model.mapBusy, model.mapMessage) {
        if (model.mapBusy || model.mapMessage != null) scroll.animateScrollTo(0)
    }
    val importFile = rememberLauncherForActivityResult(ActivityResultContracts.OpenDocument()) { uri -> uri?.let(model::importMap) }

    Column(Modifier.fillMaxSize()) {
        PageHeader("A city in your pocket", "Your maps. Ready without a signal.", onBack = { model.overlay = null })
        Column(Modifier.weight(1f).verticalScroll(scroll).padding(horizontal = 24.dp)) {
            model.mapMessage?.let { message ->
                Surface(color = MaterialTheme.colorScheme.surfaceContainer, shape = SetuShape.control,
                    modifier = Modifier.fillMaxWidth().padding(bottom = 16.dp)) {
                    Text(message, Modifier.padding(16.dp).testTag("map-operation-message"), style = MaterialTheme.typography.bodyMedium)
                }
            }
            if (model.mapBusy) Column(Modifier.fillMaxWidth().padding(bottom = 16.dp)) {
                LinearProgressIndicator(Modifier.fillMaxWidth())
                Text(model.mapProgress ?: "Checking map…", Modifier.padding(top = 8.dp), style = MaterialTheme.typography.bodyMedium)
                TextButton(onClick = model::cancelMapOperation, modifier = Modifier.testTag("cancel-map-operation")) { Text("Cancel") }
            }
            Surface(shape = SetuShape.card, modifier = Modifier.fillMaxWidth().height(180.dp)) {
                NavigationMap(null, null, 0, dark, Modifier.fillMaxSize(), maps = maps)
            }
            Text(maps.region.name, Modifier.padding(top = 20.dp).testTag("active-map-name"), style = MaterialTheme.typography.headlineSmall)
            Text(maps.region.summary, Modifier.padding(top = 8.dp), style = MaterialTheme.typography.bodyMedium,
                color = MaterialTheme.colorScheme.onSurfaceVariant)
            ReadingRow("Active revision", maps.region.revision.toString(), Icons.Outlined.Layers)
            ReadingRow("Map and road graph", android.text.format.Formatter.formatShortFileSize(LocalContext.current, maps.sizeBytes), Icons.Outlined.Storage)
            ReadingRow("Source snapshot", maps.region.dataTimestamp.take(10), Icons.Outlined.Event)
            Text("${maps.region.source} · ${maps.region.license}", Modifier.padding(top = 12.dp), style = MaterialTheme.typography.bodySmall)
            Button(onClick = { model.overlay = null; model.tab = "Drive" }, modifier = Modifier.fillMaxWidth().padding(top = 16.dp).heightIn(min = 54.dp)) {
                Icon(Icons.Outlined.Explore, null); Spacer(Modifier.width(10.dp)); Text("Explore this area")
            }
            InformationNote("${maps.region.limitations} Data inside the coverage boundary is not a guarantee that every road is routable.")
            SectionTitle("On this phone")
            regions.forEach { region ->
                val active = region.key == maps.region.key
                Column(Modifier.fillMaxWidth().padding(vertical = 14.dp).testTag("region-${region.id}-${region.revision}")) {
                    Row(verticalAlignment = Alignment.Top, horizontalArrangement = Arrangement.spacedBy(12.dp)) {
                        Icon(if (active) Icons.Outlined.CheckCircle else Icons.Outlined.Map, null, tint = MaterialTheme.colorScheme.primary)
                        Column(Modifier.weight(1f)) {
                            Text(region.name, style = MaterialTheme.typography.titleMedium)
                            Text("Revision ${region.revision} · ${if (region.bundled) "Included" else "Imported"}${if (active) " · Active" else ""}",
                                Modifier.padding(top = 4.dp), style = MaterialTheme.typography.bodySmall)
                        }
                    }
                    Row(Modifier.fillMaxWidth().padding(top = 8.dp), horizontalArrangement = Arrangement.End) {
                        if (!active) TextButton(onClick = { model.activateMap(region.key) }, enabled = !locked,
                            modifier = Modifier.testTag("use-region-${region.id}-${region.revision}")) { Text("Use this map") }
                        if (!region.bundled) TextButton(onClick = { remove = region }, enabled = !locked && !active,
                            modifier = Modifier.testTag("remove-region-${region.id}-${region.revision}")) { Text("Remove") }
                    }
                    if (active && !region.bundled) Text("Select another map before removing this one.", style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant)
                }
                HorizontalDivider(color = MaterialTheme.colorScheme.outlineVariant)
            }
            SectionTitle("Add an offline area")
            if (recording || model.navigating || model.replayTrip != null) InformationNote("Finish your recording, navigation or replay before managing maps.")
            OutlinedButton(onClick = { importFile.launch(arrayOf("*/*")) }, enabled = !locked,
                modifier = Modifier.fillMaxWidth().heightIn(min = 52.dp).testTag("import-map-pack")) {
                Icon(Icons.Outlined.FileOpen, null); Spacer(Modifier.width(10.dp)); Text("Import a .setumap file")
            }
            TextButton(onClick = { downloadOpen = !downloadOpen }, enabled = !model.mapBusy, modifier = Modifier.testTag("show-map-download")) {
                Text(if (downloadOpen) "Hide download fields" else "Download from a trusted publisher")
            }
            if (downloadOpen) {
                Text("Use a direct HTTPS file URL and its separately published SHA-256. There is no hosted SETU map catalogue yet.", style = MaterialTheme.typography.bodySmall)
                OutlinedTextField(address, { address = it }, label = { Text("Map-pack URL") }, enabled = !locked,
                    singleLine = true, keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Uri),
                    modifier = Modifier.fillMaxWidth().padding(top = 12.dp).testTag("map-download-url"))
                OutlinedTextField(checksum, { checksum = it.trim() }, label = { Text("SHA-256 checksum") }, enabled = !locked,
                    minLines = 2, keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Ascii),
                    modifier = Modifier.fillMaxWidth().padding(top = 12.dp).testTag("map-download-checksum"))
                Button(onClick = { model.downloadMap(address, checksum) }, enabled = !locked && address.isNotBlank() && checksum.length == 64,
                    modifier = Modifier.fillMaxWidth().padding(top = 12.dp).heightIn(min = 52.dp).testTag("download-map-pack")) { Text("Download & verify") }
                if (BuildConfig.DEBUG) Text("Development builds also allow the local emulator server at 10.0.2.2.",
                    Modifier.padding(top = 8.dp), style = MaterialTheme.typography.bodySmall)
            }
            InformationNote("Imports are checked before installation and do not switch your active map. Verify the publisher yourself; checksums detect changed bytes, not trustworthy roads. Map management sends no trip or sensor data.")
            TextButton(onClick = { model.overlay = "about" }) { Text("Map attribution & licenses") }
            Spacer(Modifier.height(24.dp))
        }
    }
    remove?.let { region -> AlertDialog(onDismissRequest = { remove = null },
        title = { Text("Remove ${region.name}?") }, text = { Text("Revision ${region.revision} will be removed from this phone. Your recordings and other maps stay unchanged.") },
        confirmButton = { TextButton(onClick = { model.removeMap(region.key); remove = null }) { Text("Remove map") } },
        dismissButton = { TextButton(onClick = { remove = null }) { Text("Keep map") } }) }
}
