package com.setu.navigator.ui

import android.content.ComponentCallbacks2
import android.content.res.Configuration
import android.graphics.Bitmap
import android.graphics.Canvas
import android.graphics.Paint
import android.graphics.Path
import android.graphics.RectF
import androidx.compose.foundation.layout.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.layout.onSizeChanged
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
    trail: List<Pose> = emptyList(), comparisonPose: Pose? = null,
    recordedPath: List<Pose>? = null,
    followPosition: Boolean = false, onFollowInterrupted: () -> Unit = {},
    referenceRoute: Boolean = false,
    onRendered: (Boolean) -> Unit = {},
) {
    val context = LocalContext.current
    val density = LocalDensity.current.density
    val lifecycle = LocalLifecycleOwner.current.lifecycle
    val mapView = remember { MapView(context, MapLibreMapOptions.createFromAttributes(context).textureMode(true)).apply { onCreate(null) } }
    var nativeMap by remember { mutableStateOf<MapLibreMap?>(null) }
    var styleReady by remember { mutableStateOf(false) }
    var mapRendered by remember { mutableStateOf(false) }
    val reportRendered by rememberUpdatedState(onRendered)
    LaunchedEffect(mapRendered) { reportRendered(mapRendered) }
    var mapError by remember { mutableStateOf<String?>(null) }
    var reload by remember { mutableIntStateOf(0) }
    var styleGeneration by remember { mutableIntStateOf(0) }
    var readyGeneration by remember { mutableIntStateOf(0) }
    var viewport by remember { mutableStateOf(androidx.compose.ui.unit.IntSize.Zero) }
    val interruptFollowing by rememberUpdatedState(onFollowInterrupted)
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
        var started = false
        var resumed = false
        fun synchronize(state: Lifecycle.State) {
            if (resumed && !state.isAtLeast(Lifecycle.State.RESUMED)) { mapView.onPause(); resumed = false }
            if (started && !state.isAtLeast(Lifecycle.State.STARTED)) { mapView.onStop(); started = false }
            if (!started && state.isAtLeast(Lifecycle.State.STARTED)) { mapView.onStart(); started = true }
            if (!resumed && state.isAtLeast(Lifecycle.State.RESUMED)) { mapView.onResume(); resumed = true }
        }
        val memoryCallbacks = object : ComponentCallbacks2 {
            override fun onConfigurationChanged(configuration: Configuration) = Unit
            override fun onLowMemory() = mapView.onLowMemory()
            override fun onTrimMemory(level: Int) {
                if (level == ComponentCallbacks2.TRIM_MEMORY_RUNNING_LOW || level == ComponentCallbacks2.TRIM_MEMORY_RUNNING_CRITICAL) mapView.onLowMemory()
            }
        }
        context.applicationContext.registerComponentCallbacks(memoryCallbacks)
        val observer = LifecycleEventObserver { _, event -> synchronize(event.targetState) }
        lifecycle.addObserver(observer)
        synchronize(lifecycle.currentState)
        onDispose {
            lifecycle.removeObserver(observer)
            context.applicationContext.unregisterComponentCallbacks(memoryCallbacks)
            synchronize(Lifecycle.State.CREATED)
            mapView.onDestroy()
        }
    }

    DisposableEffect(mapView, nativeMap) {
        val listener = MapView.OnDidFinishRenderingFrameListener { fully, _, _ ->
            if (fully && styleReady && mapError == null) mapRendered = true
        }
        mapView.addOnDidFinishRenderingFrameListener(listener)
        val failure = MapView.OnDidFailLoadingMapListener { _ ->
            mapError = "The offline map could not load. Try again or select another offline area."
            mapRendered = false
        }
        mapView.addOnDidFailLoadingMapListener(failure)
        onDispose {
            mapView.removeOnDidFinishRenderingFrameListener(listener)
            mapView.removeOnDidFailLoadingMapListener(failure)
        }
    }

    DisposableEffect(nativeMap) {
        val listener = MapLibreMap.OnCameraMoveStartedListener { reason ->
            if (reason == MapLibreMap.OnCameraMoveStartedListener.REASON_API_GESTURE) interruptFollowing()
        }
        nativeMap?.addOnCameraMoveStartedListener(listener)
        onDispose { nativeMap?.removeOnCameraMoveStartedListener(listener) }
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
        modifier = Modifier.fillMaxSize().onSizeChanged { viewport = it }
            .testTag(if (mapRendered) "offline-map-ready" else "offline-map-loading")
            .semantics { contentDescription = "Offline map of ${maps.region.name}. Use destination search to plan a route." },
      )
      if (!mapRendered) Surface(Modifier.fillMaxSize(), color = MaterialTheme.colorScheme.surfaceContainer) {
          Box(Modifier.fillMaxSize().padding(top = if (reserveControls) 108.dp else 0.dp,
              bottom = (bottomInset / density).dp), contentAlignment = Alignment.Center) {
              Row(Modifier.padding(horizontal = 20.dp).testTag("map-loading-message"),
                  verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(12.dp)) {
                  if (mapError == null) CircularProgressIndicator(Modifier.size(20.dp), strokeWidth = 2.dp)
                  Text(mapError ?: "Preparing your offline map…", Modifier.weight(1f), style = MaterialTheme.typography.bodySmall)
                  if (mapError != null) TextButton(onClick = { reload++ }) { Text("Try again") }
              }
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
            withContext(Dispatchers.IO) { maps.citySource() }
        } catch (cancelled: kotlinx.coroutines.CancellationException) {
            throw cancelled
        } catch (error: Exception) {
            mapError = "The active map could not be opened. Try again or select another offline area."
            return@LaunchedEffect
        }
        withContext(Dispatchers.Main.immediate) {
          map.cameraPosition = CameraPosition.Builder().target(LatLng(maps.center.latitude, maps.center.longitude)).zoom(14.4).build()
          val document = JSONObject(json)
          document.getJSONObject("sources").put("city", city)
          if (city.getString("type") == "vector") {
              val layers = document.getJSONArray("layers")
              for (index in 0 until layers.length()) {
                  val layer = layers.getJSONObject(index)
                  if (layer.optString("source") == "city") layer.put("source-layer", "city")
              }
          }
          map.setStyle(Style.Builder().fromJson(document.toString())) { style ->
            if (generation != styleGeneration) return@setStyle
            style.addSource(GeoJsonSource("journey", emptyFeatures()))
            style.addSource(GeoJsonSource("uncertainty", emptyFeatures()))
            style.addSource(GeoJsonSource("vehicle", emptyFeatures()))
            style.addSource(GeoJsonSource("endpoints", emptyFeatures()))
            style.addSource(GeoJsonSource("route-access", emptyFeatures()))
            style.addSource(GeoJsonSource("map-places", JSONObject().put("type", "FeatureCollection").put("features", JSONArray().apply {
                maps.places.forEach { place ->
                    put(JSONObject().put("type", "Feature").put("properties", JSONObject().put("label", place.name))
                        .put("geometry", JSONObject().put("type", "Point").put("coordinates", JSONArray().put(place.point.longitude).put(place.point.latitude))))
                }
            }).toString()))
            style.addLayer(SymbolLayer("area-labels", "map-places").withProperties(textField("{label}"), textFont(arrayOf("Noto Sans Regular")),
                textSize(12f), textColor(if (dark) "#C2CAB7" else "#67715E"), textHaloColor(if (dark) "#15231C" else "#FCFDF9"),
                textHaloWidth(1.5f), textPadding(12f)).apply { minZoom = 7f; maxZoom = 14f })
            style.addSource(GeoJsonSource("tracked-path", emptyFeatures()))
            style.addSource(GeoJsonSource("gps-reference", emptyFeatures()))
            style.addLayer(FillLayer("uncertainty-area", "uncertainty").withProperties(fillColor("#67A879"), fillOpacity(0.18f)))
            style.addLayer(LineLayer("route-access-line", "route-access").withProperties(lineColor(if (dark) "#C2CAB7" else "#67715E"),
                lineWidth(2f), lineDasharray(arrayOf(2f, 2f))))
            style.addLayer(LineLayer("journey-outline", "journey").withProperties(lineColor("#FCFDF9"), lineWidth(11f), lineCap(Property.LINE_CAP_ROUND), lineJoin(Property.LINE_JOIN_ROUND)))
            style.addLayer(LineLayer("journey-line", "journey").withProperties(lineColor(if (dark) "#79B4FF" else "#1769E0"), lineWidth(7f), lineCap(Property.LINE_CAP_ROUND), lineJoin(Property.LINE_JOIN_ROUND)))
            style.addLayer(LineLayer("tracked-line", "tracked-path").withProperties(lineColor(if (dark) "#80CAEF" else "#176C96"),
                lineWidth(4f), lineCap(Property.LINE_CAP_ROUND), lineJoin(Property.LINE_JOIN_ROUND)))
            style.addLayer(CircleLayer("last-gps-marker", "gps-reference").withProperties(circleColor("#A96617"),
                circleRadius(6f), circleStrokeColor("#FCFDF9"), circleStrokeWidth(2f)))
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
            readyGeneration = generation
            if (!maps.region.bundled && mapView.width > 0 && mapView.height > 0) {
                val area = maps.region.bounds
                val bounds = LatLngBounds.from(area[2], area[3], area[0], area[1])
                map.moveCamera(CameraUpdateFactory.newLatLngBounds(bounds, (16 * density).roundToInt()))
            }
          }
        }
    }
    LaunchedEffect(route, recordedPath, nativeMap, styleReady, readyGeneration, viewport,
        bottomInset, originLabel, maps, referenceRoute) {
        val map = nativeMap ?: return@LaunchedEffect
        if (!styleReady) return@LaunchedEffect
        map.style?.getLayerAs<LineLayer>("journey-line")?.setProperties(lineColor(
            if (referenceRoute) { if (dark) "#A2D69B" else "#195A40" }
            else if (dark) "#79B4FF" else "#1769E0"
        ))
        map.style?.getSourceAs<GeoJsonSource>("journey")?.setGeoJson(recordedPath?.let(::recordedFeatures) ?: route?.takeIf { it.points.size > 1 }?.let { lineFeature(it.points) } ?: emptyFeatures())
        map.style?.getSourceAs<GeoJsonSource>("endpoints")?.setGeoJson(route?.let { endpointFeatures(it, originLabel) } ?: emptyFeatures())
        map.style?.getSourceAs<GeoJsonSource>("route-access")?.setGeoJson(route?.let(::accessFeatures) ?: emptyFeatures())
        if (route != null && route.points.size > 1 && !followPosition && viewport.width > 0 && viewport.height > 0) {
            val bounds = LatLngBounds.Builder().includes(route.points.map { LatLng(it.latitude, it.longitude) }).build()
            map.animateCamera(CameraUpdateFactory.newLatLngBounds(bounds,
                (72 * density).roundToInt(), ((if (reserveControls) 140 else 30) * density).roundToInt(),
                ((if (reserveControls) 112 else 72) * density).roundToInt(), bottomInset + (64 * density).roundToInt()), 700)
        }
    }
    // The position sources update at the estimator's 10 Hz. Building their GeoJSON on the main
    // thread put a marker document and a confidence ring through JSON assembly on every frame; the
    // work now happens on Dispatchers.Default and only the source hand-off stays on main.
    LaunchedEffect(pose, nativeMap, styleReady, readyGeneration) {
        val map = nativeMap ?: return@LaunchedEffect
        if (!styleReady) return@LaunchedEffect
        val (vehicle, uncertainty) = withContext(Dispatchers.Default) {
            (pose?.let { pointFeature(it) } ?: emptyFeatures()) to
                (pose?.takeIf { (it.filterRadius95Meters ?: it.accuracyMeters ?: 0.0) > 0 }?.let { confidenceFeature(it) } ?: emptyFeatures())
        }
        map.style?.getSourceAs<GeoJsonSource>("vehicle")?.setGeoJson(vehicle)
        map.style?.getSourceAs<GeoJsonSource>("uncertainty")?.setGeoJson(uncertainty)
    }
    // The trail carries up to 1,200 samples, so serialising it inline stalled a frame every time a
    // new position was retained.
    LaunchedEffect(trail, comparisonPose, nativeMap, styleReady, readyGeneration) {
        val map = nativeMap ?: return@LaunchedEffect
        if (!styleReady) return@LaunchedEffect
        val (path, reference) = withContext(Dispatchers.Default) {
            val segments = JSONArray()
            positionSegments(trail).forEach { segment ->
                segments.put(JSONArray().apply { segment.forEach { put(JSONArray().put(it.longitude).put(it.latitude)) } })
            }
            JSONObject().put("type", "Feature").put("properties", JSONObject()).put("geometry",
                JSONObject().put("type", "MultiLineString").put("coordinates", segments)).toString() to
                (comparisonPose?.let(::pointFeature) ?: emptyFeatures())
        }
        map.style?.getSourceAs<GeoJsonSource>("tracked-path")?.setGeoJson(path)
        map.style?.getSourceAs<GeoJsonSource>("gps-reference")?.setGeoJson(reference)
    }
    LaunchedEffect(pose, followPosition, bottomInset, nativeMap, styleReady, readyGeneration, viewport) {
        val map = nativeMap ?: return@LaunchedEffect
        val position = pose ?: return@LaunchedEffect
        if (!styleReady || !followPosition) return@LaunchedEffect
        map.moveCamera(CameraUpdateFactory.newCameraPosition(CameraPosition.Builder(map.cameraPosition)
            .target(LatLng(position.point.latitude, position.point.longitude)).zoom(maxOf(16.0, map.cameraPosition.zoom))
            .padding(24.0 * density, 104.0 * density, 24.0 * density, bottomInset + 24.0 * density).build()))
    }
}

private fun emptyFeatures() = "{\"type\":\"FeatureCollection\",\"features\":[]}"

private fun accessFeatures(route: DriveRoute): String {
    val features = JSONArray()
    if (route.startOffsetMeters > 5) features.put(JSONObject(lineFeature(listOf(requireNotNull(route.requestedStart), route.points.first()))))
    if (route.destinationOffsetMeters > 5) features.put(JSONObject(lineFeature(listOf(route.points.last(), requireNotNull(route.requestedDestination)))))
    return JSONObject().put("type", "FeatureCollection").put("features", features).toString()
}

private fun recordedFeatures(history: List<Pose>): String = JSONObject().put("type", "FeatureCollection")
    .put("features", JSONArray().apply { positionSegments(history).forEach { put(JSONObject(lineFeature(it))) } }).toString()
private fun endpointFeatures(route: DriveRoute, originLabel: String): String {
    if (route.points.isEmpty()) return emptyFeatures()
    val features = JSONArray()
    listOf((route.requestedStart ?: route.points.first()) to originLabel,
        (route.requestedDestination ?: route.points.last()) to "Destination").forEach { (point, label) ->
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
