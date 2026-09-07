package com.setu.navigator

import android.graphics.RectF
import android.os.Debug
import android.os.SystemClock
import android.view.WindowManager
import androidx.activity.ComponentActivity
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.runtime.mutableStateOf
import androidx.compose.ui.Modifier
import androidx.compose.ui.test.onAllNodesWithTag
import androidx.compose.ui.test.junit4.v2.createAndroidComposeRule
import androidx.test.ext.junit.runners.AndroidJUnit4
import com.setu.navigator.data.MapPackStore
import com.setu.navigator.data.OfflineMap
import com.setu.navigator.ui.NavigationMap
import com.setu.navigator.ui.SetuTheme
import org.json.JSONArray
import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith
import org.maplibre.android.camera.CameraUpdateFactory
import org.maplibre.android.geometry.LatLng
import org.maplibre.android.maps.MapLibreMap
import org.maplibre.android.style.sources.VectorSource
import java.io.File
import java.util.concurrent.atomic.AtomicReference

@RunWith(AndroidJUnit4::class)
class MapRenderingTest {
    @get:Rule val compose = createAndroidComposeRule<ComponentActivity>()

    @Test
    fun ncrTilesRenderAcrossZoomsAndRepeatedMapDisposalWithoutHeapGrowth() {
        val context = compose.activity
        val region = MapPackStore(context).regions.value.single { it.id == "delhi" }
        val maps = OfflineMap(context, region)
        val mounted = mutableStateOf(true)
        val dark = mutableStateOf(false)
        val currentMap = AtomicReference<MapLibreMap?>()
        val measurements = JSONArray()
        compose.runOnUiThread { context.window.addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON) }
        compose.setContent {
            SetuTheme(if (dark.value) "Dark" else "Light") {
                if (mounted.value) NavigationMap(null, null, 0, dark.value,
                    Modifier.fillMaxSize(), maps = maps, onReady = { currentMap.set(it) })
            }
        }
        fun waitForRoads() {
            compose.waitUntil(45000) {
                var rendered = false
                if (compose.onAllNodesWithTag("offline-map-ready").fetchSemanticsNodes().isNotEmpty()) compose.runOnUiThread {
                    currentMap.get()?.let { map ->
                        val bounds = RectF(0f, 0f, context.window.decorView.width.toFloat(), context.window.decorView.height.toFloat())
                        rendered = map.style?.getSourceAs<VectorSource>("city") != null &&
                            map.queryRenderedFeatures(bounds, "roads", "main-roads").isNotEmpty()
                    }
                }
                rendered
            }
        }
        val started = SystemClock.elapsedRealtime()
        waitForRoads()
        val coldLoadMs = SystemClock.elapsedRealtime() - started
        val points = listOf(LatLng(28.6773, 77.2860), LatLng(28.7196, 77.0662), LatLng(28.5706, 77.3272),
            LatLng(28.6711, 77.4120), LatLng(28.9963, 77.7062), LatLng(28.4595, 77.0266))
        points.forEachIndexed { index, point ->
            compose.runOnUiThread { currentMap.get()!!.moveCamera(CameraUpdateFactory.newLatLngZoom(point, 14.0)) }
            waitForRoads()
            compose.runOnUiThread { currentMap.get()!!.moveCamera(CameraUpdateFactory.newLatLngZoom(point, 9.0)) }
            waitForRoads()
            compose.runOnUiThread { dark.value = !dark.value }
            waitForRoads()
            compose.runOnUiThread { mounted.value = false; currentMap.set(null) }
            compose.waitForIdle()
            Runtime.getRuntime().gc()
            SystemClock.sleep(300)
            val memory = Debug.MemoryInfo().also { Debug.getMemoryInfo(it) }
            measurements.put(JSONObject().put("cycle", index).put("pssKiB", memory.totalPss)
                .put("nativeBytes", Debug.getNativeHeapAllocatedSize()))
            assertTrue("Map renderer memory is not bounded: ${memory.totalPss} KiB", memory.totalPss < 700 * 1024)
            compose.runOnUiThread { mounted.value = true }
            waitForRoads()
        }
        compose.runOnUiThread { mounted.value = false; currentMap.set(null) }
        compose.waitForIdle()
        Runtime.getRuntime().gc()
        SystemClock.sleep(12000)
        val directory = File(context.getExternalFilesDir(null), "verification").apply { mkdirs() }
        File(directory, "map-rendering-stability.json").writeText(JSONObject()
            .put("scenario", "Real offline NCR vector tiles, six location/zoom/theme/disposal cycles; no sensor accuracy claim")
            .put("coldLoadMs", coldLoadMs).put("cycles", measurements).put("finalizerObservationMs", 12000).toString(2))
    }
}
