package com.setu.navigator

import com.setu.navigator.model.canonicalModelSpec
import com.setu.navigator.model.modelFusionApproved
import com.setu.navigator.model.modelSupportsVehicle
import com.setu.navigator.model.validateModelInputSpec
import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Assert.assertFalse
import org.junit.Assert.assertThrows
import org.junit.Test
import java.io.File
import java.security.MessageDigest

/**
 * The on-device runtime refuses to load a bundle whose input spec does not hash to the value the
 * trainer recorded (`docs/05` §5.2), so a trainer/runtime disagreement fails loudly at startup
 * instead of quietly producing a wrong speed.
 *
 * That check is only as good as the canonicalisation behind it. The trainer used
 * `json.dumps(spec, sort_keys=True)` (`notebooks/kaggle_train.py`), whose defaults put ", " between
 * items and ": " after a key; a runtime that omits those spaces computes a different hash and the
 * model never loads. This exercises the shipping function against the manifest actually in assets,
 * so the two cannot drift apart unnoticed.
 */
class OnDeviceModelSpecTest {
    @Test fun unsupportedActivityDoesNotStartTheCarModel() {
        val manifest = JSONObject().put("vehicles", org.json.JSONArray(listOf("Car")))
        assertTrue(modelSupportsVehicle(manifest, "Car"))
        assertFalse(modelSupportsVehicle(manifest, "Two-wheeler"))
        assertFalse(modelSupportsVehicle(manifest, "Walking"))
        assertFalse(modelSupportsVehicle(JSONObject().put("vehicles", org.json.JSONArray()), "Car"))
    }

    @Test
    fun fusionRequiresDeploymentApprovalAndPassingCalibration() {
        val manifest = manifest()
        val calibration = JSONObject(File("src/main/assets/models/setu-speed-v1/calibration.json").readText())
        assertFalse(modelFusionApproved(manifest, calibration))
        manifest.put("deployment_approved", true)
        assertFalse(modelFusionApproved(manifest, calibration))
        calibration.put("gate_g4_pass", true)
        assertFalse(modelFusionApproved(manifest, calibration))
        calibration.getJSONObject("test_coverage").put("3_sigma", 0.98)
        assertTrue(modelFusionApproved(manifest, calibration))
        calibration.remove("test_coverage")
        assertFalse(modelFusionApproved(manifest, calibration))
    }

    @Test
    fun changedInputContractsAreRejectedEvenIfSelfConsistent() {
        validateModelInputSpec(manifest().getJSONObject("input_spec"))
        val reordered = manifest().getJSONObject("input_spec")
        reordered.getJSONArray("channels").put(0, "gyro_x")
        assertThrows(IllegalArgumentException::class.java) { validateModelInputSpec(reordered) }
        val wrongUnits = manifest().getJSONObject("input_spec")
        wrongUnits.getJSONObject("units").put("gyro", "deg/s")
        assertThrows(IllegalArgumentException::class.java) { validateModelInputSpec(wrongUnits) }
        val wrongWindow = manifest().getJSONObject("input_spec").put("window_samples", 200)
        assertThrows(IllegalArgumentException::class.java) { validateModelInputSpec(wrongWindow) }
    }

    private val manifestFile = File("src/main/assets/models/setu-speed-v1/manifest.json")

    private fun manifest(): JSONObject {
        assertTrue("model bundle missing from assets at ${manifestFile.absolutePath}", manifestFile.exists())
        return JSONObject(manifestFile.readText())
    }

    @Test
    fun shippedManifestHashesToItsDeclaredValue() {
        val manifest = manifest()
        val computed = MessageDigest.getInstance("SHA-256")
            .digest(canonicalModelSpec(manifest.getJSONObject("input_spec")).toByteArray(Charsets.UTF_8))
            .joinToString("") { "%02x".format(it) }
        assertEquals(manifest.getString("input_spec_sha256"), computed)
    }

    @Test
    fun canonicalFormUsesPythonSeparators() {
        val spec = JSONObject().put("b", 2).put("a", "x")
        assertEquals("""{"a": "x", "b": 2}""", canonicalModelSpec(spec))
    }

    @Test
    fun theContractMatchesWhatTheAppCollects() {
        val spec = manifest().getJSONObject("input_spec")
        assertEquals(6, spec.getJSONArray("channels").length())
        assertEquals("phone_body", spec.getString("frame"))
        assertEquals(400, spec.getInt("window_samples"))
        assertEquals(100.0, spec.getDouble("canonical_rate_hz"), 0.0)
        assertEquals(4.0, spec.getDouble("window_seconds"), 0.0)
    }

    @Test
    fun theBundleDoesNotClaimDeploymentApproval() {
        // The trainer recorded this as false: 3-sigma coverage is 96.3 % against a 98 % bar. If a
        // future bundle flips it, that should be a deliberate decision with evidence behind it,
        // not something that slips in with a file copy.
        assertEquals(false, manifest().optBoolean("deployment_approved", false))
    }
}
