package com.setu.navigator.data

import android.util.JsonReader
import android.util.JsonToken
import org.json.JSONArray
import org.json.JSONObject
import java.io.InputStream

internal object MapJson {
    fun objectValue(reader: JsonReader): JSONObject {
        var values = 0
        fun read(depth: Int): Any {
            require(depth <= 16 && ++values <= 3_000_000) { "A map record is too large or deeply nested." }
            return when (reader.peek()) {
                JsonToken.BEGIN_OBJECT -> JSONObject().apply {
                    reader.beginObject()
                    while (reader.hasNext()) {
                        val name = reader.nextName()
                        require(!has(name)) { "Duplicate map JSON field." }
                        put(name, read(depth + 1))
                    }
                    reader.endObject()
                }
                JsonToken.BEGIN_ARRAY -> JSONArray().apply {
                    reader.beginArray()
                    while (reader.hasNext()) put(read(depth + 1))
                    reader.endArray()
                }
                JsonToken.STRING -> reader.nextString()
                JsonToken.NUMBER -> reader.nextString().let { it.toLongOrNull() ?: it.toDouble().also { number -> require(number.isFinite()) } }
                JsonToken.BOOLEAN -> reader.nextBoolean()
                JsonToken.NULL -> { reader.nextNull(); JSONObject.NULL }
                else -> error("Invalid map JSON.")
            }
        }
        require(reader.peek() == JsonToken.BEGIN_OBJECT) { "A map record needs an object." }
        return read(2) as JSONObject
    }

    fun skip(reader: JsonReader, depth: Int = 1) {
        require(depth <= 16) { "Map JSON is nested too deeply." }
        when (reader.peek()) {
            JsonToken.BEGIN_OBJECT -> { reader.beginObject(); while (reader.hasNext()) { reader.nextName(); skip(reader, depth + 1) }; reader.endObject() }
            JsonToken.BEGIN_ARRAY -> { reader.beginArray(); while (reader.hasNext()) skip(reader, depth + 1); reader.endArray() }
            JsonToken.STRING, JsonToken.NUMBER -> reader.nextString()
            JsonToken.BOOLEAN -> reader.nextBoolean()
            JsonToken.NULL -> reader.nextNull()
            else -> error("Invalid map JSON.")
        }
    }

    fun graph(input: InputStream, checkpoint: () -> Unit = {}): RoadGraph = JsonReader(input.bufferedReader()).use { reader ->
        var nodeCount: Int? = null
        var edgeCount: Int? = null
        var graph: RoadGraph? = null
        val fields = mutableSetOf<String>()
        reader.beginObject()
        while (reader.hasNext()) {
            val field = reader.nextName()
            require(fields.add(field)) { "Duplicate map JSON field." }
            when (field) {
                "nodeCount", "edgeCount" -> {
                    require(graph == null && reader.peek() == JsonToken.NUMBER) { "Graph counts must precede roads and be integers." }
                    val count = reader.nextInt()
                    if (field == "nodeCount") nodeCount = count else edgeCount = count
                }
                "roads" -> {
                    require((nodeCount == null) == (edgeCount == null)) { "Supply both indexed graph counts." }
                    val builder = RoadGraph.Builder(nodeCount, edgeCount)
                    var ways = LongArray(1024)
                    var wayCount = 0
                    var references = 0
                    reader.beginArray()
                    while (reader.hasNext()) {
                        if (wayCount % 1024 == 0) checkpoint()
                        val road = objectValue(reader)
                        require(wayCount < 1_200_000) { "Too many road IDs." }
                        if (wayCount == ways.size) ways = ways.copyOf(minOf(1_200_000, wayCount * 2))
                        ways[wayCount++] = identifier(road.get("id"))
                        val identifiers = road.getJSONArray("nodes")
                        val coordinates = road.getJSONArray("coordinates")
                        require(identifiers.length() in 2..10000 && identifiers.length() == coordinates.length())
                        references += identifiers.length()
                        require(references <= 6_000_000) { "This graph has too many road references." }
                        builder.road(LongArray(identifiers.length()) { identifier(identifiers.get(it)) },
                            List(coordinates.length()) { index -> point(coordinates.getJSONArray(index)) },
                            road.optString("name", "Local road"), road.optString("oneway", "no"))
                    }
                    reader.endArray()
                    ways.sort(0, wayCount)
                    require((1 until wayCount).all { ways[it] != ways[it - 1] }) { "Duplicate road ID." }
                    graph = builder.build()
                }
                else -> skip(reader)
            }
        }
        reader.endObject()
        require(reader.peek() == JsonToken.END_DOCUMENT) { "Unexpected data after map JSON." }
        requireNotNull(graph) { "The map has no road graph." }
    }

    fun point(values: JSONArray): GeoPoint {
        require(values.length() == 2 && values.get(0) is Number && values.get(1) is Number) { "Map coordinates must be longitude, latitude pairs." }
        return GeoPoint(values.getDouble(1), values.getDouble(0))
    }

    private fun identifier(value: Any): Long {
        require(value is Int || value is Long) { "Road and node IDs must be integers." }
        return (value as Number).toLong()
    }
}
