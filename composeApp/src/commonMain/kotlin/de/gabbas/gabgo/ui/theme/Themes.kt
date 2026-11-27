package de.gabbas.gabgo.ui.theme

import androidx.compose.material3.ColorScheme
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.darkColorScheme
import androidx.compose.material3.lightColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.ui.graphics.Color

enum class GabGoTheme(val label: String, val proOnly: Boolean, val isDark: Boolean) {
    PULSE("GabGo Pulse", proOnly = false, isDark = true),
    MIDNIGHT_GOLD("Midnight Gold", proOnly = true, isDark = true),
    OCEAN_GLASS("Ocean Glass", proOnly = true, isDark = true),
    CLEAN_LIGHT("Clean Light", proOnly = false, isDark = false),
}

private val Pulse = darkColorScheme(
    primary = Color(0xFFF53E0E),
    onPrimary = Color(0xFFFFFFFF),
    primaryContainer = Color(0xFF5A1B08),
    onPrimaryContainer = Color(0xFFFFDBD0),
    secondary = Color(0xFFE9EBE0),
    onSecondary = Color(0xFF0D3334),
    secondaryContainer = Color(0xFF1E4A4B),
    onSecondaryContainer = Color(0xFFE9EBE0),
    tertiary = Color(0xFFFF8A5C),
    background = Color(0xFF0A2627),
    onBackground = Color(0xFFE9EBE0),
    surface = Color(0xFF0D3334),
    onSurface = Color(0xFFE9EBE0),
    surfaceVariant = Color(0xFF184445),
    onSurfaceVariant = Color(0xFFBFCBC6),
    surfaceContainer = Color(0xFF113B3C),
    surfaceContainerHigh = Color(0xFF164445),
    surfaceContainerHighest = Color(0xFF1B4C4D),
    surfaceContainerLow = Color(0xFF0F3637),
    outline = Color(0xFF5E7F7E),
    outlineVariant = Color(0xFF2B5556),
)

private val MidnightGold = darkColorScheme(
    primary = Color(0xFFE6B450),
    onPrimary = Color(0xFF231A00),
    primaryContainer = Color(0xFF4A3A10),
    onPrimaryContainer = Color(0xFFFFE6A8),
    secondary = Color(0xFFCFC3A4),
    onSecondary = Color(0xFF231A00),
    secondaryContainer = Color(0xFF2E2A20),
    onSecondaryContainer = Color(0xFFEDE1C2),
    tertiary = Color(0xFFF2D27A),
    background = Color(0xFF0B0B0F),
    onBackground = Color(0xFFEDE6D6),
    surface = Color(0xFF121218),
    onSurface = Color(0xFFEDE6D6),
    surfaceVariant = Color(0xFF1E1E26),
    onSurfaceVariant = Color(0xFFC9C0AC),
    surfaceContainer = Color(0xFF17171E),
    surfaceContainerHigh = Color(0xFF1D1D25),
    surfaceContainerHighest = Color(0xFF24242D),
    surfaceContainerLow = Color(0xFF131319),
    outline = Color(0xFF7A715E),
    outlineVariant = Color(0xFF34312A),
)

private val OceanGlass = darkColorScheme(
    primary = Color(0xFF5ED6E6),
    onPrimary = Color(0xFF00363D),
    primaryContainer = Color(0xFF0E4F5A),
    onPrimaryContainer = Color(0xFFB8F2FA),
    secondary = Color(0xFF8FB8FF),
    onSecondary = Color(0xFF002E69),
    secondaryContainer = Color(0xFF1C3A63),
    onSecondaryContainer = Color(0xFFD7E3FF),
    tertiary = Color(0xFFB7A6FF),
    background = Color(0xFF06182A),
    onBackground = Color(0xFFDDEBF5),
    surface = Color(0xFF0B2236),
    onSurface = Color(0xFFDDEBF5),
    surfaceVariant = Color(0xFF173149),
    onSurfaceVariant = Color(0xFFB0C6D6),
    surfaceContainer = Color(0xFF0F2A40),
    surfaceContainerHigh = Color(0xFF143048),
    surfaceContainerHighest = Color(0xFF1A3852),
    surfaceContainerLow = Color(0xFF0C2438),
    outline = Color(0xFF5C7A90),
    outlineVariant = Color(0xFF223F57),
)

private val CleanLight = lightColorScheme(
    primary = Color(0xFFD9360B),
    onPrimary = Color(0xFFFFFFFF),
    primaryContainer = Color(0xFFFFDBD0),
    onPrimaryContainer = Color(0xFF3B0A00),
    secondary = Color(0xFF0D3334),
    onSecondary = Color(0xFFFFFFFF),
    secondaryContainer = Color(0xFFD4E6E4),
    onSecondaryContainer = Color(0xFF0D3334),
    tertiary = Color(0xFF2F6F6B),
    background = Color(0xFFF7F7F2),
    onBackground = Color(0xFF17201F),
    surface = Color(0xFFFFFFFF),
    onSurface = Color(0xFF17201F),
    surfaceVariant = Color(0xFFE9EBE0),
    onSurfaceVariant = Color(0xFF44504E),
    surfaceContainer = Color(0xFFF0F1EA),
    surfaceContainerHigh = Color(0xFFEAECE4),
    surfaceContainerHighest = Color(0xFFE4E6DE),
    surfaceContainerLow = Color(0xFFF5F6F0),
    outline = Color(0xFF75807E),
    outlineVariant = Color(0xFFC9CFC8),
)

fun GabGoTheme.colorScheme(): ColorScheme = when (this) {
    GabGoTheme.PULSE -> Pulse
    GabGoTheme.MIDNIGHT_GOLD -> MidnightGold
    GabGoTheme.OCEAN_GLASS -> OceanGlass
    GabGoTheme.CLEAN_LIGHT -> CleanLight
}

@Composable
fun GabGoMaterialTheme(theme: GabGoTheme, content: @Composable () -> Unit) {
    MaterialTheme(colorScheme = theme.colorScheme(), content = content)
}
