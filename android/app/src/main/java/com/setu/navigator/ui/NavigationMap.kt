package com.setu.navigator.ui

import android.graphics.Bitmap
import android.graphics.Canvas
import android.graphics.Paint
import android.graphics.Path
import android.graphics.RectF
import androidx.compose.foundation.layout.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.Alignment
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.unit.dp
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.viewinterop.AndroidView
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.LifecycleEventObserver
import androidx.lifecycle.compose.LocalLifecycleOwner
import com.setu.navigator.data.*
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import org.json.JSONArray
import org.json.JSONObject
import org.maplibre.android.camera.CameraPosition
import org.maplibre.android.camera.CameraUpdateFactory
import org.maplibre.android.geometry.LatLng
import org.maplibre.android.geometry.LatLngBounds
import org.maplibre.android.maps.MapLibreMap
import org.maplibre.android.maps.MapLibreMapOptions
import org.maplibre.android.maps.MapView
import org.maplibre.android.maps.Style
import org.maplibre.android.style.expressions.Expression
import org.maplibre.android.style.layers.*
import org.maplibre.android.style.layers.PropertyFactory.*
import org.maplibre.android.style.sources.GeoJsonSource
import kotlin.math.*

@Composable
fun NavigationMap(
    route: DriveRoute?, pose: Pose?, bottomInset: Int, dark: Boolean,
    modifier: Modifier = Modifier, maps: OfflineMap, reserveControls: Boolean = false, originLabel: String = "Start", onReady: (MapLibreMap) -> Unit = {},
) {
    val context = LocalContext.current
    val density = LocalDensity.current.density
    val lifecycle = LocalLifecycleOwner.current.lifecycle
    val mapView = remember { MapView(context, MapLibreMapOptions.createFromAttributes(context).textureMode(true)).apply { onCreate(null) } }
    var nativeMap by remember { mutableStateOf<MapLibreMap?>(null) }
    var styleReady by remember { mutableStateOf(false) }
    var mapRendered by remember { mutableStateOf(false) }
    var mapError by remember { mutableStateOf<String?>(null) }
    var reload by remember { mutableIntStateOf(0) }
    var styleGeneration by remember { mutableIntStateOf(0) }
    val json = remember(dark) {
        val source = context.assets.open("map-style.json").bufferedReader().use { it.readText() }
        if (!dark) source else source.replace("#EDF0E7", "#15231C")
            .replace("#D7E3B5", "#283D29").replace("#C8D8A1", "#35472F")
            .replace("#B5D5DC", "#254552").replace("#DFE3D8", "#203229")
            .replace("#D5DBCF", "#2D4134").replace("#D3DBCC", "#314638")
            .replace("#FCFDF8", "#3B5040").replace("#FFFFF9", "#566447")
            .replace("#BDCEA1", "#465C35").replace("#67715E", "#C2CAB7")
            .replace("#F8FAF2", "#1D2B22").replace("#657D45", "#B2C490")
            .replace("#DFE9C7", "#283D29")
    }

    DisposableEffect(mapView, lifecycle) {
        mapView.onStart()
        mapView.onResume()
        val observer = LifecycleEventObserver { _, event ->
            when (event) {
                Lifecycle.Event.ON_START -> mapView.onStart()
                Lifecycle.Event.ON_RESUME -> mapView.onResume()
                Lifecycle.Event.ON_PAUSE -> mapView.onPause()
                Lifecycle.Event.ON_STOP -> mapView.onStop()
                else -> Unit
            }
        }
        lifecycle.addObserver(observer)
        onDispose {
            lifecycle.removeObserver(observer)
            mapView.onPause()
            mapView.onStop()
            mapView.onDestroy()
        }
    }

    DisposableEffect(mapView, nativeMap) {
        val listener = MapView.OnDidFinishRenderingFrameListener { _, _, _ ->
            if (styleReady && !mapRendered) {
                val bounds = RectF(0f, 0f, mapView.width.toFloat(), mapView.height.toFloat())
                if (nativeMap?.queryRenderedFeatures(bounds, "roads", "parks", "water", "buildings", "journey-line", "vehicle-marker", "position-without-heading")?.isNotEmpty() == true) mapRendered = true
            }
        }
        mapView.addOnDidFinishRenderingFrameListener(listener)
        onDispose { mapView.removeOnDidFinishRenderingFrameListener(listener) }
    }

    Box(modifier) {
      AndroidView(
        factory = {
            mapView.apply {
                getMapAsync { map ->
                    nativeMap = map
                    map.uiSettings.isCompassEnabled = false
                    map.uiSettings.isLogoEnabled = false
                    map.uiSettings.isAttributionEnabled = false
                    map.uiSettings.isRotateGesturesEnabled = false
                    map.cameraPosition = CameraPosition.Builder().target(LatLng(maps.center.latitude, maps.center.longitude)).zoom(14.4).build()
                    onReady(map)
                }
            }
        },
        modifier = Modifier.fillMaxSize().testTag(if (mapRendered) "offline-map-ready" else "offline-map-loading")
            .semantics { contentDescription = "Offline map of ${maps.region.name}. Use destination search to plan a route." },
      )
      if (!mapRendered) Surface(Modifier.fillMaxSize(), color = MaterialTheme.colorScheme.surfaceContainer) {
          Column(Modifier.fillMaxSize(), verticalArrangement = Arrangement.Center, horizontalAlignment = Alignment.CenterHorizontally) {
              if (mapError == null) CircularProgressIndicator(Modifier.size(28.dp), strokeWidth = 3.dp)
              Text(mapError ?: "Preparing your offline map…", Modifier.padding(16.dp), style = MaterialTheme.typography.bodyMedium)
              if (mapError != null) TextButton(onClick = { reload++ }) { Text("Try again") }
          }
      }
    }

    LaunchedEffect(nativeMap, json, reload, maps) {
        val map = nativeMap ?: return@LaunchedEffect
        val generation = ++styleGeneration
        styleReady = false
        mapRendered = false
        mapError = null
        val city = try {
            withContext(Dispatchers.IO) { maps.cityJson() }
        } catch (error: java.io.IOException) {
            mapError = "The active map could not be opened. Try again or select another offline area."
            return@LaunchedEffect
        }
        withContext(Dispatchers.Main.immediate) {
          map.cameraPosition = CameraPosition.Builder().target(LatLng(maps.center.latitude, maps.center.longitude)).zoom(14.4).build()
          map.setStyle(Style.Builder().fromJson(json)) { style ->
            if (generation != styleGeneration) return@setStyle
            style.getSourceAs<GeoJsonSource>("city")?.setGeoJson(city)
            style.addSource(GeoJsonSource("journey", emptyFeatures()))
            style.addSource(GeoJsonSource("uncertainty", emptyFeatures()))
            style.addSource(GeoJsonSource("vehicle", emptyFeatures()))
            style.addSource(GeoJsonSource("endpoints", emptyFeatures()))
            style.addLayer(FillLayer("uncertainty-area", "uncertainty").withProperties(fillColor("#67A879"), fillOpacity(0.18f)))
            style.addLayer(LineLayer("journey-outline", "journey").withProperties(lineColor("#FCFDF9"), lineWidth(9f), lineCap(Property.LINE_CAP_ROUND), lineJoin(Property.LINE_JOIN_ROUND)))
            style.addLayer(LineLayer("journey-line", "journey").withProperties(lineColor("#24764D"), lineWidth(5f), lineCap(Property.LINE_CAP_ROUND), lineJoin(Property.LINE_JOIN_ROUND)))
            style.addLayer(CircleLayer("endpoint-markers", "endpoints").withProperties(circleRadius(5f), circleColor("#195A40"), circleStrokeColor("#FCFDF9"), circleStrokeWidth(2f)))
            style.addLayer(SymbolLayer("endpoint-labels", "endpoints").withProperties(textField(Expression.get("label")),
                textFont(arrayOf("Noto Sans Regular")), textSize(12f), textMaxWidth(10f), textOffset(arrayOf(0f, 1.6f)),
                textColor(if (dark) "#F1F6EC" else "#195A40"), textHaloColor(if (dark) "#15231C" else "#FCFDF9"),
                textHaloWidth(2f), textAllowOverlap(true)))
            style.addImage("setu-vehicle", vehicleBitmap())
            style.addLayer(CircleLayer("position-without-heading", "vehicle")
                .withFilter(Expression.not(Expression.has("bearing")))
                .withProperties(circleRadius(8f), circleColor("#195A40"), circleStrokeColor("#FCFDF9"), circleStrokeWidth(3f)))
            style.addLayer(SymbolLayer("vehicle-marker", "vehicle").withProperties(iconImage("setu-vehicle"), iconSize(0.7f),
                iconAllowOverlap(true), iconIgnorePlacement(true), iconRotationAlignment(Property.ICON_ROTATION_ALIGNMENT_MAP),
                iconRotate(Expression.get("bearing"))).withFilter(Expression.has("bearing")))
            styleReady = true
            if (!maps.region.bundled && mapView.width > 0 && mapView.height > 0) {
                val area = maps.region.bounds
                val bounds = LatLngBounds.from(area[2], area[3], area[0], area[1])
                map.moveCamera(CameraUpdateFactory.newLatLngBounds(bounds, (16 * density).roundToInt()))
            }
          }
        }
    }
    LaunchedEffect(route, nativeMap, styleReady, bottomInset, originLabel, maps) {
        val map = nativeMap ?: return@LaunchedEffect
        if (!styleReady) return@LaunchedEffect
        map.style?.getSourceAs<GeoJsonSource>("journey")?.setGeoJson(route?.let { lineFeature(it.points) } ?: emptyFeatures())
        map.style?.getSourceAs<GeoJsonSource>("endpoints")?.setGeoJson(route?.let { endpointFeatures(it, originLabel) } ?: emptyFeatures())
        if (route != null && route.points.size > 1) {
            val bounds = LatLngBounds.Builder().includes(route.points.map { LatLng(it.latitude, it.longitude) }).build()
            map.animateCamera(CameraUpdateFactory.newLatLngBounds(bounds,
                (72 * density).roundToInt(), ((if (reserveControls) 140 else 30) * density).roundToInt(),
                ((if (reserveControls) 112 else 72) * density).roundToInt(), bottomInset + (64 * density).roundToInt()), 700)
        }
    }
    LaunchedEffect(pose, nativeMap, styleReady) {
        val map = nativeMap ?: return@LaunchedEffect
        if (!styleReady) return@LaunchedEffect
        map.style?.getSourceAs<GeoJsonSource>("vehicle")?.setGeoJson(pose?.let { pointFeature(it) } ?: emptyFeatures())
        map.style?.getSourceAs<GeoJsonSource>("uncertainty")?.setGeoJson(pose?.takeIf { (it.filterRadius95Meters ?: it.accuracyMeters ?: 0.0) > 0 }?.let { confidenceFeature(it) } ?: emptyFeatures())
    }
}

private fun emptyFeatures() = "{\"type\":\"FeatureCollection\",\"features\":[]}"
private fun endpointFeatures(route: DriveRoute, originLabel: String): String {
    if (route.points.isEmpty()) return emptyFeatures()
    val features = JSONArray()
    listOf(route.points.first() to originLabel, route.points.last() to "Destination").forEach { (point, label) ->
        val visibleLabel = if (label.length <= 32) label else label.take(29) + "…"
        features.put(JSONObject().put("type", "Feature").put("properties", JSONObject().put("label", visibleLabel))
            .put("geometry", JSONObject().put("type", "Point").put("coordinates", JSONArray().put(point.longitude).put(point.latitude))))
    }
    return JSONObject().put("type", "FeatureCollection").put("features", features).toString()
}
private fun lineFeature(points: List<GeoPoint>) = JSONObject().put("type", "Feature").put("properties", JSONObject())
    .put("geometry", JSONObject().put("type", "LineString").put("coordinates", JSONArray().apply {
        points.forEach { put(JSONArray().put(it.longitude).put(it.latitude)) }
    })).toString()
private fun pointFeature(pose: Pose) = JSONObject().put("type", "Feature").put("properties", JSONObject().put("bearing", pose.bearing))
    .put("geometry", JSONObject().put("type", "Point").put("coordinates", JSONArray().put(pose.point.longitude).put(pose.point.latitude))).toString()

private fun confidenceFeature(pose: Pose): String {
    val radius = requireNotNull(pose.filterRadius95Meters ?: pose.accuracyMeters).coerceAtMost(5000.0)
    val ring = JSONArray()
    for (index in 0..48) {
        val angle = index * 2 * PI / 48
        ring.put(JSONArray().put(pose.point.longitude + radius * cos(angle) / (111320 * cos(Math.toRadians(pose.point.latitude)).coerceAtLeast(0.01)))
            .put(pose.point.latitude + radius * sin(angle) / 111320))
    }
    return JSONObject().put("type", "Feature").put("properties", JSONObject()).put("geometry",
        JSONObject().put("type", "Polygon").put("coordinates", JSONArray().put(ring))).toString()
}

private fun vehicleBitmap(): Bitmap {
    val bitmap = Bitmap.createBitmap(80, 80, Bitmap.Config.ARGB_8888)
    val canvas = Canvas(bitmap)
    val paint = Paint(Paint.ANTI_ALIAS_FLAG)
    paint.color = android.graphics.Color.WHITE
    canvas.drawCircle(40f, 40f, 32f, paint)
    paint.color = android.graphics.Color.rgb(25, 90, 64)
    val chevron = Path().apply { moveTo(40f, 13f); lineTo(61f, 61f); lineTo(40f, 51f); lineTo(19f, 61f); close() }
    canvas.drawPath(chevron, paint)
    return bitmap
}
