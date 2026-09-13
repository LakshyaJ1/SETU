package com.setu.navigator

import com.setu.navigator.model.canonicalModelSpec
import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
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
