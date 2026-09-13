package com.setu.navigator

import com.setu.navigator.data.SearchScratch
import org.junit.Assert.*
import org.junit.Test
import kotlin.random.Random

/**
 * The A* working memory that replaced three dense node-count arrays.
 *
 * On the bundled Delhi/NCR graph those arrays were 25.5 MB + 12.7 MB + 12.7 MB per search attempt,
 * and a route runs up to three attempts, so the old form allocated ~153 MB of short-lived heap and
 * reliably threw OutOfMemoryError next to MapLibre. These tests pin the behaviour the replacement
 * has to preserve: absent nodes read as unvisited, relax keeps the cheaper cost, the table survives
 * rehashing, and the frontier pops in priority order.
 */
class SearchScratchTest {

    @Test
    fun absentNodesReadAsUnvisited() {
        val scratch = SearchScratch(1_000)
        assertEquals(Double.POSITIVE_INFINITY, scratch.costOf(0), 0.0)
        assertEquals(Double.POSITIVE_INFINITY, scratch.costOf(999), 0.0)
        assertEquals(-1, scratch.previousEdgeOf(42))
        assertEquals(-1, scratch.rootOf(42))
        assertTrue(scratch.frontierIsEmpty())
        assertEquals(Double.POSITIVE_INFINITY, scratch.peekPriority(), 0.0)
    }

    @Test
    fun relaxKeepsTheCheapestCostAndItsProvenance() {
        val scratch = SearchScratch(1_000)
        assertTrue(scratch.relax(7, 10.0, previousEdge = 3, root = 1))
        assertEquals(10.0, scratch.costOf(7), 0.0)
        assertEquals(3, scratch.previousEdgeOf(7))
        assertEquals(1, scratch.rootOf(7))

        assertFalse("a worse cost must not overwrite", scratch.relax(7, 12.0, 9, 2))
        assertEquals(10.0, scratch.costOf(7), 0.0)
        assertEquals(3, scratch.previousEdgeOf(7))

        assertTrue(scratch.relax(7, 4.0, 9, 2))
        assertEquals(4.0, scratch.costOf(7), 0.0)
        assertEquals(9, scratch.previousEdgeOf(7))
        assertEquals(2, scratch.rootOf(7))
        assertEquals(1, scratch.settledNodes)
    }

    @Test
    fun tableSurvivesGrowthAndRehashing() {
        // Well past the initial 8,192 slots, so several rehashes happen mid-test.
        val scratch = SearchScratch(400_000)
        val count = 60_000
        for (node in 0 until count) {
            assertTrue(scratch.relax(node * 7, node.toDouble(), node, node % 5))
        }
        assertEquals(count, scratch.settledNodes)
        for (node in 0 until count) {
            assertEquals("node $node", node.toDouble(), scratch.costOf(node * 7), 0.0)
            assertEquals(node, scratch.previousEdgeOf(node * 7))
            assertEquals(node % 5, scratch.rootOf(node * 7))
        }
        // Anything never inserted must still read as unvisited after all that rehashing.
        assertEquals(Double.POSITIVE_INFINITY, scratch.costOf(count * 7 + 1), 0.0)
    }

    @Test
    fun frontierPopsInPriorityOrder() {
        val scratch = SearchScratch(10_000)
        val random = Random(19)
        val priorities = List(2_000) { random.nextDouble(0.0, 1_000.0) }
        priorities.forEachIndexed { index, priority -> scratch.push(index, priority * 2, priority) }

        var previous = Double.NEGATIVE_INFINITY
        var popped = 0
        while (!scratch.frontierIsEmpty()) {
            val peeked = scratch.peekPriority()
            scratch.pop()
            assertTrue("heap order broken at $popped", peeked >= previous - 1e-12)
            assertEquals(peeked * 2, scratch.poppedCost, 1e-9)
            previous = peeked
            popped++
        }
        assertEquals(priorities.size, popped)
        assertEquals(priorities.size.toLong(), scratch.expansions)
    }

    @Test
    fun resetClearsVisitedAndFrontierButKeepsCapacity() {
        val scratch = SearchScratch(50_000)
        for (node in 0 until 20_000) scratch.relax(node, node.toDouble(), node, 0)
        for (node in 0 until 500) scratch.push(node, 1.0, 1.0)

        scratch.reset()
        assertEquals(0, scratch.settledNodes)
        assertTrue(scratch.frontierIsEmpty())
        assertEquals(Double.POSITIVE_INFINITY, scratch.costOf(11), 0.0)
        assertEquals(-1, scratch.rootOf(11))

        // Reusable across the route's three attempts.
        assertTrue(scratch.relax(11, 5.0, 1, 0))
        assertEquals(5.0, scratch.costOf(11), 0.0)
    }

    @Test
    fun expansionsAccumulateAcrossResetsSoOneRouteStaysBounded() {
        val scratch = SearchScratch(10_000)
        repeat(3) {
            for (node in 0 until 100) scratch.push(node, 1.0, node.toDouble())
            while (!scratch.frontierIsEmpty()) scratch.pop()
            scratch.reset()
        }
        assertEquals(300L, scratch.expansions)
        assertTrue("the guard must be reachable", SearchScratch.MAX_EXPANSIONS > 0)
    }
}
