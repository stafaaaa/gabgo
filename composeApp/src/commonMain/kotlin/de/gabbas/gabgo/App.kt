package de.gabbas.gabgo

import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.BoxWithConstraints
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.WindowInsets
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.safeDrawing
import androidx.compose.foundation.layout.windowInsetsPadding
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Bookmarks
import androidx.compose.material.icons.filled.Groups
import androidx.compose.material.icons.filled.Radar
import androidx.compose.material.icons.filled.Settings
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.NavigationBar
import androidx.compose.material3.NavigationBarItem
import androidx.compose.material3.NavigationRail
import androidx.compose.material3.NavigationRailItem
import androidx.compose.material3.Scaffold
import androidx.compose.material3.SnackbarHost
import androidx.compose.material3.SnackbarHostState
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import de.gabbas.gabgo.data.AppRepository
import de.gabbas.gabgo.platform.createKeyValueStore
import de.gabbas.gabgo.ui.AppController
import de.gabbas.gabgo.ui.Tab
import de.gabbas.gabgo.ui.screens.EventDetailDialog
import de.gabbas.gabgo.ui.screens.FavoritesScreen
import de.gabbas.gabgo.ui.screens.RadarScreen
import de.gabbas.gabgo.ui.screens.SettingsScreen
import de.gabbas.gabgo.ui.screens.VibesScreen
import de.gabbas.gabgo.ui.theme.GabGoMaterialTheme

private fun Tab.icon() = when (this) {
    Tab.RADAR -> Icons.Default.Radar
    Tab.VIBES -> Icons.Default.Groups
    Tab.FAVORITES -> Icons.Default.Bookmarks
    Tab.SETTINGS -> Icons.Default.Settings
}

@Composable
fun App() {
    val scope = rememberCoroutineScope()
    val controller = remember { AppController(AppRepository(createKeyValueStore()), scope) }
    val snackbar = remember { SnackbarHostState() }

    LaunchedEffect(controller.message) {
        controller.message?.let {
            snackbar.showSnackbar(it)
            controller.message = null
        }
    }

    GabGoMaterialTheme(controller.theme) {
        Surface(Modifier.fillMaxSize(), color = MaterialTheme.colorScheme.background) {
            BoxWithConstraints(Modifier.fillMaxSize()) {
                val wide = maxWidth >= 840.dp
                Scaffold(
                    containerColor = MaterialTheme.colorScheme.background,
                    snackbarHost = { SnackbarHost(snackbar) },
                    bottomBar = {
                        if (!wide) NavigationBar {
                            Tab.entries.forEach { t ->
                                NavigationBarItem(
                                    selected = controller.tab == t, onClick = { controller.tab = t },
                                    icon = { Icon(t.icon(), null) }, label = { Text(t.label, maxLines = 1) },
                                )
                            }
                        }
                    },
                ) { padding ->
                    Row(Modifier.fillMaxSize().padding(padding)) {
                        if (wide) NavigationRail(Modifier.windowInsetsPadding(WindowInsets.safeDrawing)) {
                            Tab.entries.forEach { t ->
                                NavigationRailItem(
                                    selected = controller.tab == t, onClick = { controller.tab = t },
                                    icon = { Icon(t.icon(), null) }, label = { Text(t.label) },
                                )
                            }
                        }
                        Box(Modifier.weight(1f).fillMaxSize()) {
                            when (controller.tab) {
                                Tab.RADAR -> RadarScreen(controller)
                                Tab.VIBES -> VibesScreen(controller)
                                Tab.FAVORITES -> FavoritesScreen(controller)
                                Tab.SETTINGS -> SettingsScreen(controller)
                            }
                        }
                    }
                }
            }
            controller.selectedEvent?.let { EventDetailDialog(controller, it) }
        }
    }
}
