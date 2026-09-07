package com.setu.navigator

import androidx.test.platform.app.InstrumentationRegistry
import org.json.JSONObject
import java.io.ByteArrayOutputStream
import java.security.MessageDigest
import java.util.zip.ZipEntry
import java.util.zip.ZipOutputStream

internal object MapPackFixture {
    fun documents(): MutableMap<String, JSONObject> = listOf("manifest.json", "city.geojson", "roads.json").associateWith { name ->
        JSONObject(InstrumentationRegistry.getInstrumentation().context.assets.open("map-fixture/$name").bufferedReader().use { it.readText() })
    }.toMutableMap()

    fun bytes(documents: Map<String, JSONObject> = documents(), alterManifest: (JSONObject) -> Unit = {}): ByteArray {
        val files = documents.mapValues { it.value.toString().toByteArray() }.toMutableMap()
        val manifest = JSONObject(documents.getValue("manifest.json").toString())
        manifest.put("sha256", JSONObject().apply { listOf("city.geojson", "roads.json").forEach { put(it, sha256(files.getValue(it))) } })
        alterManifest(manifest)
        files["manifest.json"] = manifest.toString().toByteArray()
        return zip(files)
    }

    fun zip(files: Map<String, ByteArray>): ByteArray = ByteArrayOutputStream().also { output ->
        ZipOutputStream(output).use { archive -> files.forEach { (name, bytes) ->
            archive.putNextEntry(ZipEntry(name)); archive.write(bytes); archive.closeEntry()
        } }
    }.toByteArray()

    fun sha256(bytes: ByteArray): String = MessageDigest.getInstance("SHA-256").digest(bytes).joinToString("") { "%02x".format(it) }
}
