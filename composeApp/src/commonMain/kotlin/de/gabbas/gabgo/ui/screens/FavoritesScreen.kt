package de.gabbas.gabgo.ui.screens

import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.items
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.unit.dp
import de.gabbas.gabgo.ui.AppController
import de.gabbas.gabgo.ui.components.EventCard

@Composable
fun FavoritesScreen(c: AppController) {
    ScreenColumn {
        item { Column(contentWidth) { Header("Merkliste", "${c.favorites.size} gespeicherte Favoriten") } }
        if (c.favorites.isEmpty()) item {
            Text(
                "Noch nichts gemerkt. Tippe im Radar auf das Lesezeichen einer Ergebnis-Karte.",
                contentWidth.padding(top = 24.dp), style = MaterialTheme.typography.bodyLarge,
            )
        }
        items(c.favorites, key = { it.id }) { e ->
            Column(contentWidth.padding(bottom = 10.dp)) {
                EventCard(e, true, onClick = { c.selectedEvent = e }, onToggleFavorite = { c.toggleFavorite(e) })
            }
        }
    }
}
