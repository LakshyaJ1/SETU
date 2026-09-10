package com.setu.navigator.data

import kotlin.math.cos

data class RouteProgress(val segment: Int, val distanceFromStart: Double, val distanceFromRoad: Double)

fun routeProgress(route: DriveRoute, position: GeoPoint): RouteProgress {
    var traveled = 0.0
    var closest = RouteProgress(0, 0.0, route.points.firstOrNull()?.distanceTo(position) ?: Double.POSITIVE_INFINITY)
    val scale = cos(Math.toRadians(position.latitude))
    route.points.zipWithNext().forEachIndexed { index, (start, end) ->
        val east = (end.longitude - start.longitude) * scale
        val north = end.latitude - start.latitude
        val squaredLength = east * east + north * north
        val fraction = if (squaredLength == 0.0) 0.0 else
            (((position.longitude - start.longitude) * scale * east + (position.latitude - start.latitude) * north) / squaredLength).coerceIn(0.0, 1.0)
        val distance = start.interpolate(end, fraction).distanceTo(position)
        val length = start.distanceTo(end)
        if (distance < closest.distanceFromRoad) closest = RouteProgress(index, traveled + fraction * length, distance)
        traveled += length
    }
    return closest
}

fun appendTrackingPose(history: List<Pose>, pose: Pose?, nowNs: Long, startedNs: Long): List<Pose> {
    if (pose == null || !pose.isFresh(nowNs) || pose.timestampNs < startedNs) return history
    val previous = history.lastOrNull()
    if (previous != null && (pose.timestampNs <= previous.timestampNs ||
            pose.source == previous.source && pose.timestampNs - previous.timestampNs < 500_000_000L)) return history
    return (history.takeLast(1199) + pose)
}

fun positionSegments(history: List<Pose>): List<List<GeoPoint>> {
    val segments = mutableListOf<MutableList<GeoPoint>>()
    history.forEachIndexed { index, pose ->
        val previous = history.getOrNull(index - 1)
        if (previous == null || previous.source != pose.source ||
            pose.timestampNs - previous.timestampNs !in 1..3_000_000_000L) segments.add(mutableListOf())
        segments.last().add(pose.point)
    }
    return segments.filter { it.size >= 2 }
}

fun trajectoryDistance(history: List<Pose>): Double = positionSegments(history).sumOf { segment ->
    segment.zipWithNext().sumOf { (previous, current) -> previous.distanceTo(current) }
}

fun recordedPoseAt(history: List<Pose>, timestamp: Long): Pose? {
    if (history.isEmpty() || timestamp !in history.first().timestampNs..history.last().timestampNs) return null
    val insertion = history.binarySearchBy(timestamp) { it.timestampNs }
    if (insertion >= 0) return history[insertion]
    val index = -insertion - 2
    val previous = history[index]
    val next = history[index + 1]
    val interval = next.timestampNs - previous.timestampNs
    if (interval !in 1..3_000_000_000L || previous.source != next.source) return null
    val fraction = (timestamp - previous.timestampNs).toDouble() / interval
    return previous.copy(point = previous.point.interpolate(next.point, fraction), timestampNs = timestamp,
        filterRadius95Meters = listOfNotNull(previous.filterRadius95Meters, next.filterRadius95Meters).maxOrNull())
}
