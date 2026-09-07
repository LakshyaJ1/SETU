package com.setu.navigator.data

import android.content.Context
import org.json.JSONObject
import java.util.PriorityQueue
import kotlin.math.abs

class OfflineMap(private val context: Context, val region: MapRegion) {
    val places get() = region.places
    val center get() = region.center
    val demonstrationStart get() = region.previewStart
    private data class Edge(val to: Long, val distance: Double, val name: String)
    private val positions = mutableMapOf<Long, GeoPoint>()
    private val neighbors = mutableMapOf<Long, MutableList<Edge>>()
    private var loaded = false

    val sizeBytes: Long get() = region.sizeBytes
    fun cityJson(): String = region.directory?.resolve("city.geojson")?.readText()
        ?: context.assets.open("bengaluru.geojson").bufferedReader().use { it.readText() }

    fun contains(point: GeoPoint) = region.contains(point)

    @Synchronized
    private fun loadGraph() {
        if (loaded) return
        val document = JSONObject(region.directory?.resolve("roads.json")?.readText()
            ?: context.assets.open("bengaluru-roads.json").bufferedReader().use { it.readText() })
        val roads = document.getJSONArray("roads")
        for (roadIndex in 0 until roads.length()) {
            val road = roads.getJSONObject(roadIndex)
            val nodes = road.getJSONArray("nodes")
            val coordinates = road.getJSONArray("coordinates")
            val name = road.optString("name", "Local road")
            val oneway = road.optString("oneway", "no")
            for (nodeIndex in 0 until nodes.length()) {
                val coordinate = coordinates.getJSONArray(nodeIndex)
                positions[nodes.getLong(nodeIndex)] = GeoPoint(coordinate.getDouble(1), coordinate.getDouble(0))
            }
            for (nodeIndex in 1 until nodes.length()) {
                val previous = nodes.getLong(nodeIndex - 1)
                val current = nodes.getLong(nodeIndex)
                val distance = positions.getValue(previous).distanceTo(positions.getValue(current))
                if (oneway != "-1") neighbors.getOrPut(previous) { mutableListOf() }.add(Edge(current, distance, name))
                if (oneway !in listOf("yes", "1", "true")) neighbors.getOrPut(current) { mutableListOf() }.add(Edge(previous, distance, name))
            }
        }
        loaded = true
    }

    fun route(from: GeoPoint, to: GeoPoint): DriveRoute {
        require(contains(from) && contains(to)) { "This journey is outside ${region.name}." }
        loadGraph()
        val start = neighbors.keys.minByOrNull { positions.getValue(it).distanceTo(from) }
            ?: error("The offline road graph is empty.")
        require(positions.getValue(start).distanceTo(from) <= 250) { "Move closer to a mapped driving road to start this route." }
        val costs = mutableMapOf(start to 0.0)
        val previous = mutableMapOf<Long, Pair<Long, String>>()
        val queue = PriorityQueue<Pair<Long, Double>>(compareBy { it.second })
        queue.add(start to 0.0)
        while (queue.isNotEmpty()) {
            val (node, cost) = queue.remove()
            if (cost > costs.getValue(node)) continue
            for (edge in neighbors[node].orEmpty()) {
                val candidate = cost + edge.distance
                if (candidate < (costs[edge.to] ?: Double.POSITIVE_INFINITY)) {
                    costs[edge.to] = candidate
                    previous[edge.to] = node to edge.name
                    queue.add(edge.to to candidate)
                }
            }
        }
        val end = costs.keys.filter { positions.getValue(it).distanceTo(to) <= 250 }
            .minByOrNull { positions.getValue(it).distanceTo(to) }
            ?: error("No connected driving road within 250 metres of this destination. Try a nearby entrance.")
        val nodes = mutableListOf(end)
        var cursor = end
        while (cursor != start) {
            cursor = previous.getValue(cursor).first
            nodes.add(cursor)
        }
        nodes.reverse()
        val points = nodes.map(positions::getValue)
        var traveled = 0.0
        val instructions = mutableListOf(Maneuver(0, "Follow the highlighted route", "straight", 0.0))
        for (index in 1 until points.lastIndex) {
            traveled += points[index - 1].distanceTo(points[index])
            val change = (points[index].bearingTo(points[index + 1]) - points[index - 1].bearingTo(points[index]) + 540) % 360 - 180
            if (abs(change) > 35 && traveled - instructions.last().distanceFromStart > 35) {
                val direction = if (change > 0) "right" else "left"
                val road = previous[nodes[index + 1]]?.second ?: "the road"
                instructions.add(Maneuver(index, "Turn $direction onto $road", direction, traveled))
            }
        }
        instructions.add(Maneuver(points.lastIndex, "Arrive near your destination", "arrive", costs.getValue(end)))
        return DriveRoute(points, costs.getValue(end), instructions)
    }
}
