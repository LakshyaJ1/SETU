# SETU — phone QA and GPS-withheld report

**Development evidence, not release approval.**

APK SHA-256: `410ca8d79d42780b3cb1c33c0d569c093e1216b257d9c2ccd10dc56e9a8db62b`

120 s GPS warmup; 10 Hz ticks in [0, duration); missing estimates count as failures

Withheld phone GNSS, not independent surveyed ground truth

## Requested outage durations

| Duration | Within 10 m / expected | Joint success | Available | Reference | RMSE / p90, m |
| --- | ---: | ---: | ---: | ---: | ---: |
| 10 s | 285 / 2600 | 10.96% | 377 | 1613 | 5.94 / 10.21 |
| 20 s | 183 / 4800 | 3.81% | 342 | 2575 | 9.31 / 19.50 |
| 30 s | 408 / 6900 | 5.91% | 457 | 3995 | 4.65 / 8.44 |
| 40 s | 232 / 8000 | 2.90% | 445 | 4826 | 10.25 / 19.75 |
| 50 s | 130 / 10000 | 1.30% | 190 | 5878 | 5.68 / 11.43 |
| 90 s | 91 / 14400 | 0.63% | 164 | 7958 | 2.96 / 1.51 |

## Matched prefixes of the same 90-second outages

| Duration | Within 10 m / expected | Joint success | Available | Reference | RMSE / p90, m |
| --- | ---: | ---: | ---: | ---: | ---: |
| 10 s | 91 / 1600 | 5.69% | 164 | 688 | 2.96 / 1.51 |
| 20 s | 91 / 3200 | 2.84% | 164 | 1661 | 2.96 / 1.51 |
| 30 s | 91 / 4800 | 1.90% | 164 | 2644 | 2.96 / 1.51 |
| 40 s | 91 / 6400 | 1.42% | 164 | 3634 | 2.96 / 1.51 |
| 50 s | 91 / 8000 | 1.14% | 164 | 4509 | 2.96 / 1.51 |
| 90 s | 91 / 14400 | 0.63% | 164 | 7958 | 2.96 / 1.51 |

## Non-overlapping phases of 90-second outages

| Duration | Within 10 m / expected | Joint success | Available | Reference | RMSE / p90, m |
| --- | ---: | ---: | ---: | ---: | ---: |
| 0–10 s | 91 / 1600 | 5.69% | 164 | 688 | 2.96 / 1.51 |
| 10–20 s | 0 / 1600 | 0.00% | 0 | 973 | Unavailable / Unavailable |
| 20–30 s | 0 / 1600 | 0.00% | 0 | 983 | Unavailable / Unavailable |
| 30–40 s | 0 / 1600 | 0.00% | 0 | 990 | Unavailable / Unavailable |
| 40–50 s | 0 / 1600 | 0.00% | 0 | 875 | Unavailable / Unavailable |
| 50–90 s | 0 / 6400 | 0.00% | 0 | 3449 | Unavailable / Unavailable |

## Limits

- Three same-phone/day development rides with unconfirmed mounts
- Duration runs have different cycle counts; matched prefixes use 90 s runs
- Ticks and duration prefixes are correlated, not independent trials
- Conditional errors exclude missing predictions; joint success does not
- Missing references are unknown: joint success is a verified lower bound
- Low errors on rare outputs do not prove long-outage tracking
- Physical Location-off continuity is not a moving accuracy experiment

## Physical Location-off check

No independent moving reference; continuity only, not navigation accuracy

| Checkpoint | Location enabled | New paired IMU samples | Sensor age, ms | Native position |
| --- | --- | ---: | ---: | --- |
| 10 s | False | 2000 | 102.0 | False |
| 20 s | False | 2000 | 90.6 | False |
| 30 s | False | 2000 | 80.2 | False |
| 40 s | False | 2000 | 70.3 | False |
| 50 s | False | 1980 | 60.5 | False |
| 90 s | False | 8000 | 21.4 | False |

## Build and user-flow checks

| Check | Result | Detail |
| --- | --- | --- |
| APK identity | PASS | 212,472,310 bytes; signature and 16 KiB alignment verified; installed app and website HTTP download match SHA-256. |
| Python regressions | PASS | 265 passed, 2 skipped in 229.86 s. Skips require optional osmium. One ReportLab deprecation warning. |
| Android JVM tests | PASS | 102 tests, zero failures/errors/skips. Unit tests and both APK builds succeed in 64 s. |
| Android lint | WARN | Zero errors, 25 existing warnings. Final separate lint invocation succeeds in 75 s; an earlier slow invocation was cancelled. |
| Latest phone inventory | PASS | 84 discovered methods completed on the latest APK: 77 passed, 7 controlled/opt-in fixtures skipped, zero failures/errors. Each method uses a fresh instrumentation process without clearing user data. The six-duration replay runs separately with selected private rides. |
| User recording preservation | PASS | All 37 original SETULOG files remain byte-identical after the final complete device run. Only test-owned fixtures are removed. |
| Foreground screen wake | PASS | Production FLAG_KEEP_SCREEN_ON is asserted during recording and released after Stop. The 38.035-second physical foreground regression passes without a test-forced screen flag. |
| Normal-radio sensor capture | PASS | Latest 30-second foreground and 15-second background checks pass with Location enabled and Battery saver disabled. Maximum IMU gaps are 5.009 and 5.006 ms. These do not supersede the all-radios-off background failures. |
| Baseline focused phone tests | PASS | On the preceding aee9c570 build: 11 passed, 1 controlled-native-GNSS fixture skipped. Includes map rendering, settings, recording and curved native demo. |
| Baseline repeated journeys | PASS | Five demo/theme/settings/trips cycles in one process; baseline PSS 276,405-605,640 KiB; focused repeat 587,855-619,599 KiB. Both below unchanged 716,800 KiB cap. |
| Latest repeated journeys | PASS | Five journeys in the latest APK remain below the unchanged 716,800 KiB cap: PSS 609,280; 613,850; 612,414; 475,666; 608,178 KiB. |
| Compact map controls | PASS | The latest APK passes the new 8.665-second regression: all three map controls remain below the header and above attribution. |
| Native/model integrity | PASS | All nine packaged native-library and model files match the preceding APK byte-for-byte. The six-duration replay is repeated against the latest APK and yields the same counts. |
| Real Location-off continuity | PASS | 90-second actual OS switch test; fresh paired IMU at all six checkpoints. No initialized native position or independent moving reference. |
| Beta website | PASS | Desktop and 360/390 px layouts, keyboard focus, reduced motion, denied clipboard, malformed release metadata, actual APK download and PDF HTTP checks. Local hosting only. |
| Background capture | FAIL | With Location and internet off, baseline background probes stall even with Battery saver off and battery exemptions enabled. A normal 45.71-second background recording has a 15.95-second IMU gap. Keep SETU visible; background capture is not certified. |
| 90% within 10 m | FAIL | All six GPS-withheld replay durations fail the target. Availability itself is too low. This is development data, not independent field validation. |

## Findings and remaining work

- The original combined 81-test run has four retained failures: two Compose-root lifecycle failures, a 1,854,612 KiB map-memory reading against a 716,800 KiB ceiling, and an obsolete straight-chord assertion for the curved demo.
- Use fresh instrumentation processes per method without clearing user data. Isolated focused tests and a five-cycle actual app soak pass; this supports fixture/process accumulation as a contributor, not a proof that every long app session is leak-free.
- The curved-demo test now sums travelled distance along the path. Its travelled-distance and under-5-m synthetic error guards remain unchanged. No production estimator guard or model weight is relaxed.
- Compact map controls were covered by attribution and initial loading feedback sat behind the task sheet. The latest APK reserves visible map space, lays compact controls out horizontally, and shows loading feedback in that visible area.
- The latest APK keeps the screen on only during visible recording and releases that flag on stop/background. This is a foreground mitigation, not a claim that screen-off recording is reliable.
- Background probes with Location, Wi-Fi and mobile data off stalled for 412,991 ms, and 155,377 ms with Battery saver disabled; foreground recovery was used for cleanup. A special-use service candidate also failed and was reverted. The normal app independently shows a roughly 15.95-second sensor gap in a 45.71-second background interval. These failures remain disclosed with their source APKs.
- Replay now scores exactly duration-times-10 ticks, excludes the GPS recovery boundary and compares position with the reference at the scoring timestamp. Missing predictions count as failures; missing references remain unknown, not successes.
- The HTML regression test permits only the intentional trusted sweep script and rejects route-name script injection. The beta publisher rejects mismatched evidence, retains the preceding release after failure and optionally watches verified artifacts every 30 seconds.
- Three same-phone/day scooter rides cannot establish independent accuracy. Repeated ticks are correlated. Conditional low errors on rare surviving estimates are not whole-outage accuracy. All matched ninety-second-cohort predictions cease after ten seconds.
- Sustained GPS-free navigation and heading initialization remain release blockers. The earlier CPU-trained model still predicts motion at rest and remains research-only. Collect rigid-mount, multi-day rides with independent position reference before making accuracy claims.

## Device test inventory

### baseline-all-device-tests.log

Runner completed: True. Counts: {'skipped': 7, 'failed': 4, 'passed': 70}.

| Test | Result | Detail |
| --- | --- | --- |
| `AndroidWorkflowTest.liveNativePositioningConsumesAndroidSensorsAndRecordsSeparateOutput` | skipped | org.junit.AssumptionViolatedException: Requires a controlled live GNSS/heading fixture; opt in with -e nativeGnssFixture true. |
| `AndroidWorkflowTest.offlineJourneyAndSettingsRemainUsable` | failed | java.lang.IllegalStateException: No compose hierarchies found in the app. Possible reasons include: (1) the Activity that calls setContent did not launch; (2) setContent was not called; (3) setContent was called before the ComposeTestRule ran. If setContent is called by the Activity, make sure the Activity is launched after the ComposeTestRule runs |
| `AndroidWorkflowTest.presentationDemoShowsNativeLossRecoveryAndSurvivesRecreation` | failed | java.lang.IllegalStateException: No compose hierarchies found in the app. Possible reasons include: (1) the Activity that calls setContent did not launch; (2) setContent was not called; (3) setContent was called before the ComposeTestRule ran. If setContent is called by the Activity, make sure the Activity is launched after the ComposeTestRule runs |
| `AndroidWorkflowTest.liveTrackingFollowsMockFixesRecordsAndSavesWithoutADestination` | passed |  |
| `AndroidWorkflowTest.missingMeasuredAndStaleGpsStayDistinct` | passed |  |
| `AndroidWorkflowTest.sensorSubscriptionsCanBeRepeatedlyStoppedAndRestarted` | passed |  |
| `AndroidWorkflowTest.regionalMapsInstallSwitchRouteRejectAndRemove` | passed |  |
| `CompiledRoadGraphTest.pythonCompiledFixtureMatchesJsonRoutesAndOneWaySemantics` | passed |  |
| `CompiledRoadGraphTest.ncrColdAndWarmRoutesUseMappedGraphAndRecoverCorruptCacheWithoutJsonParsing` | passed |  |
| `GnssObservationTest.duplicateDelayedAndFutureFixesDoNotReplaceLatestOrEnterLog` | passed |  |
| `GnssObservationTest.malformedMeasurementMetadataIsRejected` | passed |  |
| `GnssObservationTest.invalidOrOrphanMeasurementsCannotBecomeObservations` | passed |  |
| `GnssObservationTest.optionalMeasurementsPreserveMissingAndMeasuredZero` | passed |  |
| `GnssObservationTest.legacyZeroMeasurementsAreUnknownAndNonzeroValuesSurvive` | passed |  |
| `LocationLifecycleTest.coldStartWithLocationOffObservesReenableWithoutRestart` | passed |  |
| `MapPackStoreTest.invalidGeometryMetadataAndGraphAreRejected` | passed |  |
| `MapPackStoreTest.includedNcrUsesBoundedLocalVectorTiles` | passed |  |
| `MapPackStoreTest.corruptInstalledMapCannotActivateAndRestoresFallback` | passed |  |
| `MapPackStoreTest.installActivateRestoreAndRemovePreserveFallback` | passed |  |
| `MapPackStoreTest.includedNcrCoversCitiesAndRoutesShahdaraToMait` | passed |  |
| `MapPackStoreTest.revisionsNeverSilentlyReplaceOrDowngrade` | passed |  |
| `MapPackStoreTest.directDownloadChecksHashAndDoesNotActivateAutomatically` | passed |  |
| `MapPackStoreTest.badArchivesAndChecksumsLeaveNoInstalledFiles` | passed |  |
| `MapPackStoreTest.cancellationKeepsThePreviousMapAndCleansStaging` | passed |  |
| `MapPackStoreTest.failedDownloadsNeverInstallOrFollowRedirects` | passed |  |
| `MapRenderingTest.ncrTilesRenderAcrossZoomsAndRepeatedMapDisposalWithoutHeapGrowth` | failed | java.lang.AssertionError: Map renderer memory is not bounded: 1854612 KiB |
| `MapRenderingTest.plannedNcrRouteRemainsRenderedWhenFollowingAndChangingTheme` | passed |  |
| `ModelConsentTest.legacyFlagDoesNotAuthorizeUploadsAndChangingServersRevokesConsent` | passed |  |
| `ModelProviderTest.unavailableRetainsReasonRatherThanPretendingTheVehicleStopped` | passed |  |
| `ModelProviderTest.malformedAndOutOfWindowMeasurementsAreRejected` | passed |  |
| `ModelProviderTest.cancellingADownloadDoesNotWaitForTheReadTimeout` | passed |  |
| `ModelProviderTest.healthPreservesExperimentalWarningAndInferenceContainsNoLocation` | passed |  |
| `ModelProviderTest.urlAndWindowValidationHappenBeforeNetworkTraffic` | passed |  |
| `ModelProviderTest.redirectsOversizedResponsesAndUnknownHealthAreRejected` | passed |  |
| `NativeEngineTest.stationaryUncalibratedVehicleDoesNotRunIndefinitely` | passed |  |
| `NativeEngineTest.horizontalVelocityUpdateDoesNotInventVerticalSpeed` | passed |  |
| `NativeEngineTest.rapidPhoneRotationClearsVehicleMountAndRequiresFreshAlignment` | passed |  |
| `NativeEngineTest.magneticDeclinationMatchesPublishedNoaaWmm2025Examples` | passed |  |
| `NativeEngineTest.pendingFixDoesNotResetTheFilterAndOutageEventuallyWithholdsOutput` | passed |  |
| `NativeEngineTest.measuredStopWithoutCourseUsesItsSpeedUncertainty` | passed |  |
| `NativeEngineTest.delayedCorrectionsMatchOnTimePropagationAndGeographicDisplacement` | passed |  |
| `NativeEngineTest.gapsWithholdTheEstimateAndRequireNewAlignmentInputs` | passed |  |
| `NativeEngineTest.nonCarProfileKeepsRawRotationButNeverBorrowsCarConstraintsOrOutageBudget` | passed |  |
| `NativeEngineTest.learnedSpeedRejectsFutureDuplicateAndStaleMeasurements` | passed |  |
| `NativeEngineTest.initializationNeedsHeadingAndMissingAltitudeDoesNotBecomeSeaLevel` | passed |  |
| `NativeEngineTest.gatesAndInvalidTimestampsDoNotMoveTheState` | passed |  |
| `NativeFilterTest.matchesPythonAcrossPropagationAndEveryMeasurementChannel` | passed |  |
| `NativeFilterTest.invalidSamplesDoNotCorruptStateAndClosedHandlesAreSafe` | passed |  |
| `OfflineMapTest.outOfCoverageOriginIsRejected` | passed |  |
| `OfflineMapTest.includedDestinationsHaveDrivableRoutes` | passed |  |
| `OfflineTilesTest.missingTruncatedAndSameSizeCorruptTilesAreRepairedDespiteACompleteMarker` | passed |  |
| `OnDeviceModelProviderTest.actualPackagedModelRunsLocallyButUnapprovedPredictionsCannotFuse` | passed |  |
| `PhysicalRecordingTest.actualImuRecordingContinuesInForegroundWithoutLocationOrModelSharing` | passed |  |
| `PhysicalRecordingTest.actualImuRecordingContinuesInBackgroundWithoutLocationOrModelSharing` | passed |  |
| `PositioningDemoTest.nativeEngineTracksThroughWithheldGpsAndAcceptsRecovery` | failed | java.lang.AssertionError |
| `PositioningDemoTest.cancelledPreparationDoesNotContinueGeneratingFrames` | passed |  |
| `ScooterCaptureReviewTest.changingCarToScooterReconfiguresSensorsAndDoesNotStartCarModel` | passed |  |
| `ScooterCaptureReviewTest.exportSelectedRidesAndMeasureIndependentBlackouts` | skipped | org.junit.AssumptionViolatedException: Select existing recordings explicitly; originals are read only. |
| `ScooterCaptureReviewTest.measureLongWarmupBlackoutsWithoutChangingRecordings` | skipped | org.junit.AssumptionViolatedException: Select existing recordings explicitly; originals are read only. |
| `SensorFallbackTest.missingHardwareHeadingAccuracyStillUsesRealSensorPipelineThroughTurns` | passed |  |
| `SensorFallbackTest.capturedPhysicalSensorsCanBeReplayedWithoutLeakingCoordinates` | skipped | org.junit.AssumptionViolatedException: got: <false>, expected: is <true> |
| `SensorFallbackTest.nativePositionsPublishAtTenHertzDuringGpsAndSensorOnlySegments` | passed |  |
| `SensorFallbackTest.gpsMotionCalibratesThroughAccelerationAndTurnsWithoutACompassHeading` | passed |  |
| `SensorFallbackTest.coldStartWithoutGpsNeverInventsAnAbsolutePosition` | passed |  |
| `SensorFallbackTest.disturbedMagnetometerDoesNotBypassHeadingChecks` | passed |  |
| `TrainingCollectionTest.phoneRecordsAndExportsPortableTrainingBundle` | passed |  |
| `TrainingCollectionTest.gpsReferenceChangesCannotLeakIntoTheWithheldTrajectory` | passed |  |
| `TrainingCollectionTest.shadowReplayWorksAcrossRebootsAndReportsMissingHeadingHonestly` | passed |  |
| `TrainingCollectionUiTest.trainingControlsExplainCollectionAndRequireExplicitExport` | passed |  |
| `TripStoreTest.malformedImportsLeaveNoOrphanFiles` | passed |  |
| `TripStoreTest.importExportAndDeleteRoundTrip` | passed |  |
| `TripStoreTest.recordedTrajectoryRetainsInertialPointsAndUncertaintySeparatelyFromRawGps` | passed |  |
| `TripStoreTest.invalidTrajectoryUncertaintyAndUnknownStreamsAreRejected` | passed |  |
| `TripStoreTest.optionalMeasurementsSurviveImportAndStoredMetadata` | passed |  |
| `TripStoreTest.activeRecordingIsNotRecovered` | passed |  |
| `TripStoreTest.interruptedFinalRecordIsRecoveredAndExportsCleanly` | passed |  |
| `WalkingIntegrationTest.physicalWalkingProfileRecordsImuWithoutRunningCarModel` | passed |  |
| `WalkingIntegrationTest.physicalWalkingEstimateSurvivesGpsOffAtRest` | skipped | org.junit.AssumptionViolatedException: got: <false>, expected: is <true> |
| `WalkingIntegrationTest.replayCapturedStepBatchesWithRecordedInitialHeading` | skipped | org.junit.AssumptionViolatedException: Opt in with a captured walking recording ID. |
| `WalkingIntegrationTest.syntheticPlatformCallbacksUseStepsAndWithholdWithoutPermission` | passed |  |
| `WalkingIntegrationTest.replayPrivateWalkingRecordingsChecksTheUncalibratedCeiling` | skipped | org.junit.AssumptionViolatedException: Opt in with existing recording IDs; originals are read only. |

Suite APK SHA-256: `aee9c5706879a44790b62d4347df75e6bbe3366e08c1d564e6d4fa437a208d5b`

### actual-location-off.log

Runner completed: True. Counts: {'passed': 1}.

| Test | Result | Detail |
| --- | --- | --- |
| `LocationOffDurationTest.realSensorsContinueForNinetySecondsWithSystemLocationOff` | passed |  |

Suite APK SHA-256: `aee9c5706879a44790b62d4347df75e6bbe3366e08c1d564e6d4fa437a208d5b`

### latest-six-duration-replay.log

Runner completed: True. Counts: {'passed': 1}.

| Test | Result | Detail |
| --- | --- | --- |
| `ScooterCaptureReviewTest.measureLongWarmupBlackoutsWithoutChangingRecordings` | passed |  |

Suite APK SHA-256: `410ca8d79d42780b3cb1c33c0d569c093e1216b257d9c2ccd10dc56e9a8db62b`

### internet-location-off-recording.log

Runner completed: True. Counts: {'passed': 1, 'failed': 1}.

| Test | Result | Detail |
| --- | --- | --- |
| `PhysicalRecordingTest.actualImuRecordingContinuesInForegroundWithoutLocationOrModelSharing` | passed |  |
| `PhysicalRecordingTest.actualImuRecordingContinuesInBackgroundWithoutLocationOrModelSharing` | failed | java.lang.AssertionError: Process was suspended for 412991 ms |

Suite APK SHA-256: `aee9c5706879a44790b62d4347df75e6bbe3366e08c1d564e6d4fa437a208d5b`

### internet-location-off-no-saver.log

Runner completed: True. Counts: {'passed': 1, 'failed': 1}.

| Test | Result | Detail |
| --- | --- | --- |
| `PhysicalRecordingTest.actualImuRecordingContinuesInForegroundWithoutLocationOrModelSharing` | passed |  |
| `PhysicalRecordingTest.actualImuRecordingContinuesInBackgroundWithoutLocationOrModelSharing` | failed | java.lang.AssertionError: Process was suspended for 155377 ms |

Suite APK SHA-256: `aee9c5706879a44790b62d4347df75e6bbe3366e08c1d564e6d4fa437a208d5b`

### special-use-background.log

Runner completed: True. Counts: {'failed': 1}.

| Test | Result | Detail |
| --- | --- | --- |
| `PhysicalRecordingTest.actualImuRecordingContinuesInBackgroundWithoutLocationOrModelSharing` | failed | java.lang.AssertionError: Process was suspended for 159940 ms |

Suite APK SHA-256: `bf4ec19ae8b6aff661e9dc5653373f093310e046de77d0399163cd1bf33f0475`

### Isolated device test methods

Runner completed: True. Counts: {'skipped': 7, 'passed': 77}.

| Test | Result | Detail |
| --- | --- | --- |
| `AndroidWorkflowTest.liveNativePositioningConsumesAndroidSensorsAndRecordsSeparateOutput` | skipped | org.junit.AssumptionViolatedException: Requires a controlled live GNSS/heading fixture; opt in with -e nativeGnssFixture true. |
| `AndroidWorkflowTest.offlineJourneyAndSettingsRemainUsable` | passed |  |
| `AndroidWorkflowTest.presentationDemoShowsNativeLossRecoveryAndSurvivesRecreation` | passed |  |
| `AndroidWorkflowTest.liveTrackingFollowsMockFixesRecordsAndSavesWithoutADestination` | passed |  |
| `AndroidWorkflowTest.missingMeasuredAndStaleGpsStayDistinct` | passed |  |
| `AndroidWorkflowTest.sensorSubscriptionsCanBeRepeatedlyStoppedAndRestarted` | passed |  |
| `AndroidWorkflowTest.regionalMapsInstallSwitchRouteRejectAndRemove` | passed |  |
| `AndroidWorkflowTest.repeatedDemoAndThemeJourneysKeepMemoryBounded` | passed |  |
| `AndroidWorkflowTest.compactMapControlsStayAboveTheDriveSheet` | passed |  |
| `CompiledRoadGraphTest.pythonCompiledFixtureMatchesJsonRoutesAndOneWaySemantics` | passed |  |
| `CompiledRoadGraphTest.ncrColdAndWarmRoutesUseMappedGraphAndRecoverCorruptCacheWithoutJsonParsing` | passed |  |
| `GnssObservationTest.duplicateDelayedAndFutureFixesDoNotReplaceLatestOrEnterLog` | passed |  |
| `GnssObservationTest.malformedMeasurementMetadataIsRejected` | passed |  |
| `GnssObservationTest.invalidOrOrphanMeasurementsCannotBecomeObservations` | passed |  |
| `GnssObservationTest.optionalMeasurementsPreserveMissingAndMeasuredZero` | passed |  |
| `GnssObservationTest.legacyZeroMeasurementsAreUnknownAndNonzeroValuesSurvive` | passed |  |
| `LocationLifecycleTest.coldStartWithLocationOffObservesReenableWithoutRestart` | passed |  |
| `LocationOffDurationTest.realSensorsContinueForNinetySecondsWithSystemLocationOff` | passed |  |
| `MapPackStoreTest.invalidGeometryMetadataAndGraphAreRejected` | passed |  |
| `MapPackStoreTest.includedNcrUsesBoundedLocalVectorTiles` | passed |  |
| `MapPackStoreTest.corruptInstalledMapCannotActivateAndRestoresFallback` | passed |  |
| `MapPackStoreTest.installActivateRestoreAndRemovePreserveFallback` | passed |  |
| `MapPackStoreTest.includedNcrCoversCitiesAndRoutesShahdaraToMait` | passed |  |
| `MapPackStoreTest.revisionsNeverSilentlyReplaceOrDowngrade` | passed |  |
| `MapPackStoreTest.directDownloadChecksHashAndDoesNotActivateAutomatically` | passed |  |
| `MapPackStoreTest.badArchivesAndChecksumsLeaveNoInstalledFiles` | passed |  |
| `MapPackStoreTest.cancellationKeepsThePreviousMapAndCleansStaging` | passed |  |
| `MapPackStoreTest.failedDownloadsNeverInstallOrFollowRedirects` | passed |  |
| `MapRenderingTest.ncrTilesRenderAcrossZoomsAndRepeatedMapDisposalWithoutHeapGrowth` | passed |  |
| `MapRenderingTest.plannedNcrRouteRemainsRenderedWhenFollowingAndChangingTheme` | passed |  |
| `ModelConsentTest.legacyFlagDoesNotAuthorizeUploadsAndChangingServersRevokesConsent` | passed |  |
| `ModelProviderTest.unavailableRetainsReasonRatherThanPretendingTheVehicleStopped` | passed |  |
| `ModelProviderTest.malformedAndOutOfWindowMeasurementsAreRejected` | passed |  |
| `ModelProviderTest.cancellingADownloadDoesNotWaitForTheReadTimeout` | passed |  |
| `ModelProviderTest.healthPreservesExperimentalWarningAndInferenceContainsNoLocation` | passed |  |
| `ModelProviderTest.urlAndWindowValidationHappenBeforeNetworkTraffic` | passed |  |
| `ModelProviderTest.redirectsOversizedResponsesAndUnknownHealthAreRejected` | passed |  |
| `NativeEngineTest.stationaryUncalibratedVehicleDoesNotRunIndefinitely` | passed |  |
| `NativeEngineTest.horizontalVelocityUpdateDoesNotInventVerticalSpeed` | passed |  |
| `NativeEngineTest.rapidPhoneRotationClearsVehicleMountAndRequiresFreshAlignment` | passed |  |
| `NativeEngineTest.magneticDeclinationMatchesPublishedNoaaWmm2025Examples` | passed |  |
| `NativeEngineTest.pendingFixDoesNotResetTheFilterAndOutageEventuallyWithholdsOutput` | passed |  |
| `NativeEngineTest.measuredStopWithoutCourseUsesItsSpeedUncertainty` | passed |  |
| `NativeEngineTest.delayedCorrectionsMatchOnTimePropagationAndGeographicDisplacement` | passed |  |
| `NativeEngineTest.gapsWithholdTheEstimateAndRequireNewAlignmentInputs` | passed |  |
| `NativeEngineTest.nonCarProfileKeepsRawRotationButNeverBorrowsCarConstraintsOrOutageBudget` | passed |  |
| `NativeEngineTest.learnedSpeedRejectsFutureDuplicateAndStaleMeasurements` | passed |  |
| `NativeEngineTest.initializationNeedsHeadingAndMissingAltitudeDoesNotBecomeSeaLevel` | passed |  |
| `NativeEngineTest.gatesAndInvalidTimestampsDoNotMoveTheState` | passed |  |
| `NativeFilterTest.matchesPythonAcrossPropagationAndEveryMeasurementChannel` | passed |  |
| `NativeFilterTest.invalidSamplesDoNotCorruptStateAndClosedHandlesAreSafe` | passed |  |
| `OfflineMapTest.outOfCoverageOriginIsRejected` | passed |  |
| `OfflineMapTest.includedDestinationsHaveDrivableRoutes` | passed |  |
| `OfflineTilesTest.missingTruncatedAndSameSizeCorruptTilesAreRepairedDespiteACompleteMarker` | passed |  |
| `OnDeviceModelProviderTest.actualPackagedModelRunsLocallyButUnapprovedPredictionsCannotFuse` | passed |  |
| `PhysicalRecordingTest.actualImuRecordingContinuesInForegroundWithoutLocationOrModelSharing` | passed |  |
| `PhysicalRecordingTest.actualImuRecordingContinuesInBackgroundWithoutLocationOrModelSharing` | passed |  |
| `PositioningDemoTest.nativeEngineTracksThroughWithheldGpsAndAcceptsRecovery` | passed |  |
| `PositioningDemoTest.cancelledPreparationDoesNotContinueGeneratingFrames` | passed |  |
| `ScooterCaptureReviewTest.changingCarToScooterReconfiguresSensorsAndDoesNotStartCarModel` | passed |  |
| `ScooterCaptureReviewTest.exportSelectedRidesAndMeasureIndependentBlackouts` | skipped | org.junit.AssumptionViolatedException: Select existing recordings explicitly; originals are read only. |
| `ScooterCaptureReviewTest.measureLongWarmupBlackoutsWithoutChangingRecordings` | skipped | org.junit.AssumptionViolatedException: Select existing recordings explicitly; originals are read only. |
| `SensorFallbackTest.missingHardwareHeadingAccuracyStillUsesRealSensorPipelineThroughTurns` | passed |  |
| `SensorFallbackTest.capturedPhysicalSensorsCanBeReplayedWithoutLeakingCoordinates` | skipped | org.junit.AssumptionViolatedException: got: <false>, expected: is <true> |
| `SensorFallbackTest.nativePositionsPublishAtTenHertzDuringGpsAndSensorOnlySegments` | passed |  |
| `SensorFallbackTest.gpsMotionCalibratesThroughAccelerationAndTurnsWithoutACompassHeading` | passed |  |
| `SensorFallbackTest.coldStartWithoutGpsNeverInventsAnAbsolutePosition` | passed |  |
| `SensorFallbackTest.disturbedMagnetometerDoesNotBypassHeadingChecks` | passed |  |
| `TrainingCollectionTest.phoneRecordsAndExportsPortableTrainingBundle` | passed |  |
| `TrainingCollectionTest.gpsReferenceChangesCannotLeakIntoTheWithheldTrajectory` | passed |  |
| `TrainingCollectionTest.shadowReplayWorksAcrossRebootsAndReportsMissingHeadingHonestly` | passed |  |
| `TrainingCollectionUiTest.trainingControlsExplainCollectionAndRequireExplicitExport` | passed |  |
| `TripStoreTest.malformedImportsLeaveNoOrphanFiles` | passed |  |
| `TripStoreTest.importExportAndDeleteRoundTrip` | passed |  |
| `TripStoreTest.recordedTrajectoryRetainsInertialPointsAndUncertaintySeparatelyFromRawGps` | passed |  |
| `TripStoreTest.invalidTrajectoryUncertaintyAndUnknownStreamsAreRejected` | passed |  |
| `TripStoreTest.optionalMeasurementsSurviveImportAndStoredMetadata` | passed |  |
| `TripStoreTest.activeRecordingIsNotRecovered` | passed |  |
| `TripStoreTest.interruptedFinalRecordIsRecoveredAndExportsCleanly` | passed |  |
| `WalkingIntegrationTest.physicalWalkingProfileRecordsImuWithoutRunningCarModel` | passed |  |
| `WalkingIntegrationTest.physicalWalkingEstimateSurvivesGpsOffAtRest` | skipped | org.junit.AssumptionViolatedException: got: <false>, expected: is <true> |
| `WalkingIntegrationTest.replayCapturedStepBatchesWithRecordedInitialHeading` | skipped | org.junit.AssumptionViolatedException: Opt in with a captured walking recording ID. |
| `WalkingIntegrationTest.syntheticPlatformCallbacksUseStepsAndWithholdWithoutPermission` | passed |  |
| `WalkingIntegrationTest.replayPrivateWalkingRecordingsChecksTheUncalibratedCeiling` | skipped | org.junit.AssumptionViolatedException: Opt in with existing recording IDs; originals are read only. |

Suite APK SHA-256: `410ca8d79d42780b3cb1c33c0d569c093e1216b257d9c2ccd10dc56e9a8db62b`

