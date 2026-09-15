package com.setu.navigator

import android.Manifest
import android.os.Build
import android.os.Bundle
import android.view.WindowManager
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.activity.result.contract.ActivityResultContracts
import androidx.lifecycle.ViewModelProvider
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.lifecycleScope
import androidx.lifecycle.repeatOnLifecycle
import com.setu.navigator.ui.SetuApp
import kotlinx.coroutines.launch

class MainActivity : ComponentActivity() {
    private lateinit var model: SetuViewModel
    private var afterPermission: (() -> Unit)? = null
    private val permissionRequest = registerForActivityResult(ActivityResultContracts.RequestMultiplePermissions()) {
        model.refreshPermissions()
        if (model.hasLocationPermission) afterPermission?.invoke()
        else model.notify("Precise location is off. Offline maps and demo replay are still available.")
        afterPermission = null
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        enableEdgeToEdge()
        model = ViewModelProvider(this)[SetuViewModel::class.java]
        lifecycleScope.launch {
            repeatOnLifecycle(Lifecycle.State.STARTED) {
                try {
                    model.recording.collect { recording ->
                        if (recording) window.addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
                        else window.clearFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
                    }
                } finally {
                    window.clearFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
                }
            }
        }
        setContent {
            SetuApp(model) { action ->
                val needsSteps = model.settings.value.vehicle == "Walking" && !model.repository.hub.hasStepPermission()
                if (model.hasLocationPermission && !needsSteps) action()
                else {
                    afterPermission = action
                    val permissions = mutableListOf(Manifest.permission.ACCESS_FINE_LOCATION, Manifest.permission.ACCESS_COARSE_LOCATION)
                    if (Build.VERSION.SDK_INT >= 33) permissions.add(Manifest.permission.POST_NOTIFICATIONS)
                    if (Build.VERSION.SDK_INT >= 29 && needsSteps) permissions.add(Manifest.permission.ACTIVITY_RECOGNITION)
                    permissionRequest.launch(permissions.toTypedArray())
                }
            }
        }
    }

    override fun onStart() {
        super.onStart()
        if (::model.isInitialized) {
            model.repository.uiVisible = true
            model.refreshPermissions()
        }
    }

    override fun onStop() {
        if (::model.isInitialized) {
            model.repository.uiVisible = false
            if (!model.recording.value) model.repository.hub.stop()
        }
        super.onStop()
    }
}
