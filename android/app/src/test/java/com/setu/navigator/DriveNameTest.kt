package com.setu.navigator

import com.setu.navigator.data.defaultDriveName
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import java.util.Calendar

/**
 * Every recording used to be created as "Position tracking", so the Trips list showed a column of
 * identical rows and could not be read at a glance. The default name now says when the drive
 * happened, which is what a person would have written themselves.
 */
class DriveNameTest {

    private fun at(hour: Int): Long = Calendar.getInstance().apply {
        set(Calendar.HOUR_OF_DAY, hour)
        set(Calendar.MINUTE, 30)
        set(Calendar.SECOND, 0)
    }.timeInMillis

    @Test
    fun namesFollowTheTimeOfDay() {
        assertEquals("Morning drive", defaultDriveName(at(5)))
        assertEquals("Morning drive", defaultDriveName(at(9)))
        assertEquals("Afternoon drive", defaultDriveName(at(12)))
        assertEquals("Afternoon drive", defaultDriveName(at(16)))
        assertEquals("Evening drive", defaultDriveName(at(17)))
        assertEquals("Evening drive", defaultDriveName(at(20)))
        assertEquals("Night drive", defaultDriveName(at(21)))
        assertEquals("Night drive", defaultDriveName(at(3)))
    }

    @Test
    fun everyHourProducesANonEmptyName() {
        for (hour in 0..23) {
            val name = defaultDriveName(at(hour))
            assertTrue("hour $hour produced '$name'", name.isNotBlank() && name.endsWith("drive"))
        }
    }
}
