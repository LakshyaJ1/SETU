package com.setu.navigator.data

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.Service
import android.content.Intent
import android.content.pm.ServiceInfo
import android.os.Build
import android.os.IBinder
import android.os.PowerManager
import com.setu.navigator.MainActivity
import com.setu.navigator.R
import com.setu.navigator.SetuApplication
import kotlinx.coroutines.*
import kotlinx.coroutines.flow.drop

class RecordingService : Service() {
    private val repository get() = (application as SetuApplication).repository
    private var wakeLock: PowerManager.WakeLock? = null
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.Main.immediate)

    override fun onCreate() {
        super.onCreate()
        getSystemService(NotificationManager::class.java).createNotificationChannel(
            NotificationChannel("recording", "Drive recording", NotificationManager.IMPORTANCE_LOW)
        )
        scope.launch {
            repository.recording.drop(1).collect { active ->
                if (!active) { stopForeground(STOP_FOREGROUND_REMOVE); stopSelf() }
            }
        }
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        if (intent?.action == "STOP") {
            repository.finishRecording()
            stopForeground(STOP_FOREGROUND_REMOVE)
            stopSelf()
            return START_NOT_STICKY
        }
        if (!repository.hub.hasLocationPermission()) {
            stopSelf()
            return START_NOT_STICKY
        }
        val open = PendingIntent.getActivity(this, 0, Intent(this, MainActivity::class.java), PendingIntent.FLAG_IMMUTABLE)
        val stop = PendingIntent.getService(this, 1, Intent(this, RecordingService::class.java).setAction("STOP"), PendingIntent.FLAG_IMMUTABLE)
        val notification = Notification.Builder(this, "recording").setSmallIcon(R.drawable.ic_setu_notification)
            .setContentTitle("SETU is recording your drive")
            .setContentText("Saved locally. Optional model sharing follows your settings.")
            .setContentIntent(open).setOngoing(true)
            .addAction(Notification.Action.Builder(null, "Stop & save", stop).build()).build()
        if (Build.VERSION.SDK_INT >= 29) startForeground(100, notification, ServiceInfo.FOREGROUND_SERVICE_TYPE_LOCATION)
        else startForeground(100, notification)
        if (wakeLock == null) {
            wakeLock = getSystemService(PowerManager::class.java).newWakeLock(PowerManager.PARTIAL_WAKE_LOCK, "setu:recording")
                .apply { acquire(6 * 60 * 60 * 1000L) }
        }
        try {
            repository.beginRecording(intent?.getStringExtra("name") ?: "My drive")
        } catch (error: Exception) {
            repository.reportError("Recording could not start: ${error.message}. Check available phone storage.")
            stopForeground(STOP_FOREGROUND_REMOVE)
            stopSelf()
        }
        return START_NOT_STICKY
    }

    override fun onDestroy() {
        scope.cancel()
        repository.finishRecording()
        if (!repository.uiVisible) repository.hub.stop()
        wakeLock?.let { if (it.isHeld) it.release() }
        wakeLock = null
        super.onDestroy()
    }

    override fun onBind(intent: Intent?): IBinder? = null
}
