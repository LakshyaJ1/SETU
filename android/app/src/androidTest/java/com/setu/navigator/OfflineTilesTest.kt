package com.setu.navigator

import android.content.ContextWrapper
import android.net.Uri
import android.os.SystemClock
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import com.setu.navigator.data.MapPackStore
import com.setu.navigator.data.OfflineMap
import org.json.JSONObject
import org.junit.After
import org.junit.Assert.*
import org.junit.Test
import org.junit.runner.RunWith
import java.io.File
import java.io.RandomAccessFile
import java.util.UUID

@RunWith(AndroidJUnit4::class)
class OfflineTilesTest {
    private val base = InstrumentationRegistry.getInstrumentation().targetContext
    private val directory = File(base.cacheDir, "tile-integrity-${UUID.randomUUID()}").apply { mkdirs() }
    private val context = object : ContextWrapper(base) {
        override fun getFilesDir() = File(directory, "files").apply { mkdirs() }
        override fun getCacheDir() = File(directory, "cache").apply { mkdirs() }
    }

    @After
    fun cleanup() { directory.deleteRecursively() }

    @Test
    fun missingTruncatedAndSameSizeCorruptTilesAreRepairedDespiteACompleteMarker() {
        val region = MapPackStore(context).regions.value.single { it.id == "delhi" }
        val maps = OfflineMap(context, region)
        val started = SystemClock.elapsedRealtime()
        val template = maps.citySource().getJSONArray("tiles").getString(0)
        val tile = File(requireNotNull(Uri.parse(template.replace("{z}", "13").replace("{x}", "5852").replace("{y}", "3415")).path))
        assertTrue(tile.canonicalPath.startsWith(context.filesDir.canonicalPath + File.separator))
        assertFalse(context.cacheDir.resolve("vector-maps").exists())
        val original = tile.readBytes()
        val root = tile.parentFile!!.parentFile!!.parentFile!!
        assertTrue(File(root, "complete").isFile)
        assertTrue(tile.delete())
        maps.citySource()
        assertArrayEquals(original, tile.readBytes())
        tile.writeBytes(original.copyOf(16))
        maps.citySource()
        assertArrayEquals(original, tile.readBytes())
        RandomAccessFile(tile, "rw").use { it.writeByte(original[0].toInt() xor 255) }
        assertEquals(original.size.toLong(), tile.length())
        maps.citySource()
        assertArrayEquals(original, tile.readBytes())
        assertEquals(11159, root.walkTopDown().count { it.extension == "pbf" })
        val warmStarted = SystemClock.elapsedRealtime()
        maps.citySource()
        val result = JSONObject().put("scenario", "Full NCR tile extraction and deleted/truncated/same-size-corruption repair")
            .put("totalMs", SystemClock.elapsedRealtime() - started).put("verifiedWarmOpenMs", SystemClock.elapsedRealtime() - warmStarted)
            .put("tiles", 11159).put("persistentStorage", true).put("repairs", 3)
        File(base.getExternalFilesDir(null), "verification").apply { mkdirs() }.resolve("tile-integrity-metrics.json").writeText(result.toString(2))
    }
}
