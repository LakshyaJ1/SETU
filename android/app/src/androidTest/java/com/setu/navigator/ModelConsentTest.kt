package com.setu.navigator

import android.content.Context
import android.content.ContextWrapper
import androidx.test.core.app.ApplicationProvider
import com.setu.navigator.data.SetuRepository
import org.junit.Assert.*
import org.junit.Test
import java.io.File
import java.util.UUID

class ModelConsentTest {
    @Test
    fun legacyFlagDoesNotAuthorizeUploadsAndChangingServersRevokesConsent() {
        val base = ApplicationProvider.getApplicationContext<Context>()
        val namespace = "model-consent-${UUID.randomUUID()}"
        val directory = File(base.cacheDir, namespace).apply { mkdirs() }
        val isolated = object : ContextWrapper(base) {
            override fun getFilesDir() = File(directory, "files").apply { mkdirs() }
            override fun getCacheDir() = File(directory, "cache").apply { mkdirs() }
            override fun getSharedPreferences(name: String, mode: Int) = base.getSharedPreferences("$namespace-$name", mode)
        }
        val preferences = isolated.getSharedPreferences("setu-settings", Context.MODE_PRIVATE)
        preferences.edit().putBoolean("modelSharingAllowed", true).putBoolean("onDeviceSpeedModel", false).commit()
        val repository = SetuRepository(isolated)
        assertFalse(repository.settings.value.modelSharingAllowed)
        assertNull(repository.hub.modelSession)
        repository.updateSettings(repository.settings.value.copy(modelSharingAllowed = true))
        assertTrue(repository.settings.value.modelSharingAllowed)
        assertEquals("Ready for recording", repository.modelInference.value.status)
        assertNull(repository.hub.modelSession)
        val restarted = SetuRepository(isolated)
        assertTrue(restarted.settings.value.modelSharingAllowed)
        assertEquals("Ready for recording", restarted.modelInference.value.status)
        assertNull(restarted.hub.modelSession)
        repository.updateSettings(repository.settings.value.copy(theme = "Dark"))
        assertTrue(repository.settings.value.modelSharingAllowed)
        repository.updateSettings(repository.settings.value.copy(modelEndpoint = "https://example.invalid"))
        assertFalse(repository.settings.value.modelSharingAllowed)
        assertEquals("Sharing off", repository.modelInference.value.status)
        assertEquals(0, preferences.getInt("modelSharingConsentVersion", -1))
        assertNull(repository.hub.modelSession)
    }
}
