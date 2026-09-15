package com.setu.navigator.ui

import android.app.Activity
import android.os.Build
import android.view.WindowManager
import androidx.activity.ComponentActivity
import androidx.activity.SystemBarStyle
import androidx.activity.enableEdgeToEdge
import androidx.activity.compose.BackHandler
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.outlined.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.ui.Modifier
import androidx.compose.ui.Alignment
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.StrokeCap
import androidx.compose.ui.graphics.toArgb
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.platform.LocalWindowInfo
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.setu.navigator.SetuViewModel
import com.setu.navigator.data.Trip
import kotlinx.coroutines.launch

@Composable
fun SetuApp(model: SetuViewModel, withLocationPermission: (() -> Unit) -> Unit) {
    val settings by model.settings.collectAsStateWithLifecycle()
    val recording by model.recording.collectAsStateWithLifecycle()
    val snackbar = remember { SnackbarHostState() }
    var exportTarget by remember { mutableStateOf<Trip?>(null) }
    var confirmEnd by remember { mutableStateOf(false) }
    val context = LocalContext.current
    val importFile = rememberLauncherForActivityResult(ActivityResultContracts.OpenDocument()) { uri -> uri?.let(model::importTrip) }
    val exportFile = rememberLauncherForActivityResult(ActivityResultContracts.CreateDocument("application/octet-stream")) { uri ->
        if (uri != null) exportTarget?.let { model.exportTrip(it, uri) }
    }
    val launchExport: (Trip) -> Unit = { trip -> exportTarget = trip; exportFile.launch("setu-${trip.id.take(8)}.setulog") }
    var trainingTargetId by rememberSaveable { mutableStateOf<String?>(null) }
    val trainingFile = rememberLauncherForActivityResult(ActivityResultContracts.CreateDocument("application/zip")) { uri ->
        if (uri != null) {
            val trip = model.trips.value.find { it.id == trainingTargetId }
            if (trip != null) model.exportTrainingTrip(trip, uri) else model.notify("Recording is not available. Open Trips and retry the export.")
        }
    }
    val launchTrainingExport: (Trip) -> Unit = { trip -> trainingTargetId = trip.id; trainingFile.launch("setu-training-${trip.id.take(8)}.zip") }
    LaunchedEffect(model) { model.messages.collect { snackbar.showSnackbar(it) } }
    DisposableEffect(settings.keepScreenOn, model.navigating, model.playing, recording, model.positioningDemo) {
        val window = (context as? Activity)?.window
        if (settings.keepScreenOn && (model.navigating || model.playing || recording || model.positioningDemo != null)) window?.addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
        else window?.clearFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
        onDispose { window?.clearFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON) }
    }
    BackHandler(model.overlay != null || model.replayTrip != null || model.route != null || model.tab != "Drive") {
        when {
            model.overlay != null -> model.overlay = null
            model.navigating -> confirmEnd = true
            model.replayTrip != null -> model.closeReplay()
            model.route != null -> model.clearRoute()
            else -> model.tab = "Drive"
        }
    }

    SetuTheme(settings.theme) {
        val dark = MaterialTheme.colorScheme.background.red < 0.3f
        val background = MaterialTheme.colorScheme.background.toArgb()
        val density = LocalDensity.current
        val navigationInsets = WindowInsets.navigationBars
        val navigationHeight = with(density) { navigationInsets.getBottom(this).toDp() }
        val buttonNavigation = navigationHeight >= 40.dp || with(density) { navigationInsets.getRight(this, androidx.compose.ui.unit.LayoutDirection.Ltr).toDp() >= 40.dp }
        val navigationBackground = if (buttonNavigation) ButtonNavigationBackground.toArgb() else background
        DisposableEffect(dark, background, navigationBackground, buttonNavigation, context) {
            val barStyle = if (dark) SystemBarStyle.dark(android.graphics.Color.TRANSPARENT)
                else SystemBarStyle.light(android.graphics.Color.TRANSPARENT, android.graphics.Color.TRANSPARENT)
            val navigationStyle = if (buttonNavigation) SystemBarStyle.light(navigationBackground, navigationBackground) else barStyle
            (context as? ComponentActivity)?.enableEdgeToEdge(barStyle, navigationStyle)
            (context as? Activity)?.window?.setBackgroundDrawable(android.graphics.drawable.ColorDrawable(navigationBackground))
            @Suppress("DEPRECATION")
            (context as? Activity)?.window?.navigationBarColor = navigationBackground
            if (Build.VERSION.SDK_INT >= 29) (context as? Activity)?.window?.isNavigationBarContrastEnforced = true
            onDispose { }
        }
        val expanded = with(LocalDensity.current) { LocalWindowInfo.current.containerSize.width.toDp() >= 840.dp }
        Surface(Modifier.fillMaxSize().windowInsetsPadding(WindowInsets.safeDrawing.only(WindowInsetsSides.Horizontal)), color = MaterialTheme.colorScheme.background) {
            Row {
                if (expanded && model.overlay == null) SetuNavigation(model, recording, rail = true)
                Scaffold(
                    modifier = Modifier.weight(1f),
                    contentWindowInsets = WindowInsets(0, 0, 0, 0),
                    bottomBar = { if (!expanded && model.overlay == null) SetuNavigation(model, recording) },
                    snackbarHost = { SnackbarHost(snackbar, Modifier.navigationBarsPadding()) },
                ) { padding ->
                    Box(Modifier.fillMaxSize().padding(padding)
                        .then(if (expanded || model.overlay != null) Modifier.navigationBarsPadding() else Modifier)) {
                        when (model.overlay) {
                            "search" -> DestinationSearch(model)
                            "diagnostics" -> DiagnosticsScreen(model)
                            "models" -> ModelSettingsScreen(model)
                            "offline" -> OfflineScreen(model)
                            "about" -> AboutScreen(model)
                            "trip" -> model.selectedTrip?.let { TripDetailScreen(model, it, launchExport, launchTrainingExport) }
                            else -> when (model.tab) {
                                "Drive" -> DriveScreen(model, withLocationPermission, dark, onFinish = { confirmEnd = true })
                                "Record" -> RecordScreen(model, withLocationPermission)
                                "Trips" -> TripsScreen(model, onImport = { importFile.launch(arrayOf("*/*")) })
                                "Settings" -> SettingsScreen(model)
                            }
                        }
                    }
                }
            }
            if (buttonNavigation && navigationHeight > 0.dp) Box(Modifier.fillMaxSize(), contentAlignment = Alignment.BottomCenter) {
                Spacer(Modifier.fillMaxWidth().height(navigationHeight).background(ButtonNavigationBackground))
            }
            if (confirmEnd) AlertDialog(
                onDismissRequest = { confirmEnd = false },
                title = { Text("Finish this drive?") },
                text = { Text("Your recording will be saved on this phone. You can replay or export it from Trips.") },
                confirmButton = { TextButton(onClick = { confirmEnd = false; model.endDrive() }) { Text("Finish & save") } },
                dismissButton = { TextButton(onClick = { confirmEnd = false }) { Text("Keep driving") } },
            )
        }
    }
}

@Composable
private fun SetuNavigation(model: SetuViewModel, recording: Boolean, rail: Boolean = false) {
    val items = listOf("Drive" to Icons.Outlined.Explore, "Record" to Icons.Outlined.RadioButtonChecked,
        "Trips" to Icons.Outlined.Route, "Settings" to Icons.Outlined.Tune)
    if (rail) NavigationRail(Modifier.fillMaxHeight().statusBarsPadding(), containerColor = MaterialTheme.colorScheme.surface) {
        Spacer(Modifier.height(16.dp))
        BridgeMark(Modifier.size(32.dp))
        Spacer(Modifier.height(32.dp))
        items.forEach { (label, icon) -> NavigationRailItem(
            selected = model.tab == label, onClick = { model.tab = label },
            icon = { Icon(icon, label) }, label = { Text(label) },
        ) }
    } else NavigationBar(containerColor = MaterialTheme.colorScheme.surface, tonalElevation = 0.dp) {
        items.forEach { (label, icon) -> NavigationBarItem(
            selected = model.tab == label, onClick = { model.tab = label },
            modifier = Modifier.testTag("tab-$label"),
            icon = { BadgedBox(badge = { if (label == "Record" && recording) Badge() }) { Icon(icon, contentDescription = null) } },
            label = { Text(label) },
            colors = NavigationBarItemDefaults.colors(indicatorColor = MaterialTheme.colorScheme.primaryContainer),
        ) }
    }
}

@Composable
fun BridgeMark(modifier: Modifier = Modifier) {
    val color = MaterialTheme.colorScheme.primary
    Canvas(modifier) {
        val width = size.width
        val height = size.height
        val stroke = width * 0.075f
        drawLine(color, Offset(width * 0.12f, height * 0.76f), Offset(width * 0.34f, height * 0.2f), stroke, StrokeCap.Round)
        drawLine(color, Offset(width * 0.34f, height * 0.2f), Offset(width * 0.5f, height * 0.64f), stroke, StrokeCap.Round)
        drawLine(color, Offset(width * 0.5f, height * 0.64f), Offset(width * 0.66f, height * 0.2f), stroke, StrokeCap.Round)
        drawLine(color, Offset(width * 0.66f, height * 0.2f), Offset(width * 0.88f, height * 0.76f), stroke, StrokeCap.Round)
        drawLine(color, Offset(width * 0.27f, height * 0.76f), Offset(width * 0.73f, height * 0.76f), stroke, StrokeCap.Round)
    }
}

@Composable
fun PageHeader(title: String, subtitle: String? = null, onBack: (() -> Unit)? = null, action: @Composable (() -> Unit)? = null) {
    Column(Modifier.statusBarsPadding().padding(horizontal = 24.dp).padding(top = 20.dp, bottom = 20.dp)) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            if (onBack != null) {
                IconButton(onClick = onBack, modifier = Modifier.offset(x = (-12).dp)) { Icon(Icons.Outlined.ArrowBack, "Back") }
                Spacer(Modifier.width(4.dp))
            }
            Text(title, style = if (onBack == null) MaterialTheme.typography.headlineMedium else MaterialTheme.typography.titleLarge, modifier = Modifier.weight(1f))
            action?.invoke()
        }
        if (subtitle != null) Text(subtitle, style = MaterialTheme.typography.bodyMedium,
            color = MaterialTheme.colorScheme.onSurfaceVariant, modifier = Modifier.padding(top = 8.dp))
    }
}

@Composable
fun SectionTitle(title: String, modifier: Modifier = Modifier) {
    Text(title, modifier = modifier.padding(top = 20.dp, bottom = 12.dp),
        style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.Bold)
}

@Composable
fun InformationNote(text: String, modifier: Modifier = Modifier) {
    Row(modifier.padding(vertical = 12.dp), horizontalArrangement = Arrangement.spacedBy(10.dp)) {
        Icon(Icons.Outlined.Info, null, Modifier.size(18.dp), tint = MaterialTheme.colorScheme.onSurfaceVariant)
        Text(text, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
    }
}
