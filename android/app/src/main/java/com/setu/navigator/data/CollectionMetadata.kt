package com.setu.navigator.data

import android.content.Context
import android.hardware.Sensor
import android.hardware.SensorManager
import android.os.Build
import com.setu.navigator.BuildConfig
import com.setu.navigator.model.OnDeviceModelProvider
import org.json.JSONArray
import org.json.JSONObject
import java.util.UUID

object CollectionMetadata {
    fun create(context: Context, sessionId: String, settings: AppSettings, fixedMount: Boolean): JSONObject {
        val preferences = context.getSharedPreferences("setu-collection", Context.MODE_PRIVATE)
        val installation = preferences.getString("installation", null) ?: UUID.randomUUID().toString().also {
            check(preferences.edit().putString("installation", it).commit()) { "Could not save collection identity." }
        }
        val manager = context.getSystemService(SensorManager::class.java)
        val sensors = JSONArray()
        listOf(Sensor.TYPE_ACCELEROMETER, Sensor.TYPE_GYROSCOPE, Sensor.TYPE_MAGNETIC_FIELD,
            Sensor.TYPE_ROTATION_VECTOR, Sensor.TYPE_GAME_ROTATION_VECTOR, Sensor.TYPE_PRESSURE, Sensor.TYPE_STEP_DETECTOR).forEach { type ->
            manager.getDefaultSensor(type)?.let { sensor ->
                sensors.put(JSONObject().put("type", type).put("name", sensor.name).put("vendor", sensor.vendor)
                    .put("version", sensor.version).put("resolution", sensor.resolution)
                    .put("maximumRange", sensor.maximumRange).put("minDelayUs", sensor.minDelay))
            }
        }
        return JSONObject().put("schema", "setu.collection.v1").put("sessionId", sessionId)
            .put("installationId", installation).put("vehicle", settings.vehicle)
            .put("walkingStepLengthMeters", settings.walkingStepLengthMeters)
            .put("mount", if (fixedMount) "fixed" else "unconfirmed")
            .put("appVersion", BuildConfig.VERSION_NAME).put("appVersionCode", BuildConfig.VERSION_CODE)
            .put("androidApi", Build.VERSION.SDK_INT).put("sensors", sensors)
            .put("frame", "phone_body").put("accelerationUnits", "m/s^2 including gravity")
            .put("gyroscopeUnits", "rad/s").put("nativePositioning", settings.nativePositioning)
            .put("localModelEnabled", settings.onDeviceSpeedModel && settings.vehicle != "Walking" &&
                OnDeviceModelProvider.supportsVehicle(context, settings.vehicle))
            .put("remoteSharingEnabled", settings.vehicle != "Walking" && settings.modelSharingAllowed && !settings.onDeviceSpeedModel)
            .put("modelBundle", context.assets.open("models/setu-speed-v1/manifest.json").bufferedReader().use { JSONObject(it.readText()) })
    }
}
