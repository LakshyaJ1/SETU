package com.setu.navigator.ui

import androidx.compose.foundation.isSystemInDarkTheme
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.*
import androidx.compose.runtime.Composable
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp

/**
 * The shape scale, stated once so it can be obeyed.
 *
 * The UI had grown eight different corner radii (6, 12, 14, 16, 18, 20, 24, 28), which is what
 * makes an interface read as assembled from parts rather than designed. Four steps, each with a
 * job: controls and small tiles, actions, containers, and the one hero mark.
 */
object SetuShape {
    val control = RoundedCornerShape(12.dp)   // chips, icon tiles, small inline controls
    val action = RoundedCornerShape(16.dp)    // buttons and anything the user presses to proceed
    val card = RoundedCornerShape(20.dp)      // cards, sheets, grouped containers
    val hero = RoundedCornerShape(28.dp)      // the app mark only
}

val Forest = Color(0xFF195A40)
val Leaf = Color(0xFFDBEDBD)
val Amber = Color(0xFF865318)
val ButtonNavigationBackground = Color(0xFFF4F6F2)

private val Daylight = lightColorScheme(
    primary = Forest, onPrimary = Color.White,
    primaryContainer = Color(0xFFDDEDC8), onPrimaryContainer = Color(0xFF183521),
    secondary = Color(0xFF53664B), secondaryContainer = Color(0xFFE0EAD5),
    onSecondaryContainer = Color(0xFF273923),
    background = Color(0xFFF4F6F2), surface = Color(0xFFFCFDF9),
    surfaceContainer = Color(0xFFEAF0E6), surfaceContainerLow = Color(0xFFF0F4EB),
    surfaceContainerHigh = Color(0xFFE4EBDE), surfaceVariant = Color(0xFFE4EADF),
    onSurface = Color(0xFF202A23), onBackground = Color(0xFF202A23),
    onSurfaceVariant = Color(0xFF5F6E62), outline = Color(0xFF78877A),
    outlineVariant = Color(0xFFD9E1D4), error = Color(0xFFAE3531),
)
private val Night = darkColorScheme(
    primary = Color(0xFFAFDCA0), onPrimary = Color(0xFF103723),
    primaryContainer = Color(0xFF284F37), onPrimaryContainer = Color(0xFFE0F2CD),
    secondary = Color(0xFFB9CCAE), secondaryContainer = Color(0xFF364B31),
    onSecondaryContainer = Color(0xFFDCEBCF),
    background = Color(0xFF101B16), surface = Color(0xFF16221B),
    surfaceContainer = Color(0xFF213126), surfaceContainerLow = Color(0xFF1B291F),
    surfaceContainerHigh = Color(0xFF2B3A2E), surfaceVariant = Color(0xFF334233),
    onSurface = Color(0xFFEDF3E9), onBackground = Color(0xFFEDF3E9),
    onSurfaceVariant = Color(0xFFB8C6B8), outline = Color(0xFF829482),
    outlineVariant = Color(0xFF3E5141), error = Color(0xFFFFB4AA),
)

@Composable
fun SetuTheme(theme: String, content: @Composable () -> Unit) {
    val dark = theme == "Dark" || theme == "System" && isSystemInDarkTheme()
    MaterialTheme(
        colorScheme = if (dark) Night else Daylight,
        typography = Typography(
            displaySmall = TextStyle(fontFamily = FontFamily.SansSerif, fontWeight = FontWeight.Bold, fontSize = 34.sp, lineHeight = 38.sp, letterSpacing = (-0.7).sp),
            headlineMedium = TextStyle(fontWeight = FontWeight.Bold, fontSize = 28.sp, lineHeight = 34.sp, letterSpacing = (-0.5).sp),
            headlineSmall = TextStyle(fontWeight = FontWeight.SemiBold, fontSize = 24.sp, lineHeight = 30.sp),
            titleLarge = TextStyle(fontWeight = FontWeight.SemiBold, fontSize = 21.sp, lineHeight = 28.sp),
            titleMedium = TextStyle(fontWeight = FontWeight.SemiBold, fontSize = 16.sp, lineHeight = 24.sp),
            bodyLarge = TextStyle(fontSize = 16.sp, lineHeight = 24.sp),
            bodyMedium = TextStyle(fontSize = 14.sp, lineHeight = 21.sp),
            bodySmall = TextStyle(fontSize = 12.sp, lineHeight = 18.sp),
            labelLarge = TextStyle(fontWeight = FontWeight.SemiBold, fontSize = 14.sp, lineHeight = 20.sp),
            labelMedium = TextStyle(fontWeight = FontWeight.Medium, fontSize = 12.sp, lineHeight = 16.sp),
        ),
        content = content,
    )
}
