package com.setu.navigator.ui

import android.content.Intent
import android.net.Uri
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.outlined.*
import androidx.compose.material3.*
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.setu.navigator.BuildConfig
import com.setu.navigator.SetuViewModel

/**
 * What SETU is, for someone who has just opened the app.
 *
 * Reached by tapping the wordmark on the Drive screen, which is where a person looks when they want
 * to know what they are using. The previous version opened on "Honest by design" and a disclaimer
 * about what does not work yet; a person meeting the app for the first time needs the idea before
 * the caveats, so the limits now sit at the end under a heading that says what they are.
 */
@Composable
fun AboutScreen(model: SetuViewModel) {
    val context = LocalContext.current
    val maps by model.activeMap.collectAsStateWithLifecycle()
    val scheme = MaterialTheme.colorScheme
    Column(
        Modifier.fillMaxSize().verticalScroll(rememberScrollState()).navigationBarsPadding()
    ) {
        PageHeader("About", onBack = { model.overlay = null })

        // --- the name ---------------------------------------------------------------------------
        Column(
            Modifier.fillMaxWidth().padding(horizontal = 24.dp),
            horizontalAlignment = Alignment.CenterHorizontally,
        ) {
            Surface(
                shape = SetuShape.hero,
                color = scheme.primaryContainer,
                modifier = Modifier.size(96.dp),
            ) {
                Box(contentAlignment = Alignment.Center) { BridgeMark(Modifier.size(52.dp)) }
            }
            // displaySmall carries -0.7sp of letter spacing, which is fine for Latin and breaks
            // Devanagari cluster shaping: on the device "सेतु" split into "से" above "तु", and
            // suppressing the wrap only clipped it instead. Spacing is reset to zero and the width
            // given explicitly so the shaped cluster has room to measure into.
            Text(
                "सेतु",
                Modifier.padding(top = 20.dp).fillMaxWidth(),
                style = MaterialTheme.typography.displaySmall.copy(
                    letterSpacing = 0.sp,
                    fontSize = 40.sp,
                    lineHeight = 52.sp,
                ),
                color = scheme.primary,
                textAlign = TextAlign.Center,
                maxLines = 1,
            )
            Text(
                "SETU",
                style = MaterialTheme.typography.titleMedium,
                color = scheme.onSurfaceVariant,
                letterSpacing = 4.sp,
            )
            Text(
                "Setu means bridge. When the sky disappears and satellites drop out, SETU is the " +
                    "bridge that carries your position across the gap.",
                Modifier.padding(top = 16.dp),
                style = MaterialTheme.typography.bodyLarge,
                textAlign = TextAlign.Center,
            )
        }

        // --- the problem ------------------------------------------------------------------------
        Column(Modifier.padding(horizontal = 24.dp)) {
            SectionTitle("Why it exists")
            Text(
                "Satellite navigation needs a clear view of the sky. Drive into a tunnel, under a " +
                    "flyover, into a basement car park or between tall buildings and the signal is " +
                    "blocked. Your position freezes, jumps to the wrong road, or disappears until " +
                    "you come out the other side.",
                style = MaterialTheme.typography.bodyMedium,
            )
            Text(
                "Those are exactly the places where a wrong turn costs you the most.",
                Modifier.padding(top = 12.dp),
                style = MaterialTheme.typography.bodyMedium,
                fontWeight = FontWeight.SemiBold,
            )

            SectionTitle("How it keeps going")
            Text(
                "Your phone already knows how it is moving. SETU reads the motion sensors " +
                    "hundreds of times a second and works out where you went, using the physics of " +
                    "how a vehicle actually travels.",
                Modifier.padding(bottom = 4.dp),
                style = MaterialTheme.typography.bodyMedium,
            )
        }

        Column(Modifier.padding(horizontal = 24.dp, vertical = 8.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
            AboutPoint(
                Icons.Outlined.Sensors,
                "It feels every turn and stop",
                "Accelerometers and gyroscopes track acceleration, braking and cornering at 200 " +
                    "readings a second.",
            )
            AboutPoint(
                Icons.Outlined.DirectionsCar,
                "It knows how vehicles move",
                "A car cannot slide sideways or leave the road surface. Holding the estimate to " +
                    "what is physically possible is what keeps it from wandering.",
            )
            AboutPoint(
                Icons.Outlined.RadioButtonChecked,
                "It knows when you have stopped",
                "At a barrier or in traffic, standing still is measurable, and pinning the " +
                    "estimate there clears away error that would otherwise build up.",
            )
            AboutPoint(
                Icons.Outlined.MyLocation,
                "It hands back to GPS cleanly",
                "The moment satellites return, the two are blended so your position settles back " +
                    "without a jump.",
            )
        }

        Column(Modifier.padding(horizontal = 24.dp)) {
            SectionTitle("Built to work with no signal at all")
            Text(
                "The map, the search and the route planner are all on your phone. Not a cached " +
                    "copy of somewhere you visited once, but the whole area, ready before you need " +
                    "it. Aeroplane mode changes nothing.",
                style = MaterialTheme.typography.bodyMedium,
            )
            Text(
                "Active area: ${maps.region.name}",
                Modifier.padding(top = 12.dp),
                style = MaterialTheme.typography.bodyMedium,
                fontWeight = FontWeight.SemiBold,
            )

            SectionTitle("Your journeys stay on your phone")
            Text(
                "There is no account and no sign-in. Nothing is uploaded on its own. Recording " +
                    "only happens when you start it, and a recording is exported only when you " +
                    "choose where to send it.",
                style = MaterialTheme.typography.bodyMedium,
            )

            // --- honest limits, after the idea rather than before it ---------------------------
            SectionTitle("What is still being built")
            Surface(
                shape = SetuShape.action,
                color = scheme.surfaceContainer,
                modifier = Modifier.fillMaxWidth(),
            ) {
                Column(Modifier.padding(16.dp)) {
                    Text(
                        "This is a working preview, and being straight about its edges matters " +
                            "more than looking finished.",
                        style = MaterialTheme.typography.bodyMedium,
                        fontWeight = FontWeight.SemiBold,
                    )
                    Text(
                        "Position without satellites holds direction well and is far better than " +
                            "having nothing, but distance travelled still drifts on a long " +
                            "blackout. The speed estimate that fixes this is the next piece of " +
                            "work. Turn restrictions are not in the route planner yet, and the " +
                            "demo replays a simulation rather than a recorded drive.",
                        Modifier.padding(top = 8.dp),
                        style = MaterialTheme.typography.bodyMedium,
                        color = scheme.onSurfaceVariant,
                    )
                    Text(
                        "Always follow the road and its signs rather than the screen.",
                        Modifier.padding(top = 8.dp),
                        style = MaterialTheme.typography.bodyMedium,
                        fontWeight = FontWeight.SemiBold,
                    )
                }
            }

            SectionTitle("Credits")
            Text(
                "Maps come from OpenStreetMap contributors under the Open Database License 1.0, " +
                    "drawn with MapLibre Native. ${maps.region.source}.",
                style = MaterialTheme.typography.bodyMedium,
            )
            Row {
                TextButton(onClick = {
                    context.startActivity(Intent(Intent.ACTION_VIEW, Uri.parse(maps.region.sourceUrl)))
                }) { Text("Map source") }
                TextButton(onClick = {
                    context.startActivity(Intent(Intent.ACTION_VIEW, Uri.parse("https://www.openstreetmap.org/copyright")))
                }) { Text("Attribution") }
                TextButton(onClick = {
                    context.startActivity(Intent(Intent.ACTION_VIEW, Uri.parse("https://maplibre.org/")))
                }) { Text("MapLibre") }
            }
            Text(
                "Version ${BuildConfig.VERSION_NAME}",
                Modifier.padding(top = 8.dp),
                style = MaterialTheme.typography.bodySmall,
                color = scheme.onSurfaceVariant,
            )
            Spacer(Modifier.height(32.dp))
        }
    }
}

@Composable
private fun AboutPoint(icon: ImageVector, title: String, detail: String) {
    Row(horizontalArrangement = Arrangement.spacedBy(14.dp)) {
        Box(
            Modifier.size(38.dp).clip(SetuShape.control)
                .background(MaterialTheme.colorScheme.secondaryContainer),
            contentAlignment = Alignment.Center,
        ) {
            Icon(icon, null, Modifier.size(20.dp), tint = MaterialTheme.colorScheme.onSecondaryContainer)
        }
        Column(Modifier.weight(1f)) {
            Text(title, style = MaterialTheme.typography.titleMedium)
            Text(
                detail,
                Modifier.padding(top = 2.dp),
                style = MaterialTheme.typography.bodyMedium,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
        }
    }
}
