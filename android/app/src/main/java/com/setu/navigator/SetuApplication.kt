package com.setu.navigator

import android.app.Application
import com.setu.navigator.data.SetuRepository
import org.maplibre.android.MapLibre

class SetuApplication : Application() {
    val repository by lazy { SetuRepository(this) }
    override fun onCreate() {
        super.onCreate()
        MapLibre.getInstance(this)
    }
}
