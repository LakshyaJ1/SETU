package com.setu.navigator.data

import java.util.PriorityQueue
import kotlin.math.*

class RoadGraph private constructor(
    private val latitudes: DoubleArray, private val longitudes: DoubleArray,
    private val heads: IntArray, private val sourceNodes: IntArray, private val targets: IntArray, private val next: IntArray,
    private val lengths: DoubleArray, private val nameIds: IntArray, private val names: List<String>,
) {
    val nodeCount get() = latitudes.size
    val edgeCount get() = targets.size
    private data class Snap(val from: Int, val edge: Int, val fraction: Double, val point: GeoPoint, val offset: Double)
    private data class Visit(val node: Int, val cost: Double, val priority: Double)
    private fun point(node: Int) = GeoPoint(latitudes[node], longitudes[node])

    private fun snaps(location: GeoPoint, checkpoint: () -> Unit): List<Snap> {
        val candidates = mutableListOf<Snap>()
        val eastScale = 111320.0 * cos(Math.toRadians(location.latitude))
        var closest = 250.0
        for (node in heads.indices) {
            if (node % 4096 == 0) checkpoint()
            val east = (longitudes[node] - location.longitude) * eastScale
            val north = (latitudes[node] - location.latitude) * 111320.0
            var edge = heads[node]
            while (edge >= 0) {
                val target = targets[edge]
                val deltaEast = (longitudes[target] - longitudes[node]) * eastScale
                val deltaNorth = (latitudes[target] - latitudes[node]) * 111320.0
                val squaredLength = deltaEast * deltaEast + deltaNorth * deltaNorth
                val fraction = if (squaredLength == 0.0) 0.0 else
                    (-(east * deltaEast + north * deltaNorth) / squaredLength).coerceIn(0.0, 1.0)
                val offsetSquared = (east + fraction * deltaEast).pow(2) + (north + fraction * deltaNorth).pow(2)
                if (offsetSquared <= (closest + 0.1).pow(2)) {
                    val offset = sqrt(offsetSquared)
                    if (offset < closest - 0.1) candidates.clear()
                    closest = minOf(closest, offset)
                    if (candidates.size < 32 && offset <= 250.0) {
                        candidates.add(Snap(node, edge, fraction, point(node).interpolate(point(target), fraction), offset))
                    }
                }
                edge = next[edge]
            }
        }
        return candidates.filter { it.offset <= closest + 0.1 }
    }

    fun route(from: GeoPoint, to: GeoPoint, checkpoint: () -> Unit = {}): DriveRoute {
        val starts = snaps(from, checkpoint)
        require(starts.isNotEmpty()) { "No mapped driving road within 250 metres of your start. Choose a nearby public road." }
        val ends = snaps(to, checkpoint)
        require(ends.isNotEmpty()) { "No mapped driving road within 250 metres of this destination. Choose a nearby entrance." }
        val endNodes = ends.groupBy { it.from }
        val maximumOffset = ends.maxOf { it.offset } + 2.0
        fun heuristic(node: Int) = maxOf(0.0, point(node).distanceTo(to) - maximumOffset)
        val costs = DoubleArray(nodeCount) { Double.POSITIVE_INFINITY }
        val previous = IntArray(nodeCount) { -1 }
        val root = IntArray(nodeCount) { -1 }
        val queue = PriorityQueue<Visit>(compareBy { it.priority })
        var bestCost = Double.POSITIVE_INFINITY
        var bestEnd: Snap? = null
        var directStart: Snap? = null
        starts.forEachIndexed { index, start ->
            ends.filter { it.edge == start.edge && it.fraction >= start.fraction }.forEach { end ->
                val distance = (end.fraction - start.fraction) * lengths[start.edge]
                if (distance < bestCost) { bestCost = distance; bestEnd = end; directStart = start }
            }
            val target = targets[start.edge]
            val cost = (1.0 - start.fraction) * lengths[start.edge]
            if (cost < costs[target]) {
                costs[target] = cost
                root[target] = index
                queue.add(Visit(target, cost, cost + heuristic(target)))
            }
        }
        var iterations = 0
        while (queue.isNotEmpty()) {
            if (iterations++ % 1024 == 0) checkpoint()
            val visit = queue.remove()
            if (visit.priority >= bestCost) break
            if (visit.cost > costs[visit.node]) continue
            endNodes[visit.node].orEmpty().forEach { end ->
                val cost = visit.cost + end.fraction * lengths[end.edge]
                if (cost < bestCost) { bestCost = cost; bestEnd = end; directStart = null }
            }
            var edge = heads[visit.node]
            while (edge >= 0) {
                val target = targets[edge]
                val candidate = visit.cost + lengths[edge]
                if (candidate < costs[target]) {
                    costs[target] = candidate
                    previous[target] = edge
                    root[target] = root[visit.node]
                    queue.add(Visit(target, candidate, candidate + heuristic(target)))
                }
                edge = next[edge]
            }
        }
        val end = bestEnd ?: error("The nearest roads are not connected in this map. Try another public-road entrance.")
        val points = mutableListOf<GeoPoint>()
        val roadNames = mutableListOf<String>()
        fun append(location: GeoPoint, edge: Int) {
            if (points.isEmpty()) points.add(location)
            else if (points.last().distanceTo(location) > 0.01) { points.add(location); roadNames.add(names[nameIds[edge]]) }
        }
        if (directStart != null) {
            append(directStart!!.point, directStart!!.edge)
        } else {
            val edges = mutableListOf<Int>()
            var node = end.from
            while (previous[node] >= 0) {
                val edge = previous[node]
                edges.add(edge)
                node = sourceNodes[edge]
            }
            val start = starts[root[node]]
            append(start.point, start.edge)
            append(point(targets[start.edge]), start.edge)
            edges.asReversed().forEach { append(point(targets[it]), it) }
        }
        append(end.point, end.edge)
        return describe(points, roadNames, from, to)
    }

    private fun describe(points: List<GeoPoint>, roadNames: List<String>, from: GeoPoint, to: GeoPoint): DriveRoute {
        val instructions = mutableListOf(Maneuver(0, "Follow the highlighted route", "straight", 0.0))
        var distance = 0.0
        for (index in 1 until points.size) {
            distance += points[index - 1].distanceTo(points[index])
            if (index < points.lastIndex) {
                val change = (points[index].bearingTo(points[index + 1]) - points[index - 1].bearingTo(points[index]) + 540) % 360 - 180
                if (abs(change) > 35 && distance - instructions.last().distanceFromStart > 35) {
                    val direction = if (change > 0) "right" else "left"
                    instructions.add(Maneuver(index, "Turn $direction onto ${roadNames[index]}", direction, distance))
                }
            }
        }
        instructions.add(Maneuver(points.lastIndex, "Arrive near your destination", "arrive", distance))
        return DriveRoute(points, distance, instructions, from, to)
    }

    class Builder(private val expectedNodes: Int? = null, private val expectedEdges: Int? = null) {
        init {
            require(expectedNodes == null || expectedNodes in 1..4_000_000)
            require(expectedEdges == null || expectedEdges in 1..8_000_000)
        }
        private var latitudes = DoubleArray(expectedNodes ?: 256) { Double.NaN }
        private var longitudes = DoubleArray(latitudes.size)
        private var heads = IntArray(latitudes.size) { -1 }
        private var sources = IntArray(expectedEdges ?: 512)
        private var targets = IntArray(sources.size)
        private var next = IntArray(sources.size)
        private var lengths = DoubleArray(sources.size)
        private var nameIds = IntArray(sources.size)
        private val nodeIndices = mutableMapOf<Long, Int>()
        private val names = mutableListOf<String>()
        private val nameIndices = mutableMapOf<String, Int>()
        private var nodeSize = 0
        private var edgeSize = 0
        private var built = false

        private fun node(identifier: Long, point: GeoPoint): Int {
            val index = if (expectedNodes != null) {
                require(identifier in 1L..expectedNodes.toLong()) { "Invalid indexed road node." }
                identifier.toInt() - 1
            } else nodeIndices.getOrPut(identifier) { nodeSize++ }
            require(index < 4_000_000) { "This graph has too many road nodes." }
            if (index >= latitudes.size) {
                val capacity = minOf(4_000_000, maxOf(index + 1, latitudes.size * 2))
                latitudes = latitudes.copyOf(capacity).also { it.fill(Double.NaN, heads.size) }
                longitudes = longitudes.copyOf(capacity)
                heads = heads.copyOf(capacity).also { it.fill(-1, index) }
            }
            require(latitudes[index].isNaN() || latitudes[index] == point.latitude && longitudes[index] == point.longitude) {
                "A road node has conflicting coordinates."
            }
            latitudes[index] = point.latitude
            longitudes[index] = point.longitude
            return index
        }

        fun road(identifiers: LongArray, coordinates: List<GeoPoint>, name: String, oneway: String) {
            check(!built)
            require(identifiers.size in 2..10000 && identifiers.size == coordinates.size)
            require(name.length <= 200)
            require(oneway == "no" || oneway == "yes" || oneway == "1" || oneway == "true" || oneway == "-1") { "Unsupported one-way value." }
            val forward = oneway != "-1"
            val reverse = oneway == "no" || oneway == "-1"
            val nameId = nameIndices.getOrPut(name) { names.add(name); names.lastIndex }
            var previous = node(identifiers[0], coordinates[0])
            for (index in 1 until identifiers.size) {
                val current = node(identifiers[index], coordinates[index])
                val distance = coordinates[index - 1].distanceTo(coordinates[index])
                if (forward) edge(previous, current, distance, nameId)
                if (reverse) edge(current, previous, distance, nameId)
                previous = current
            }
        }

        private fun edge(from: Int, to: Int, distance: Double, name: Int) {
            require(edgeSize < 8_000_000) { "This graph has too many road edges." }
            if (edgeSize == sources.size) {
                val capacity = minOf(8_000_000, maxOf(512, edgeSize * 2))
                sources = sources.copyOf(capacity); targets = targets.copyOf(capacity)
                next = next.copyOf(capacity); lengths = lengths.copyOf(capacity); nameIds = nameIds.copyOf(capacity)
            }
            sources[edgeSize] = from; targets[edgeSize] = to; lengths[edgeSize] = distance
            nameIds[edgeSize] = name; next[edgeSize] = heads[from]; heads[from] = edgeSize++
        }

        fun build(): RoadGraph {
            check(!built)
            built = true
            val count = expectedNodes ?: nodeSize
            require(count > 0 && edgeSize > 0 && (0 until count).all { latitudes[it].isFinite() }) { "The road graph has missing nodes." }
            require(expectedEdges == null || expectedEdges == edgeSize) { "Road edge count does not match its metadata." }
            return RoadGraph(if (latitudes.size == count) latitudes else latitudes.copyOf(count),
                if (longitudes.size == count) longitudes else longitudes.copyOf(count),
                if (heads.size == count) heads else heads.copyOf(count),
                if (sources.size == edgeSize) sources else sources.copyOf(edgeSize),
                if (targets.size == edgeSize) targets else targets.copyOf(edgeSize),
                if (next.size == edgeSize) next else next.copyOf(edgeSize),
                if (lengths.size == edgeSize) lengths else lengths.copyOf(edgeSize),
                if (nameIds.size == edgeSize) nameIds else nameIds.copyOf(edgeSize), names.toList())
        }
    }
}
