package com.setu.navigator.data

import java.util.PriorityQueue
import java.nio.DoubleBuffer
import java.nio.IntBuffer
import kotlin.math.*

class RoadGraph internal constructor(
    internal val latitudes: DoubleBuffer, internal val longitudes: DoubleBuffer,
    internal val heads: IntBuffer, internal val sourceNodes: IntBuffer, internal val targets: IntBuffer, internal val next: IntBuffer,
    internal val lengths: DoubleBuffer, internal val nameIds: IntBuffer, internal val names: List<String>,
) {
    val nodeCount get() = latitudes.limit()
    val edgeCount get() = targets.limit()
    private data class Snap(val from: Int, val edge: Int, val fraction: Double, val point: GeoPoint, val offset: Double)
    private fun point(node: Int) = GeoPoint(latitudes[node], longitudes[node])
    private var segmentIndex: RoadSegmentIndex? = null

    @Synchronized
    internal fun index(checkpoint: () -> Unit = {}): RoadSegmentIndex = segmentIndex
        ?: RoadSegmentIndex.build(this, checkpoint).also { segmentIndex = it }

    private fun snaps(location: GeoPoint, checkpoint: () -> Unit, alternatives: Boolean = false): List<Snap> {
        val candidates = PriorityQueue<Snap>(compareByDescending<Snap> { it.offset }.thenByDescending { it.edge })
        val eastScale = 111320.0 * cos(Math.toRadians(location.latitude))
        var closest = 250.0
        index(checkpoint).visit(location, checkpoint) { edge ->
            val node = sourceNodes[edge]
            val east = (longitudes[node] - location.longitude) * eastScale
            val north = (latitudes[node] - location.latitude) * 111320.0
                val target = targets[edge]
                val deltaEast = (longitudes[target] - longitudes[node]) * eastScale
                val deltaNorth = (latitudes[target] - latitudes[node]) * 111320.0
                val squaredLength = deltaEast * deltaEast + deltaNorth * deltaNorth
                val fraction = if (squaredLength == 0.0) 0.0 else
                    (-(east * deltaEast + north * deltaNorth) / squaredLength).coerceIn(0.0, 1.0)
                val offsetSquared = (east + fraction * deltaEast).pow(2) + (north + fraction * deltaNorth).pow(2)
                if (offsetSquared <= (if (alternatives) 250.0 else closest + 0.1).pow(2)) {
                    val offset = sqrt(offsetSquared)
                    if (!alternatives && offset < closest - 0.1) candidates.clear()
                    closest = minOf(closest, offset)
                    if (offset <= 250.0) {
                        candidates.add(Snap(node, edge, fraction, point(node).interpolate(point(target), fraction), offset))
                        if (candidates.size > 256) candidates.remove()
                    }
                }
        }
        return candidates.filter { alternatives || it.offset <= closest + 0.1 }.sortedWith(compareBy<Snap> { it.offset }.thenBy { it.edge })
    }

    fun route(from: GeoPoint, to: GeoPoint, checkpoint: () -> Unit = {}): DriveRoute {
        val starts = snaps(from, checkpoint)
        require(starts.isNotEmpty()) { "No mapped driving road within 250 metres of your start. Choose a nearby public road." }
        val ends = snaps(to, checkpoint)
        require(ends.isNotEmpty()) { "No mapped driving road within 250 metres of this destination. Choose a nearby entrance." }
        // One scratch buffer serves every attempt, so a route costs a few hundred kilobytes of
        // working memory instead of three dense node-count arrays.
        val scratch = SearchScratch(nodeCount)
        return search(from, to, starts, ends, scratch, checkpoint)
            ?: search(from, to, starts, snaps(to, checkpoint, true), scratch, checkpoint)
            ?: search(from, to, snaps(from, checkpoint, true), snaps(to, checkpoint, true), scratch, checkpoint)
            ?: error("No connected driving route between roads within 250 metres of these points. Try another public-road entrance.")
    }

    private fun search(from: GeoPoint, to: GeoPoint, starts: List<Snap>, ends: List<Snap>,
                       scratch: SearchScratch, checkpoint: () -> Unit): DriveRoute? {
        scratch.reset()
        val endNodes = ends.groupBy { it.from }
        val endEdges = ends.groupBy { it.edge }
        val maximumOffset = ends.maxOf { it.offset } + 2.0
        fun heuristic(node: Int) = maxOf(0.0, point(node).distanceTo(to) - maximumOffset)
        var bestCost = Double.POSITIVE_INFINITY
        var bestEnd: Snap? = null
        var directStart: Snap? = null
        starts.forEachIndexed { index, start ->
            endEdges[start.edge].orEmpty().filter { it.fraction >= start.fraction }.forEach { end ->
                val distance = start.offset + (end.fraction - start.fraction) * lengths[start.edge] + end.offset
                if (distance < bestCost) { bestCost = distance; bestEnd = end; directStart = start }
            }
            val target = targets[start.edge]
            val cost = start.offset + (1.0 - start.fraction) * lengths[start.edge]
            if (scratch.relax(target, cost, -1, index)) scratch.push(target, cost, cost + heuristic(target))
        }
        var iterations = 0
        while (!scratch.frontierIsEmpty()) {
            if (iterations++ % 1024 == 0) checkpoint()
            if (scratch.peekPriority() >= bestCost) break
            scratch.pop()
            val node = scratch.poppedNode
            val settled = scratch.poppedCost
            if (scratch.expansions > SearchScratch.MAX_EXPANSIONS) {
                error("This journey is too large to plan offline. Try a closer destination.")
            }
            if (settled > scratch.costOf(node)) continue
            val root = scratch.rootOf(node)
            endNodes[node].orEmpty().forEach { end ->
                val cost = settled + end.fraction * lengths[end.edge] + end.offset
                if (cost < bestCost) { bestCost = cost; bestEnd = end; directStart = null }
            }
            var edge = heads[node]
            while (edge >= 0) {
                val target = targets[edge]
                val candidate = settled + lengths[edge]
                if (candidate < bestCost && scratch.relax(target, candidate, edge, root)) {
                    scratch.push(target, candidate, candidate + heuristic(target))
                }
                edge = next[edge]
            }
        }
        val end = bestEnd ?: return null
        val points = mutableListOf<GeoPoint>()
        val roadNames = mutableListOf<String>()
        fun append(location: GeoPoint, edge: Int) {
            if (points.isEmpty()) points.add(location)
            else if (points.last().distanceTo(location) > 0.01) { points.add(location); roadNames.add(names[nameIds[edge]]) }
        }
        if (directStart != null) {
            append(directStart.point, directStart.edge)
        } else {
            val edges = mutableListOf<Int>()
            var node = end.from
            while (scratch.previousEdgeOf(node) >= 0) {
                val edge = scratch.previousEdgeOf(node)
                edges.add(edge)
                node = sourceNodes[edge]
            }
            val rootIndex = scratch.rootOf(node)
            if (rootIndex !in starts.indices) return null
            val start = starts[rootIndex]
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
            return RoadGraph(DoubleBuffer.wrap(latitudes, 0, count), DoubleBuffer.wrap(longitudes, 0, count),
                IntBuffer.wrap(heads, 0, count), IntBuffer.wrap(sources, 0, edgeSize), IntBuffer.wrap(targets, 0, edgeSize),
                IntBuffer.wrap(next, 0, edgeSize), DoubleBuffer.wrap(lengths, 0, edgeSize),
                IntBuffer.wrap(nameIds, 0, edgeSize), names.toList())
        }
    }
}
