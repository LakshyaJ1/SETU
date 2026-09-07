package com.setu.navigator

import android.graphics.Bitmap
import android.location.Location
import android.os.Build
import android.os.SystemClock
import androidx.core.location.LocationCompat
import androidx.compose.ui.test.*
import androidx.compose.ui.test.junit4.v2.createAndroidComposeRule
import androidx.compose.ui.semantics.SemanticsActions
import androidx.compose.ui.semantics.SemanticsProperties
import androidx.core.view.WindowCompat
import androidx.core.view.ViewCompat
import androidx.core.view.WindowInsetsCompat
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import androidx.lifecycle.ViewModelProvider
import com.setu.navigator.data.Trip
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith
import org.json.JSONObject
import java.io.File
import java.security.DigestInputStream
import java.security.MessageDigest

@RunWith(AndroidJUnit4::class)
class AndroidWorkflowTest {
    @get:Rule
    val compose = createAndroidComposeRule<MainActivity>()
    private val apkSha256 by lazy {
        val digest = MessageDigest.getInstance("SHA-256")
        DigestInputStream(File(compose.activity.packageCodePath).inputStream(), digest).use { input ->
            val buffer = ByteArray(65536)
            while (input.read(buffer) >= 0) { }
        }
        digest.digest().joinToString("") { "%02x".format(it) }
    }

    @Test
    fun offlineJourneyAndSettingsRemainUsable() {
        compose.onNodeWithTag("tab-Settings").performClick()
        compose.onNodeWithText("Appearance").performScrollTo().performClick()
        compose.onNodeWithTag("preference-option-Light").performClick()
        compose.onNodeWithTag("tab-Drive").performClick()
        compose.onNodeWithTag("destination-search").assertIsDisplayed()
        capture("01-home")
        compose.onNodeWithTag("destination-search").performClick()
        compose.onNodeWithTag("place-query").performTextInput("Cubbon")
        compose.onNodeWithTag("place-cubbon").assertIsDisplayed()
        capture("02-destination-search")
        compose.onNodeWithTag("place-cubbon").performClick()
        compose.waitUntil(20000) { compose.onAllNodesWithTag("start-drive").fetchSemanticsNodes().isNotEmpty() }
        compose.onNodeWithTag("start-drive").assertIsDisplayed()
        capture("03-route-preview")
        compose.onNodeWithContentDescription("Clear destination").performClick()
        compose.onNodeWithTag("open-demo").performClick()
        compose.waitUntil(20000) { compose.onAllNodesWithTag("replay-play-pause").fetchSemanticsNodes().isNotEmpty() }
        compose.onNodeWithTag("replay-play-pause").performClick()
        compose.onNodeWithContentDescription("Play replay").assertIsDisplayed()
        compose.onNodeWithTag("replay-timeline").performSemanticsAction(SemanticsActions.SetProgress) { it(0.5f) }
        check(compose.onNodeWithTag("replay-timeline").fetchSemanticsNode().config[SemanticsProperties.ProgressBarRangeInfo].current in 0.49f..0.51f)
        compose.onNodeWithText("Synthetic journey", substring = true).assertIsDisplayed()
        capture("04-synthetic-replay")
        compose.onNodeWithContentDescription("Exit replay").performClick()
        compose.onNodeWithTag("status-diagnostics").performClick()
        compose.onNodeWithText("Under the hood").assertExists()
        capture("05-diagnostics")
        compose.onNodeWithTag("verify-native-core").performScrollTo().performClick()
        compose.waitUntil(20000) { compose.onAllNodesWithText("Native check passed").fetchSemanticsNodes().isNotEmpty() }
        compose.onNodeWithTag("verify-native-core").performScrollTo()
        capture("24-native-core-check")
        compose.onNodeWithContentDescription("Back").performClick()
        compose.onNodeWithTag("tab-Record").performClick()
        compose.onNodeWithTag("record-toggle").assertIsDisplayed()
        capture("06-record-ready")
        compose.onNodeWithTag("tab-Trips").performClick()
        compose.onNodeWithTag("import-trip").assertIsDisplayed()
        capture("07-trips")
        compose.onNodeWithTag("tab-Settings").performClick()
        compose.onNodeWithText("Appearance").assertIsDisplayed()
        capture("08-settings")
        compose.onNodeWithText("Model integration").performScrollTo().performClick()
        compose.onNodeWithTag("model-endpoint").assertIsDisplayed()
        capture("09-model-boundary")
        compose.onNodeWithContentDescription("Back").performClick()
        compose.onNodeWithText("Offline area").performScrollTo().performClick()
        compose.onNodeWithTag("active-map-name").assertTextEquals("Bengaluru Central").assertIsDisplayed()
        capture("10-offline-area")
        compose.onNodeWithContentDescription("Back").performClick()
        compose.onNodeWithText("Appearance").performScrollTo().performClick()
        compose.onNodeWithTag("preference-option-Dark").performClick()
        compose.onNodeWithTag("tab-Drive").performClick()
        compose.onNodeWithTag("destination-search").assertIsDisplayed()
        compose.runOnUiThread {
            val view = compose.activity.window.decorView
            val insets = checkNotNull(ViewCompat.getRootWindowInsets(view)).getInsets(WindowInsetsCompat.Type.navigationBars())
            val buttonNavigation = maxOf(insets.bottom, insets.right) / view.resources.displayMetrics.density >= 40
            check(WindowCompat.getInsetsController(compose.activity.window, view).isAppearanceLightNavigationBars == buttonNavigation)
        }
        capture("11-home-dark")
        compose.onNodeWithTag("tab-Settings").performClick()
        compose.onNodeWithText("Appearance").performScrollTo().performClick()
        compose.onNodeWithTag("preference-option-Light").performClick()
    }

    @Test
    fun missingMeasuredAndStaleGpsStayDistinct() {
        val automation = InstrumentationRegistry.getInstrumentation().uiAutomation
        automation.grantRuntimePermission(BuildConfig.APPLICATION_ID, android.Manifest.permission.ACCESS_COARSE_LOCATION)
        automation.grantRuntimePermission(BuildConfig.APPLICATION_ID, android.Manifest.permission.ACCESS_FINE_LOCATION)
        val model = ViewModelProvider(compose.activity)[SetuViewModel::class.java]
        val previousSettings = model.settings.value
        val hub = model.repository.hub
        try {
            compose.runOnIdle {
                model.repository.updateSettings(previousSettings.copy(theme = "Light", units = "km/h"))
                model.refreshPermissions()
                hub.stop()
                model.overlay = "diagnostics"
            }
            fun deliver(measured: Boolean) = compose.runOnIdle {
                hub.onLocationChanged(Location("setu-test").apply {
                    latitude = 12.9810
                    longitude = 77.5968
                    elapsedRealtimeNanos = SystemClock.elapsedRealtimeNanos()
                    LocationCompat.setMock(this, true)
                    if (measured) { speed = 0f; bearing = 0f; accuracy = 5f; altitude = 0.0 }
                })
            }
            deliver(false)
            compose.onNodeWithText("Invalid timestamp").assertDoesNotExist()
            compose.onNodeWithTag("reading-Altitude (WGS84)").performScrollTo()
            listOf("GPS speed", "Course over ground", "GPS accuracy estimate", "Altitude (WGS84)").forEach { label ->
                compose.onNodeWithTag("reading-$label").assert(hasAnyDescendant(hasText("Not provided")))
            }
            compose.onNodeWithText("Test location · not live GPS").assertExists()
            capture("25-missing-gps-measurements", "Injected Android Location with mock flag; optional measurements absent; not live GPS")
            deliver(true)
            compose.onNodeWithTag("reading-Observation age").assert(hasAnyDescendant(hasText("Fresh fix")))
            compose.onNodeWithTag("reading-GPS speed").assert(hasAnyDescendant(hasText("0.0 km/h")))
            compose.onNodeWithTag("reading-Course over ground").assert(hasAnyDescendant(hasText("0°")))
            compose.onNodeWithTag("reading-GPS accuracy estimate").assert(hasAnyDescendant(hasText("±5 m")))
            capture("26-measured-zero-gps", "Injected mock Location with explicitly measured zero speed/course/altitude; not live GPS")
            Thread.sleep(3500)
            compose.onNodeWithContentDescription("Back").performClick()
            compose.waitUntil(10000) { compose.onAllNodesWithText("Last test fix").fetchSemanticsNodes().isNotEmpty() }
            capture("27-stale-gps-position", "Injected mock Location older than three seconds; no live positioning or heading")
            compose.runOnIdle {
                hub.onLocationChanged(Location("setu-test").apply {
                    latitude = 39.237255
                    longitude = -123.150032
                    elapsedRealtimeNanos = SystemClock.elapsedRealtimeNanos()
                    accuracy = 5f
                    LocationCompat.setMock(this, true)
                })
            }
            compose.onNodeWithTag("destination-search").performClick()
            compose.onNodeWithTag("place-cubbon").performClick()
            compose.waitUntil(20000) { compose.onAllNodesWithTag("start-drive").fetchSemanticsNodes().isNotEmpty() }
            compose.onNodeWithTag("start-drive").assertIsNotEnabled()
            compose.onNodeWithText("Outside offline area").assertIsDisplayed()
            compose.onNodeWithText("You can browse this preview, but cannot start a drive here.", substring = true).assertExists()
            check(model.routeOriginLabel == "MG Road preview")
            capture("28-outside-area-preview", "Injected mock GPS outside Bengaluru; labelled MG Road preview and disabled drive start; not live GPS")
        } finally {
            compose.runOnIdle {
                model.repository.updateSettings(previousSettings)
                hub.onProviderDisabled(android.location.LocationManager.GPS_PROVIDER)
                hub.start()
            }
        }
    }

    @Test
    fun liveNativePositioningConsumesAndroidSensorsAndRecordsSeparateOutput() {
        val automation = InstrumentationRegistry.getInstrumentation().uiAutomation
        automation.grantRuntimePermission(BuildConfig.APPLICATION_ID, android.Manifest.permission.ACCESS_COARSE_LOCATION)
        automation.grantRuntimePermission(BuildConfig.APPLICATION_ID, android.Manifest.permission.ACCESS_FINE_LOCATION)
        val model = ViewModelProvider(compose.activity)[SetuViewModel::class.java]
        val previousSettings = model.settings.value
        var recording: Trip? = null
        var ownsRecording = false
        try {
            compose.runOnIdle {
                model.repository.updateSettings(previousSettings.copy(theme = "Light", units = "mph", nativePositioning = false))
                model.refreshPermissions()
                model.overlay = "diagnostics"
            }
            compose.waitUntil(30000) {
                val estimate = model.nativeEstimate.value
                estimate.pairedSamples >= 100 && estimate.accepted >= 2 && estimate.currentPose(SystemClock.elapsedRealtimeNanos()) != null
            }
            compose.onNodeWithTag("native-positioning-toggle").performScrollTo().assertIsOff().performClick().assertIsOn()
            compose.onNodeWithTag("reading-95% filter radius").performScrollTo()
            compose.onNodeWithTag("reading-Native speed").assert(hasAnyDescendant(hasText("mph", substring = true)))
            capture("29-live-native-diagnostics", "Actual Android sensor/GPS callbacks in emulator; native filter and delayed corrections; not a physical road drive")
            compose.onNodeWithContentDescription("Back").performClick()
            compose.waitUntil(15000) { compose.onAllNodesWithText("GPS + IMU").fetchSemanticsNodes().isNotEmpty() }
            capture("30-live-native-map", "Opted-in native estimate selected by real application map from emulator sensors; no physical accuracy claim")
            compose.runOnIdle {
                check(!model.recording.value) { "The device already has an active recording" }
                model.repository.beginRecording("Native integration test")
                ownsRecording = true
            }
            Thread.sleep(5500)
            compose.onNodeWithTag("tab-Record").performClick()
            compose.onNodeWithText("Stop & save recording").assertIsDisplayed()
            capture("31-native-capture", "Foreground test capture of actual emulator sensors plus separately named native_pose records")
            compose.runOnIdle { recording = checkNotNull(model.repository.finishRecording()) }
            val records = model.repository.tripStore.logFile(checkNotNull(recording).id).useLines { lines -> lines.map(::JSONObject).toList() }
            val native = records.filter { it.optString("type") == "native_pose" }
            check(native.size >= 5)
            check(records.any { it.optString("type") == "pose" })
            check(records.any { it.optString("type") == "rotation_vector" })
            check(native.all { it.getBoolean("experimental") && it.getDouble("radius95Meters") > 0 })
            check(native.zipWithNext().all { (previous, current) -> previous.getLong("tNs") < current.getLong("tNs") })
        } finally {
            compose.runOnIdle {
                if (ownsRecording && model.recording.value) recording = model.repository.finishRecording()
                model.repository.updateSettings(previousSettings)
            }
            recording?.let { model.repository.tripStore.delete(it) }
            model.repository.refreshTrips()
        }
    }

    @Test
    fun regionalMapsInstallSwitchRouteRejectAndRemove() {
        val model = ViewModelProvider(compose.activity)[SetuViewModel::class.java]
        val previousSettings = model.settings.value
        val previousMap = model.activeMap.value.region.key
        val fixture = File(compose.activity.cacheDir, "ui-map-${java.util.UUID.randomUUID()}.setumap")
        var installedKey: String? = null
        check(!model.recording.value)
        check(model.regions.value.none { it.id == "verification-grid" }) { "Keep any pre-existing verification map untouched." }
        try {
            fixture.writeBytes(MapPackFixture.bytes())
            compose.runOnIdle {
                model.updateSettings(previousSettings.copy(theme = "Light"))
                model.repository.hub.stop()
                model.repository.hub.onProviderDisabled(android.location.LocationManager.GPS_PROVIDER)
                model.closeReplay()
                model.clearRoute()
                model.overlay = "offline"
                model.importMap(android.net.Uri.fromFile(fixture))
            }
            compose.waitUntil(20000) { !model.mapBusy }
            installedKey = model.regions.value.single { it.id == "verification-grid" }.key
            check(model.activeMap.value.region.key == previousMap)
            compose.onNodeWithTag("region-verification-grid-1").performScrollTo()
            capture("32-map-pack-installed", "Synthetic Verification Grid imported through the app document-stream handler; not active yet; not real map coverage")
            compose.onNodeWithTag("use-region-verification-grid-1").performScrollTo().performClick()
            compose.waitUntil(20000) { !model.mapBusy && model.activeMap.value.region.key == installedKey }
            compose.onNodeWithTag("active-map-name").assertTextEquals("Verification Grid").performScrollTo()
            capture("33-map-pack-active", "Imported synthetic Verification Grid selected; actual offline MapLibre rendering; not a real street map")
            compose.onNodeWithText("Explore this area").performScrollTo().performClick()
            compose.onNodeWithTag("destination-search").performClick()
            compose.onNodeWithTag("place-query").performTextInput("Test destination")
            compose.onNodeWithTag("place-test-destination").performClick()
            compose.waitUntil(20000) { !model.routeLoading && model.route != null }
            check(model.routeOriginLabel == "Test start preview")
            compose.onNodeWithTag("start-drive").assertIsNotEnabled()
            capture("34-map-pack-route", "Route computed from the imported synthetic graph and its named preview start; GPS withheld; start drive disabled")
            compose.runOnIdle { model.clearRoute(); model.openDemo() }
            compose.waitUntil(20000) { model.replayTrip != null }
            compose.runOnIdle { model.activateMap("bundled") }
            check(!model.mapBusy && model.activeMap.value.region.key == installedKey)
            check(model.mapMessage?.contains("Finish recording") == true)
            compose.runOnIdle { model.closeReplay(); model.overlay = "offline" }
            compose.onNodeWithTag("use-region-bengaluru-central-1").performScrollTo().performClick()
            compose.waitUntil(20000) { !model.mapBusy && model.activeMap.value.region.bundled }
            compose.onNodeWithTag("remove-region-verification-grid-1").performScrollTo().performClick()
            compose.onNodeWithText("Keep map").assertIsDisplayed()
            compose.onNodeWithText("Remove map").performClick()
            compose.waitUntil(20000) { !model.mapBusy && model.regions.value.none { it.key == installedKey } }
            compose.onNodeWithTag("map-operation-message").assertTextContains("Recordings are unchanged.", substring = true)
            capture("35-map-pack-removed", "Explicit removal of only the test-owned synthetic pack after switching back to included Bengaluru; recordings untouched")
            fixture.writeText("not a zip archive")
            compose.runOnIdle { model.importMap(android.net.Uri.fromFile(fixture)) }
            compose.waitUntil(20000) { !model.mapBusy }
            compose.onNodeWithTag("map-operation-message").assertTextContains("not a complete .setumap archive", substring = true)
            capture("36-map-pack-rejected", "Deliberately malformed test file rejected; included Bengaluru remains active")
        } finally {
            compose.runOnIdle { model.cancelMapOperation(); model.closeReplay(); model.clearRoute() }
            compose.waitUntil(20000) { !model.mapBusy }
            model.repository.mapPacks.activate(previousMap)
            installedKey?.let { key -> if (model.regions.value.any { it.key == key }) model.repository.mapPacks.remove(key) }
            fixture.delete()
            compose.runOnIdle {
                model.updateSettings(previousSettings)
                model.overlay = null
                model.repository.hub.onProviderDisabled(android.location.LocationManager.GPS_PROVIDER)
                model.repository.hub.start()
            }
        }
    }

    @Test
    fun presentationDemoShowsNativeLossRecoveryAndSurvivesRecreation() {
        val model = ViewModelProvider(compose.activity)[SetuViewModel::class.java]
        val previousSettings = model.settings.value
        val previousTrips = model.repository.tripStore.all().map { it.id }.toSet()
        check(!model.recording.value)
        try {
            compose.runOnIdle {
                model.closeReplay()
                model.clearRoute()
                model.overlay = null
                model.tab = "Drive"
                model.updateSettings(previousSettings.copy(theme = "Light"))
            }
            compose.onNodeWithTag("positioning-demo").performScrollTo().performClick()
            compose.waitUntil(60000) { model.positioningDemo != null }
            compose.onNodeWithTag("demo-phase-2000").performScrollTo().performClick()
            compose.onNodeWithTag("position-demo-stage").assertTextEquals("GPS + motion")
            capture("42-positioning-demo-lock", "Simulated GPS and IMU processed by the native engine; GPS-lock phase, not live sensor accuracy")
            compose.onNodeWithTag("demo-phase-10000").performScrollTo().performClick()
            compose.onNodeWithTag("position-demo-stage").assertTextEquals("GPS withheld · IMU tracking")
            check(model.positioningDemo!!.frameAt(10000).estimate.status == "Inertial estimate")
            compose.activityRule.scenario.recreate()
            compose.onNodeWithTag("position-demo-stage").assertTextEquals("GPS withheld · IMU tracking")
            check(!model.playing && model.replayPositionMs == 10000f)
            capture("43-positioning-demo-gap", "Native output while synthetic GPS is withheld; paused state restored after Activity recreation")
            compose.onNodeWithTag("demo-phase-18000").performScrollTo().performClick()
            compose.onNodeWithTag("position-demo-stage").assertTextEquals("GPS reacquired")
            capture("44-positioning-demo-recovery", "Native engine accepts synthetic GPS after the eight-second input gap")
            compose.runOnIdle { model.updateSettings(model.settings.value.copy(theme = "Dark")) }
            capture("45-positioning-demo-dark", "Dark-theme presentation demo; synthetic inputs, native output")
            compose.onNodeWithContentDescription("Exit replay").performClick()
            compose.onNodeWithTag("start-tracking").assertExists()
            check(model.positioningDemo == null)
            check(previousTrips == model.repository.tripStore.all().map { it.id }.toSet())
        } finally {
            compose.runOnIdle { model.closeReplay(); model.updateSettings(previousSettings) }
        }
    }

    @Test
    fun liveTrackingFollowsMockFixesRecordsAndSavesWithoutADestination() {
        val automation = InstrumentationRegistry.getInstrumentation().uiAutomation
        automation.grantRuntimePermission(BuildConfig.APPLICATION_ID, android.Manifest.permission.ACCESS_COARSE_LOCATION)
        automation.grantRuntimePermission(BuildConfig.APPLICATION_ID, android.Manifest.permission.ACCESS_FINE_LOCATION)
        if (Build.VERSION.SDK_INT >= 33) automation.grantRuntimePermission(BuildConfig.APPLICATION_ID, android.Manifest.permission.POST_NOTIFICATIONS)
        val model = ViewModelProvider(compose.activity)[SetuViewModel::class.java]
        val previousSettings = model.settings.value
        val previousTrips = model.repository.tripStore.all().map { it.id }.toSet()
        val handler = android.os.Handler(android.os.Looper.getMainLooper())
        var ownedTrip: Trip? = null
        var sequence = 0
        val locations = object : Runnable {
            override fun run() {
                model.repository.hub.onLocationChanged(Location("setu-demo-test").apply {
                    latitude = 12.9753 + sequence * 0.000002
                    longitude = 77.6067 + sequence * 0.00004
                    elapsedRealtimeNanos = SystemClock.elapsedRealtimeNanos()
                    time = System.currentTimeMillis()
                    speed = 6f
                    bearing = 87f
                    accuracy = 4f
                    LocationCompat.setMock(this, true)
                })
                sequence++
                handler.postDelayed(this, 750)
            }
        }
        var ownsRecording = false
        check(!model.recording.value)
        try {
            compose.runOnIdle {
                model.closeReplay()
                model.clearRoute()
                model.overlay = null
                model.tab = "Drive"
                model.updateSettings(previousSettings.copy(theme = "Light", nativePositioning = false))
                model.refreshPermissions()
            }
            compose.onNodeWithTag("start-tracking").performScrollTo().performClick()
            ownsRecording = true
            compose.waitUntil(15000) { model.recording.value }
            compose.runOnIdle { model.repository.hub.stop(); handler.post(locations) }
            compose.waitUntil(20000) { model.trackingTrail.size >= 5 }
            check(model.route == null && model.destination == null)
            check(model.trackingTrail.first().point.distanceTo(model.trackingTrail.last().point) > 10)
            compose.onNodeWithTag("tracking-source").assertTextEquals("Test location · recording locally")
            compose.onNodeWithTag("follow-position").performClick()
            val cameraTarget = java.util.concurrent.atomic.AtomicReference<org.maplibre.android.geometry.LatLng>()
            compose.runOnIdle {
                val views = java.util.ArrayDeque<android.view.View>()
                views.add(compose.activity.window.decorView)
                while (views.isNotEmpty()) {
                    val view = views.removeFirst()
                    if (view is org.maplibre.android.maps.MapView) view.getMapAsync { cameraTarget.set(it.cameraPosition.target) }
                    else if (view is android.view.ViewGroup) repeat(view.childCount) { views.add(view.getChildAt(it)) }
                }
            }
            compose.waitUntil(5000) { cameraTarget.get() != null }
            val camera = cameraTarget.get()
            check(com.setu.navigator.data.GeoPoint(camera.latitude, camera.longitude)
                .distanceTo(requireNotNull(model.navigationFix()).point) < 20)
            capture("46-live-position-trail", "Controlled mock Android locations exercise live following and foreground recording; not physical-device positioning accuracy")
            val beforeRecreation = model.trackingTrail.size
            compose.activityRule.scenario.recreate()
            compose.waitUntil(15000) { model.trackingTrail.size >= beforeRecreation }
            compose.onNodeWithTag("stop-tracking").performScrollTo().performClick()
            compose.waitUntil(15000) { !model.recording.value }
            val saved = model.repository.tripStore.all().single { it.id !in previousTrips }
            ownedTrip = saved
            check(saved.points.size >= 5)
            check(saved.points.any { it.mock == true })
            compose.onNodeWithTag("tab-Trips").assertIsSelected()
            compose.onNodeWithTag("trip-${saved.id}").performScrollTo().performClick()
            capture("47-tracked-journey-saved", "Recorded mock-location journey saved through the foreground service; retained user trips unchanged")
            compose.onNodeWithTag("replay-trip").performScrollTo().performClick()
            compose.onNodeWithTag("replay-play-pause").performClick()
            check(model.replayTrip?.id == saved.id && model.replayTrip?.synthetic == false)
            capture("49-tracked-journey-replay", "Saved controlled mock-location journey replayed through the user-facing Trips flow")
            compose.onNodeWithContentDescription("Exit replay").performClick()
            compose.runOnIdle { model.overlay = null; model.tab = "Record" }
            compose.onNodeWithText("No AI model required.", substring = true).assertDoesNotExist()
            compose.onNodeWithText("Capture motion, satellite measurements and your path in one synchronized recording.").assertExists()
            capture("48-record-presentation-copy", "Record screen uses presentation-ready acquisition copy; no model availability claim")
        } finally {
            handler.removeCallbacksAndMessages(null)
            compose.runOnIdle {
                if (ownsRecording && model.recording.value) ownedTrip = model.repository.finishRecording()
                model.updateSettings(previousSettings)
                model.overlay = null
                model.selectedTrip = null
                model.repository.hub.onProviderDisabled(android.location.LocationManager.GPS_PROVIDER)
                model.repository.hub.start()
            }
            ownedTrip?.let(model.repository.tripStore::delete)
            model.repository.refreshTrips()
        }
    }

    @Test
    fun sensorSubscriptionsCanBeRepeatedlyStoppedAndRestarted() {
        val automation = InstrumentationRegistry.getInstrumentation().uiAutomation
        automation.grantRuntimePermission(BuildConfig.APPLICATION_ID, android.Manifest.permission.ACCESS_COARSE_LOCATION)
        automation.grantRuntimePermission(BuildConfig.APPLICATION_ID, android.Manifest.permission.ACCESS_FINE_LOCATION)
        val model = ViewModelProvider(compose.activity)[SetuViewModel::class.java]
        check(!model.recording.value)
        try {
            repeat(8) {
                compose.runOnIdle { model.repository.hub.stop(); model.refreshPermissions() }
                compose.waitUntil(15000) { model.nativeEstimate.value.pairedSamples >= 20 }
                Thread.sleep(1100)
            }
        } finally {
            compose.runOnIdle { model.refreshPermissions() }
        }
    }

    private fun capture(name: String, scenario: String = "Application workflow on API 35 emulator") {
        compose.waitForIdle()
        compose.waitUntil(30000) { compose.onAllNodesWithTag("offline-map-loading").fetchSemanticsNodes().isEmpty() }
        Thread.sleep(1800)
        compose.waitForIdle()
        val instrumentation = InstrumentationRegistry.getInstrumentation()
        val image = checkNotNull(instrumentation.uiAutomation.takeScreenshot())
        val directory = File(instrumentation.targetContext.getExternalFilesDir(null), "verification").apply { mkdirs() }
        File(directory, "$name.png").outputStream().use { output ->
            check(image.compress(Bitmap.CompressFormat.PNG, 100, output))
        }
        image.recycle()
        val native = ViewModelProvider(compose.activity)[SetuViewModel::class.java].nativeEstimate.value
        File(directory, "$name.json").writeText(JSONObject()
            .put("capture", "$name.png").put("apkSha256", apkSha256)
            .put("version", BuildConfig.VERSION_NAME).put("device", Build.MODEL)
            .put("sdk", Build.VERSION.SDK_INT).put("deviceClockMs", System.currentTimeMillis())
            .put("fontScale", instrumentation.targetContext.resources.configuration.fontScale)
            .put("orientation", instrumentation.targetContext.resources.configuration.orientation)
            .put("scenario", scenario)
            .put("nativeStatus", native.status).put("pairedImuSamples", native.pairedSamples)
            .put("acceptedNativeFixes", native.accepted).put("delayedNativeCorrections", native.delayedCorrections)
            .put("source", "Android UiAutomation.takeScreenshot; unaltered PNG").toString(2))
    }
}
