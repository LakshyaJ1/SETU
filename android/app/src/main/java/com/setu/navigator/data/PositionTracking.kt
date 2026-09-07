package com.setu.navigator.data

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
