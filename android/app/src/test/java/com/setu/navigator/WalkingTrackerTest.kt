package com.setu.navigator

import com.setu.navigator.data.GeoPoint
import com.setu.navigator.data.Pose
import com.setu.navigator.estimation.WalkingTracker
import com.setu.navigator.estimation.navigationPose
import org.junit.Assert.*
import org.junit.Test
import kotlin.math.cos
import kotlin.math.sin

class WalkingTrackerTest {
    private val start = 1_000_000_000L
    private val origin = GeoPoint(28.7, 77.2)
    private fun fix(timestamp: Long = start) = Pose(origin, 0.0, accuracyMeters = 3.0, timestampNs = timestamp, mock = true)
    private fun rotation(degrees: Double, pitch: Double = 0.0): DoubleArray {
        val angle = Math.toRadians(degrees)
        val tilt = Math.toRadians(pitch)
        return doubleArrayOf(cos(angle), sin(angle) * cos(tilt), -sin(angle) * sin(tilt),
            -sin(angle), cos(angle) * cos(tilt), -cos(angle) * sin(tilt), 0.0, sin(tilt), cos(tilt))
    }

    private inner class Trial(length: Double = .7) {
        val tracker = WalkingTracker(length)
        var time = start
        var heading = 0.0
        var pitch = 0.0
        init {
            tracker.gnss(fix())
            tracker.imu(time, DoubleArray(3))
            tracker.rotation(time, rotation(0.0))
            tracker.align(time, rotation(0.0), .2)
        }
        fun advance(samples: Int = 25, turn: Double = 0.0, tilt: Double = 0.0) {
            repeat(samples) {
                time += 20_000_000L
                heading += turn / samples
                pitch += tilt / samples
                tracker.imu(time, doubleArrayOf(Math.toRadians(tilt / samples) / .02, 0.0, -Math.toRadians(turn / samples) / .02))
                tracker.rotation(time, rotation(heading, pitch))
            }
        }
        fun pose() = checkNotNull(tracker.estimate(time).pose)
        fun step() { advance(); assertTrue(tracker.step(time)) }
    }

    @Test fun stationaryForThirtySecondsNeverInventsSpeedOrDistance() {
        val trial = Trial()
        trial.advance(1500)
        assertEquals(origin, trial.pose().point)
        assertEquals(0.0, trial.pose().speedMps!!, 0.0)
        assertEquals(0L, trial.tracker.steps)
        assertTrue(trial.pose().mock == true)
    }

    @Test fun hundredDegreeTurnChangesHeadingNotSpeedAndStopSettles() {
        val trial = Trial()
        repeat(4) { trial.step() }
        assertEquals(1.4, trial.pose().speedMps!!, 1e-8)
        val beforeTurn = trial.pose().point
        trial.advance(50, 100.0)
        assertEquals(beforeTurn, trial.pose().point)
        assertEquals(100.0, trial.pose().bearing!!, 1e-6)
        trial.advance(26)
        assertEquals(0.0, trial.pose().speedMps!!, 0.0)
        assertTrue(trial.tracker.step(trial.time))
        assertTrue(trial.pose().point.longitude > beforeTurn.longitude)
        assertTrue(trial.pose().point.latitude < beforeTurn.latitude)
    }

    @Test fun outAndBackClosesAndCalibrationChangesDistance() {
        val trial = Trial(.8)
        repeat(12) { trial.step() }
        assertEquals(9.6, origin.distanceTo(trial.pose().point), .02)
        trial.advance(50, 180.0)
        repeat(12) { trial.step() }
        assertTrue(origin.distanceTo(trial.pose().point) < .01)
        assertEquals(24L, trial.tracker.steps)
    }

    @Test fun duplicateStaleAndPreAnchorStepsCannotAdvance() {
        val trial = Trial()
        assertFalse(trial.tracker.step(start))
        trial.step()
        val after = trial.pose().point
        assertFalse(trial.tracker.step(trial.time))
        assertFalse(trial.tracker.step(trial.time - 1))
        trial.advance(150)
        assertFalse(trial.tracker.step(trial.time - 2_100_000_000L))
        assertEquals(after, trial.pose().point)
        assertEquals(1L, trial.tracker.steps)
    }

    @Test fun delayedStepUsesHistoricalHeadingRatherThanNewHeading() {
        val trial = Trial()
        trial.advance()
        val stepTime = trial.time
        trial.advance(25, 100.0)
        assertTrue(trial.tracker.step(stepTime))
        assertEquals(origin.longitude, trial.pose().point.longitude, 1e-8)
        assertTrue(trial.pose().point.latitude > origin.latitude)
    }

    @Test fun unmatchedRotationAndSensorGapRequireNewGps() {
        for (gap in listOf(false, true)) {
            val trial = Trial()
            if (gap) trial.tracker.imu(trial.time + 200_000_000L, DoubleArray(3))
            else trial.tracker.rotation(trial.time + 20_000_000L, rotation(100.0))
            trial.time += 220_000_000L
            trial.tracker.rotation(trial.time, rotation(100.0))
            trial.tracker.align(trial.time, rotation(100.0), .2)
            assertNull(trial.tracker.estimate(trial.time).pose)
            assertFalse(trial.tracker.step(trial.time))
        }
    }

    @Test fun freshGpsWinsAndExpiredWalkingPositionIsWithheld() {
        val trial = Trial()
        trial.step()
        assertEquals(fix(), navigationPose(fix(), trial.tracker.estimate(trial.time), true, trial.time))
        trial.advance(6000)
        assertNull(trial.tracker.estimate(trial.time).pose)
        assertFalse(trial.tracker.step(trial.time))
    }

    @Test fun lateGpsCannotRewindStepsAndInvalidCalibrationIsRejected() {
        val trial = Trial()
        trial.step()
        val before = trial.pose().point
        trial.tracker.gnss(fix(trial.time - 1))
        assertEquals(before, trial.pose().point)
        for (length in listOf(Double.NaN, 0.0, 20.0)) {
            assertThrows(IllegalArgumentException::class.java) { WalkingTracker(length) }
        }
    }

    @Test fun laterRealFixCannotEraseMockAlignmentProvenance() {
        val trial = Trial()
        trial.advance()
        trial.tracker.gnss(fix(trial.time).copy(mock = false))
        assertTrue(trial.pose().mock == true)
    }

    @Test fun batchedStepsPreserveCountsWithoutMillisecondSpeedSpikes() {
        val trial = Trial()
        repeat(2) {
            trial.advance(100)
            repeat(3) { index -> assertTrue(trial.tracker.step(trial.time + index * 1_000_000L)) }
            trial.advance(1)
        }
        assertEquals(6L, trial.tracker.steps)
        assertEquals(0L, trial.tracker.rejectedSteps)
        assertEquals(4.2, origin.distanceTo(trial.pose().point), .02)
        assertEquals(1.05, trial.pose().speedMps!!, .03)
        trial.advance(125)
        assertTrue(trial.pose().speedMps!! > 0)
        trial.advance(35)
        assertEquals(0.0, trial.pose().speedMps!!, 0.0)
    }

    @Test fun normalPitchThroughVerticalDoesNotEraseGpsOrYaw() {
        val trial = Trial()
        trial.advance(50, tilt = 90.0)
        assertEquals(origin, trial.pose().point)
        assertEquals(0.0, trial.pose().bearing!!, 1e-6)
        trial.advance(50, turn = 100.0)
        assertEquals(100.0, trial.pose().bearing!!, 1e-6)
        trial.advance(50, tilt = -90.0)
        assertEquals(100.0, trial.pose().bearing!!, 1e-6)
        trial.step()
        assertTrue(trial.pose().point.longitude > origin.longitude)
    }

    @Test fun aLeadingRotationCallbackDoesNotHideAnAvailableHistoricalHeading() {
        val trial = Trial()
        trial.advance()
        trial.tracker.rotation(trial.time + 20_000_000L, rotation(0.0))
        assertNotNull(trial.tracker.estimate(trial.time).pose)
    }

    @Test fun implausibleStepEventFloodWithholdsRatherThanClampingSpeed() {
        val trial = Trial()
        trial.advance()
        repeat(16) { index -> assertTrue(trial.tracker.step(trial.time + index * 1_000_000L)) }
        assertFalse(trial.tracker.step(trial.time + 16_000_000L))
        assertNull(trial.tracker.estimate(trial.time + 20_000_000L).pose)
    }
}
