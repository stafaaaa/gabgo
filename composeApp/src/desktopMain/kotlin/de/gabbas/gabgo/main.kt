package de.gabbas.gabgo

import androidx.compose.ui.unit.DpSize
import androidx.compose.ui.unit.dp
import androidx.compose.ui.window.Window
import androidx.compose.ui.window.application
import androidx.compose.ui.window.rememberWindowState
import de.gabbas.gabgo.resources.Res
import de.gabbas.gabgo.resources.gabgo_logo
import org.jetbrains.compose.resources.painterResource
import java.util.Locale

fun main() {
    // The UI is German; keep Material date pickers consistent regardless of the OS locale.
    Locale.setDefault(Locale.GERMANY)
    runApp()
}

private fun runApp() = application {
    Window(
        onCloseRequest = ::exitApplication,
        title = "GabGo",
        icon = painterResource(Res.drawable.gabgo_logo),
        state = rememberWindowState(size = DpSize(1180.dp, 860.dp)),
    ) {
        App()
    }
}
