package com.setu.navigator.data

/**
 * Reusable working memory for one [RoadGraph.route] call.
 *
 * The previous implementation allocated `DoubleArray(nodeCount)` plus two `IntArray(nodeCount)`
 * per search attempt. On the bundled Delhi/NCR graph that is 3,185,592 nodes, so 25.5 MB + 12.7 MB
 * + 12.7 MB = ~51 MB, and `route()` runs up to three attempts, so ~153 MB of short-lived Java heap
 * per route. That reliably exhausted the heap next to MapLibre and the mapped graph.
 *
 * A* over a road graph settles only a small fraction of the nodes, so the visited set is stored in
 * an open-addressed table that starts small and grows, and the frontier is a primitive binary heap
 * on parallel arrays instead of a `PriorityQueue` of boxed objects. The same instance is reused by
 * every attempt of a single route.
 */
internal class SearchScratch(private val nodeCount: Int) {

    private var keys = IntArray(INITIAL_CAPACITY)
    private var costs = DoubleArray(INITIAL_CAPACITY)
    private var previousEdges = IntArray(INITIAL_CAPACITY)
    private var roots = IntArray(INITIAL_CAPACITY)
    private var mask = INITIAL_CAPACITY - 1
    private var occupancy = 0
    private var growthThreshold = (INITIAL_CAPACITY * LOAD_FACTOR).toInt()

    private var heapNodes = IntArray(INITIAL_CAPACITY)
    private var heapCosts = DoubleArray(INITIAL_CAPACITY)
    private var heapPriorities = DoubleArray(INITIAL_CAPACITY)
    private var heapSize = 0

    /** Nodes removed from the frontier across every attempt, to bound a pathological query. */
    var expansions = 0L
        private set

    val settledNodes get() = occupancy

    /** Clears the visited set and frontier but keeps the allocated capacity for the next attempt. */
    fun reset() {
        if (occupancy > 0) keys.fill(0)
        occupancy = 0
        heapSize = 0
    }

    // ---------------------------------------------------------------- visited set

    private fun slotOf(node: Int): Int {
        val key = node + 1
        var slot = mix(node) and mask
        while (true) {
            val existing = keys[slot]
            if (existing == 0 || existing == key) return slot
            slot = (slot + 1) and mask
        }
    }

    fun costOf(node: Int): Double {
        val slot = slotOf(node)
        return if (keys[slot] == 0) Double.POSITIVE_INFINITY else costs[slot]
    }

    fun previousEdgeOf(node: Int): Int {
        val slot = slotOf(node)
        return if (keys[slot] == 0) -1 else previousEdges[slot]
    }

    fun rootOf(node: Int): Int {
        val slot = slotOf(node)
        return if (keys[slot] == 0) -1 else roots[slot]
    }

    /** Records [node] if [cost] improves on the value already stored. Returns true when stored. */
    fun relax(node: Int, cost: Double, previousEdge: Int, root: Int): Boolean {
        val slot = slotOf(node)
        if (keys[slot] != 0) {
            if (cost >= costs[slot]) return false
            costs[slot] = cost
            previousEdges[slot] = previousEdge
            roots[slot] = root
            return true
        }
        keys[slot] = node + 1
        costs[slot] = cost
        previousEdges[slot] = previousEdge
        roots[slot] = root
        if (++occupancy >= growthThreshold) grow()
        return true
    }

    private fun grow() {
        val capacity = keys.size
        if (capacity >= maximumCapacity()) {
            // Already large enough to hold every node; linear probing still terminates.
            growthThreshold = Int.MAX_VALUE
            return
        }
        val enlarged = capacity shl 1
        val oldKeys = keys
        val oldCosts = costs
        val oldPrevious = previousEdges
        val oldRoots = roots
        keys = IntArray(enlarged)
        costs = DoubleArray(enlarged)
        previousEdges = IntArray(enlarged)
        roots = IntArray(enlarged)
        mask = enlarged - 1
        growthThreshold = (enlarged * LOAD_FACTOR).toInt()
        for (index in oldKeys.indices) {
            val key = oldKeys[index]
            if (key == 0) continue
            var slot = mix(key - 1) and mask
            while (keys[slot] != 0) slot = (slot + 1) and mask
            keys[slot] = key
            costs[slot] = oldCosts[index]
            previousEdges[slot] = oldPrevious[index]
            roots[slot] = oldRoots[index]
        }
    }

    private fun maximumCapacity(): Int {
        var capacity = INITIAL_CAPACITY
        val target = if (nodeCount >= MAX_TABLE_ENTRIES) MAX_TABLE_ENTRIES else nodeCount + 1
        while (capacity < target && capacity < MAX_TABLE_ENTRIES) capacity = capacity shl 1
        return capacity
    }

    // ---------------------------------------------------------------- frontier

    fun frontierIsEmpty() = heapSize == 0

    fun push(node: Int, cost: Double, priority: Double) {
        if (heapSize == heapNodes.size) {
            val enlarged = heapNodes.size shl 1
            heapNodes = heapNodes.copyOf(enlarged)
            heapCosts = heapCosts.copyOf(enlarged)
            heapPriorities = heapPriorities.copyOf(enlarged)
        }
        var child = heapSize++
        heapNodes[child] = node
        heapCosts[child] = cost
        heapPriorities[child] = priority
        while (child > 0) {
            val parent = (child - 1) shr 1
            if (heapPriorities[parent] <= heapPriorities[child]) break
            swap(parent, child)
            child = parent
        }
    }

    /** Priority of the cheapest entry, or +infinity when the frontier is empty. */
    fun peekPriority(): Double = if (heapSize == 0) Double.POSITIVE_INFINITY else heapPriorities[0]

    var poppedNode = 0
        private set
    var poppedCost = 0.0
        private set

    /** Removes the cheapest entry into [poppedNode] and [poppedCost]. */
    fun pop() {
        poppedNode = heapNodes[0]
        poppedCost = heapCosts[0]
        expansions++
        val last = --heapSize
        if (last > 0) {
            heapNodes[0] = heapNodes[last]
            heapCosts[0] = heapCosts[last]
            heapPriorities[0] = heapPriorities[last]
            var parent = 0
            while (true) {
                val left = parent * 2 + 1
                if (left >= heapSize) break
                val right = left + 1
                val child = if (right < heapSize && heapPriorities[right] < heapPriorities[left]) right else left
                if (heapPriorities[parent] <= heapPriorities[child]) break
                swap(parent, child)
                parent = child
            }
        }
    }

    private fun swap(first: Int, second: Int) {
        val node = heapNodes[first]; heapNodes[first] = heapNodes[second]; heapNodes[second] = node
        val cost = heapCosts[first]; heapCosts[first] = heapCosts[second]; heapCosts[second] = cost
        val priority = heapPriorities[first]; heapPriorities[first] = heapPriorities[second]; heapPriorities[second] = priority
    }

    companion object {
        private const val INITIAL_CAPACITY = 1 shl 13
        private const val LOAD_FACTOR = 0.55
        private const val MAX_TABLE_ENTRIES = 1 shl 23

        /** Bound on nodes settled across one route, so a pathological query fails instead of hanging. */
        const val MAX_EXPANSIONS = 3_000_000L

        private fun mix(value: Int): Int {
            var hash = value * -1640531527 // Fibonacci scrambling; road node ids are dense and ordered.
            hash = hash xor (hash ushr 15)
            return hash and 0x7fffffff
        }
    }
}
