package com.setu.navigator.data

import java.io.File
import java.io.FileInputStream
import java.nio.ByteBuffer
import java.nio.ByteOrder
import java.nio.channels.FileChannel
import java.nio.charset.CodingErrorAction

object GraphBinary {
    const val MAX_BYTES = 384L * 1024 * 1024
    private val magic = "SETUGR1\n".toByteArray(Charsets.US_ASCII)

    fun read(file: File, checkpoint: () -> Unit = {}): RoadGraph = FileInputStream(file).channel.use { channel ->
        checkpoint()
        require(channel.size() in 20..MAX_BYTES) { "Missing or oversized compiled road graph." }
        val data = channel.map(FileChannel.MapMode.READ_ONLY, 0, channel.size()).order(ByteOrder.LITTLE_ENDIAN)
        require(ByteArray(8).also(data::get).contentEquals(magic)) { "Unsupported compiled road graph." }
        val nodes = data.int
        val edges = data.int
        val nameCount = data.int
        require(nodes in 1..4_000_000 && edges in 1..8_000_000 && nameCount in 1..minOf(edges, 1_200_000)) { "Invalid graph counts." }
        require(20L + nodes * 20L + edges * 24L + nameCount * 4L <= data.limit()) { "Truncated graph arrays." }
        fun section(bytes: Int): ByteBuffer = data.slice().order(ByteOrder.LITTLE_ENDIAN).apply {
            limit(bytes)
            data.position(data.position() + bytes)
        }
        val latitudes = section(nodes * 8).asDoubleBuffer()
        val longitudes = section(nodes * 8).asDoubleBuffer()
        val heads = section(nodes * 4).asIntBuffer()
        val sources = section(edges * 4).asIntBuffer()
        val targets = section(edges * 4).asIntBuffer()
        val next = section(edges * 4).asIntBuffer()
        val lengths = section(edges * 8).asDoubleBuffer()
        val nameIds = section(edges * 4).asIntBuffer()
        val decoder = Charsets.UTF_8.newDecoder().onMalformedInput(CodingErrorAction.REPORT).onUnmappableCharacter(CodingErrorAction.REPORT)
        val names = List(nameCount) {
            if (it % 4096 == 0) checkpoint()
            require(data.remaining() >= 4) { "Truncated graph name." }
            val length = data.int
            require(length in 0..800 && length <= data.remaining()) { "Invalid graph name length." }
            decoder.decode(section(length)).toString().also { require(it.length <= 200) { "Graph name is too long." } }
        }
        require(!data.hasRemaining()) { "Unexpected data after compiled graph." }
        var linkedEdges = 0
        for (node in 0 until nodes) {
            if (node % 4096 == 0) checkpoint()
            require(latitudes[node].isFinite() && latitudes[node] in -90.0..90.0 &&
                longitudes[node].isFinite() && longitudes[node] in -180.0..180.0) { "Invalid graph coordinate." }
            var edge = heads[node]
            require(edge in -1 until edges) { "Invalid graph adjacency head." }
            while (edge >= 0) {
                if (linkedEdges % 4096 == 0) checkpoint()
                require(sources[edge] == node && targets[edge] in 0 until nodes && next[edge] in -1 until edge &&
                    lengths[edge].isFinite() && lengths[edge] in 0.0..21_000_000.0 && nameIds[edge] in 0 until nameCount) { "Invalid graph edge." }
                linkedEdges++
                edge = next[edge]
            }
        }
        require(linkedEdges == edges) { "Compiled graph has unlinked edges." }
        RoadGraph(latitudes, longitudes, heads, sources, targets, next, lengths, nameIds, names)
    }
}
