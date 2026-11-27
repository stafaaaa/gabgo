package de.gabbas.gabgo.ui.screens

import androidx.compose.foundation.Image
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.WindowInsets
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.safeDrawing
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.layout.windowInsetsPadding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardActions
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Add
import androidx.compose.material.icons.filled.Info
import androidx.compose.material.icons.filled.LocationCity
import androidx.compose.material.icons.filled.Search
import androidx.compose.material.icons.filled.Verified
import androidx.compose.material.icons.filled.Warning
import androidx.compose.material3.AssistChip
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.DatePickerDialog
import androidx.compose.material3.DateRangePicker
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.SegmentedButton
import androidx.compose.material3.SegmentedButtonDefaults
import androidx.compose.material3.SingleChoiceSegmentedButtonRow
import androidx.compose.material3.Slider
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.rememberDateRangePickerState
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.unit.dp
import de.gabbas.gabgo.model.AgeGroup
import de.gabbas.gabgo.model.Budget
import de.gabbas.gabgo.model.Category
import de.gabbas.gabgo.model.Mood
import de.gabbas.gabgo.model.SearchMode
import de.gabbas.gabgo.model.SearchStatus
import de.gabbas.gabgo.resources.Res
import de.gabbas.gabgo.resources.gabgo_logo
import de.gabbas.gabgo.ui.AppController
import de.gabbas.gabgo.ui.DatePreset
import de.gabbas.gabgo.ui.components.ChipGroup
import de.gabbas.gabgo.ui.components.EventCard
import de.gabbas.gabgo.ui.components.SectionTitle
import de.gabbas.gabgo.ui.components.SingleChipGroup
import de.gabbas.gabgo.ui.components.formatDate
import kotlinx.datetime.Instant
import kotlinx.datetime.LocalDate
import kotlinx.datetime.TimeZone
import kotlinx.datetime.toLocalDateTime
import org.jetbrains.compose.resources.painterResource

@Composable
fun ScreenColumn(content: androidx.compose.foundation.lazy.LazyListScope.() -> Unit) {
    LazyColumn(
        modifier = Modifier.fillMaxSize().windowInsetsPadding(WindowInsets.safeDrawing),
        horizontalAlignment = Alignment.CenterHorizontally,
    ) {
        content()
    }
}

@Composable
fun Header(title: String, subtitle: String, trailing: @Composable () -> Unit = {}) {
    Row(Modifier.fillMaxWidth().padding(top = 8.dp, bottom = 8.dp), verticalAlignment = Alignment.CenterVertically) {
        Image(painterResource(Res.drawable.gabgo_logo), null, Modifier.size(44.dp).clip(RoundedCornerShape(12.dp)))
        Spacer(Modifier.width(12.dp))
        Column(Modifier.weight(1f)) {
            Text(title, style = MaterialTheme.typography.headlineSmall, fontWeight = FontWeight.Bold)
            Text(subtitle, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
        }
        trailing()
    }
}

val contentWidth = Modifier.widthIn(max = 760.dp).fillMaxWidth().padding(horizontal = 16.dp)

@OptIn(ExperimentalMaterial3Api::class, ExperimentalLayoutApi::class)
@Composable
fun RadarScreen(c: AppController) {
    var showRange by remember { mutableStateOf(false) }
    var newTag by remember { mutableStateOf("") }

    ScreenColumn {
        item {
            Column(contentWidth) {
                Header("GabGo-Radar", "Live-Events, Ausflüge & Familienziele – nur mit echten Quellen") {
                    if (!c.isPro) AssistChip(onClick = { c.tab = de.gabbas.gabgo.ui.Tab.SETTINGS }, label = { Text("Demo: ${c.demoLeft}/3") })
                    else AssistChip(onClick = {}, label = { Text("Pro") }, leadingIcon = { Icon(Icons.Default.Verified, null) })
                }
                SingleChoiceSegmentedButtonRow(Modifier.fillMaxWidth()) {
                    SearchMode.entries.forEachIndexed { i, m ->
                        SegmentedButton(
                            selected = c.mode == m,
                            onClick = { c.mode = m; if (m == SearchMode.FAMILY) c.categories = c.categories.filterNot { it.musicRelated }.toSet() },
                            shape = SegmentedButtonDefaults.itemShape(i, SearchMode.entries.size),
                        ) { Text(m.label, maxLines = 1) }
                    }
                }
                Spacer(Modifier.height(12.dp))
                OutlinedTextField(
                    value = c.city, onValueChange = { c.city = it }, modifier = Modifier.fillMaxWidth(),
                    label = { Text("Stadt oder Ort") }, singleLine = true,
                    leadingIcon = { Icon(Icons.Default.LocationCity, null) },
                    keyboardOptions = KeyboardOptions(imeAction = ImeAction.Search),
                    keyboardActions = KeyboardActions(onSearch = { c.searchRadar() }),
                )
                SectionTitle("Umkreis: ${c.radiusKm} km")
                Slider(value = c.radiusKm.toFloat(), onValueChange = { c.radiusKm = it.toInt() }, valueRange = 5f..150f, steps = 28)

                val (from, to) = c.dateRange()
                SectionTitle("Zeitraum: ${formatDate(from)}${if (to != from) " – ${formatDate(to)}" else ""}")
                SingleChipGroup(DatePreset.entries, c.datePreset, { it.label }) {
                    if (it == DatePreset.CUSTOM) showRange = true else c.datePreset = it
                }

                SectionTitle("Budget")
                SingleChipGroup(Budget.entries, c.budget, { it.label }) { c.budget = it }

                if (c.mode == SearchMode.FAMILY) {
                    SectionTitle("Familie & Kinder – Altersgruppen")
                    ChipGroup(AgeGroup.entries, c.ageGroups, { it.label }) { c.ageGroups = c.ageGroups.toggle(it) }
                }

                SectionTitle("Kategorien")
                val cats = if (c.mode == SearchMode.FAMILY) Category.entries.filterNot { it.musicRelated } else Category.entries
                ChipGroup(cats, c.categories, { it.label }) { c.categories = c.categories.toggle(it) }

                SectionTitle("Stimmung")
                ChipGroup(Mood.entries, c.moods, { it.label }) { c.moods = c.moods.toggle(it) }

                SectionTitle("Eigene Tags")
                ChipGroup(c.customTags, c.selectedTags, { it }, { c.selectedTags = c.selectedTags.toggle(it) })
                Row(verticalAlignment = Alignment.CenterVertically) {
                    OutlinedTextField(
                        newTag, { newTag = it }, Modifier.weight(1f), singleLine = true,
                        placeholder = { Text("#NeuerTag") },
                        keyboardActions = KeyboardActions(onDone = { if (c.addTag(newTag)) newTag = "" }),
                        keyboardOptions = KeyboardOptions(imeAction = ImeAction.Done),
                    )
                    TextButton(onClick = { if (c.addTag(newTag)) { c.selectedTags = c.selectedTags + de.gabbas.gabgo.vibes.VibeCode.normalizeTag(newTag); newTag = "" } }) {
                        Icon(Icons.Default.Add, null); Text("Tag")
                    }
                }

                OutlinedTextField(
                    c.freeText, { c.freeText = it }, Modifier.fillMaxWidth().padding(top = 12.dp),
                    label = { Text("Besonderer Wunsch (optional)") }, placeholder = { Text("z. B. barrierefrei, mit Hund, bei Regen") },
                )
                Spacer(Modifier.height(16.dp))
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Button(onClick = { c.searchRadar() }, enabled = !c.searching, modifier = Modifier.weight(1f).height(52.dp)) {
                        Icon(Icons.Default.Search, null); Spacer(Modifier.width(8.dp)); Text("Live suchen")
                    }
                    if (c.searching) {
                        Spacer(Modifier.width(12.dp))
                        OutlinedButton(onClick = { c.cancelSearch() }) { Text("Abbrechen") }
                    }
                }
                Spacer(Modifier.height(16.dp))
            }
        }

        if (c.searching) item {
            Column(contentWidth.padding(vertical = 24.dp), horizontalAlignment = Alignment.CenterHorizontally) {
                CircularProgressIndicator()
                Spacer(Modifier.height(8.dp))
                Text("GabGo durchsucht das Live-Web nach verifizierten Terminen …", style = MaterialTheme.typography.bodyMedium)
            }
        }

        c.outcome?.let { outcome ->
            if (!c.searching) {
                item { OutcomeBanner(c, outcome) }
                items(outcome.events, key = { it.id }) { e ->
                    Column(contentWidth.padding(bottom = 10.dp)) {
                        EventCard(e, c.isFavorite(e), onClick = { c.selectedEvent = e }, onToggleFavorite = { c.toggleFavorite(e) })
                    }
                }
                if (outcome.sources.isNotEmpty()) item {
                    Column(contentWidth.padding(bottom = 24.dp)) {
                        SectionTitle("Live-Quellen der Recherche (${outcome.sources.size})")
                        FlowRow(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                            outcome.sources.take(12).forEach { s ->
                                AssistChip(onClick = { c.open(s.url) }, label = { Text(s.title.take(40), maxLines = 1) })
                            }
                        }
                    }
                }
            }
        }
    }

    if (showRange) {
        val state = rememberDateRangePickerState()
        DatePickerDialog(
            onDismissRequest = { showRange = false },
            confirmButton = {
                TextButton(onClick = {
                    val s = state.selectedStartDateMillis
                    if (s != null) {
                        c.customFrom = millisToDate(s)
                        c.customTo = state.selectedEndDateMillis?.let { millisToDate(it) } ?: c.customFrom
                        c.datePreset = DatePreset.CUSTOM
                    }
                    showRange = false
                }) { Text("Übernehmen") }
            },
            dismissButton = { TextButton(onClick = { showRange = false }) { Text("Abbrechen") } },
        ) {
            DateRangePicker(state, Modifier.weight(1f), title = { Text("Zeitraum wählen", Modifier.padding(16.dp)) })
        }
    }
}

@Composable
private fun OutcomeBanner(c: AppController, outcome: de.gabbas.gabgo.model.SearchOutcome) {
    val (icon, title) = when (outcome.status) {
        SearchStatus.VERIFIED -> Icons.Default.Verified to "${outcome.events.size} verifizierte Live-Ergebnisse" +
            (if (c.lastSearchWasGroup) " für eure Gruppe" else "")
        SearchStatus.NO_VERIFIED_DATA -> Icons.Default.Info to "Keine verifizierten Live-Daten"
        SearchStatus.ERROR -> Icons.Default.Warning to "Suche fehlgeschlagen"
    }
    Card(
        contentWidth.padding(bottom = 12.dp),
        colors = CardDefaults.cardColors(
            containerColor = if (outcome.status == SearchStatus.VERIFIED) MaterialTheme.colorScheme.secondaryContainer
            else MaterialTheme.colorScheme.errorContainer,
        ),
    ) {
        Row(Modifier.padding(14.dp), verticalAlignment = Alignment.CenterVertically) {
            Icon(icon, null)
            Spacer(Modifier.width(12.dp))
            Column {
                Text(title, fontWeight = FontWeight.SemiBold)
                val details = buildList {
                    if (outcome.message.isNotBlank()) add(outcome.message)
                    outcome.provider?.let { add("Quelle: ${it.label}") }
                    if (outcome.droppedCount > 0) add("${outcome.droppedCount} Einträge ohne Datum/Ort/Quelle verworfen.")
                }
                if (details.isNotEmpty()) Text(details.joinToString("\n"), style = MaterialTheme.typography.bodySmall)
            }
        }
    }
}

fun <T> Set<T>.toggle(item: T): Set<T> = if (item in this) this - item else this + item

private fun millisToDate(ms: Long): LocalDate = Instant.fromEpochMilliseconds(ms).toLocalDateTime(TimeZone.UTC).date

