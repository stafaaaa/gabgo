package de.gabbas.gabgo.ui.screens

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Bookmark
import androidx.compose.material.icons.filled.Close
import androidx.compose.material.icons.filled.ConfirmationNumber
import androidx.compose.material.icons.filled.Directions
import androidx.compose.material.icons.filled.EventAvailable
import androidx.compose.material.icons.filled.LocalTaxi
import androidx.compose.material.icons.filled.OpenInNew
import androidx.compose.material.icons.outlined.BookmarkBorder
import androidx.compose.material3.AssistChip
import androidx.compose.material3.Button
import androidx.compose.material3.FilledTonalButton
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.window.Dialog
import androidx.compose.ui.window.DialogProperties
import de.gabbas.gabgo.model.EventSuggestion
import de.gabbas.gabgo.platform.currentPlatform
import de.gabbas.gabgo.platform.isApple
import de.gabbas.gabgo.ui.AppController
import de.gabbas.gabgo.ui.components.formatWhen

@OptIn(ExperimentalLayoutApi::class)
@Composable
fun EventDetailDialog(c: AppController, e: EventSuggestion) {
    Dialog(onDismissRequest = { c.selectedEvent = null }, properties = DialogProperties(usePlatformDefaultWidth = false)) {
        Surface(
            shape = RoundedCornerShape(24.dp), color = MaterialTheme.colorScheme.surface,
            modifier = Modifier.padding(16.dp).widthIn(max = 640.dp).heightIn(max = 860.dp),
        ) {
            Column(Modifier.verticalScroll(rememberScrollState()).padding(20.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
                Row(verticalAlignment = Alignment.Top) {
                    Column(Modifier.weight(1f)) {
                        if (e.category.isNotBlank()) Text(e.category.uppercase(), style = MaterialTheme.typography.labelMedium, color = MaterialTheme.colorScheme.primary)
                        Text(e.title, style = MaterialTheme.typography.headlineSmall, fontWeight = FontWeight.Bold)
                    }
                    IconButton(onClick = { c.toggleFavorite(e) }) {
                        Icon(if (c.isFavorite(e)) Icons.Default.Bookmark else Icons.Outlined.BookmarkBorder, "Merkliste", tint = MaterialTheme.colorScheme.primary)
                    }
                    IconButton(onClick = { c.selectedEvent = null }) { Icon(Icons.Default.Close, "Schließen") }
                }
                Detail("Wann", formatWhen(e.start, e.end))
                Detail("Wo", e.fullAddress)
                if (e.priceRange.isNotBlank()) Detail("Preis", e.priceRange)
                e.openingHours?.takeIf { it.isNotBlank() }?.let { Detail("Öffnungszeiten", it) }
                if (e.ageGroups.isNotEmpty()) Detail("Geeignet für", e.ageGroups.joinToString())
                if (e.description.isNotBlank()) Text(e.description, style = MaterialTheme.typography.bodyLarge)
                if (e.tags.isNotEmpty()) FlowRow(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                    e.tags.forEach { AssistChip(onClick = {}, label = { Text(it) }) }
                }
                HorizontalDivider()
                Text("1-Klick-Export", style = MaterialTheme.typography.titleSmall, color = MaterialTheme.colorScheme.primary)
                Button(onClick = { c.exportCalendar(e) }, Modifier.fillMaxWidth()) {
                    Icon(Icons.Default.EventAvailable, null); Spacer(Modifier.padding(4.dp)); Text("In Kalender (.ics)")
                }
                FilledTonalButton(onClick = { c.openRoute(e) }, Modifier.fillMaxWidth()) {
                    Icon(Icons.Default.Directions, null); Spacer(Modifier.padding(4.dp))
                    Text(if (currentPlatform.isApple) "Route in Apple Karten" else "Route in Google Maps")
                }
                FilledTonalButton(onClick = { c.openUber(e) }, Modifier.fillMaxWidth()) {
                    Icon(Icons.Default.LocalTaxi, null); Spacer(Modifier.padding(4.dp)); Text("Fahrt mit Uber")
                }
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    OutlinedButton(onClick = { c.open(e.sourceUrl) }, Modifier.weight(1f)) {
                        Icon(Icons.Default.OpenInNew, null); Spacer(Modifier.padding(2.dp)); Text("Quelle")
                    }
                    e.ticketUrl?.takeIf { it.isNotBlank() && it != e.sourceUrl }?.let { t ->
                        OutlinedButton(onClick = { c.open(t) }, Modifier.weight(1f)) {
                            Icon(Icons.Default.ConfirmationNumber, null); Spacer(Modifier.padding(2.dp)); Text("Tickets")
                        }
                    }
                }
                Spacer(Modifier.height(4.dp))
                Text(
                    "Angaben stammen aus der verlinkten Live-Quelle. Bitte vor dem Besuch kurz prüfen.",
                    style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }
        }
    }
}

@Composable
private fun Detail(label: String, value: String) {
    Column {
        Text(label, style = MaterialTheme.typography.labelMedium, color = MaterialTheme.colorScheme.onSurfaceVariant)
        Text(value, style = MaterialTheme.typography.bodyLarge)
    }
}
