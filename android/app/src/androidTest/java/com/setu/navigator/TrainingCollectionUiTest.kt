package com.setu.navigator

import androidx.compose.ui.test.*
import androidx.compose.ui.test.junit4.v2.createAndroidComposeRule
import androidx.lifecycle.ViewModelProvider
import androidx.test.ext.junit.runners.AndroidJUnit4
import com.setu.navigator.data.Trip
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith
import java.util.UUID

@RunWith(AndroidJUnit4::class)
class TrainingCollectionUiTest {
    @get:Rule val compose = createAndroidComposeRule<MainActivity>()

    @Test
    fun trainingControlsExplainCollectionAndRequireExplicitExport() {
        val model = ViewModelProvider(compose.activity)[SetuViewModel::class.java]
        check(!model.recording.value)
        compose.onNodeWithTag("tab-Record").performClick()
        compose.onNodeWithTag("fixed-mount").performScrollTo().assertIsOff().performClick().assertIsOn()
        compose.onNodeWithTag("record-toggle").assertIsDisplayed()
        val trip = Trip(UUID.randomUUID().toString(), "Training UI fixture", 0, 1000, 0.0, 0, emptyList())
        compose.runOnIdle { model.selectedTrip = trip; model.overlay = "trip" }
        compose.onNodeWithTag("export-training").performScrollTo().performClick()
        compose.onNodeWithText("Export location and sensor data?").assertIsDisplayed()
        compose.onNodeWithText("Cancel").performClick()
        compose.onNodeWithTag("export-training").assertIsDisplayed()
        compose.runOnIdle { model.selectedTrip = null; model.overlay = null }
    }
}
