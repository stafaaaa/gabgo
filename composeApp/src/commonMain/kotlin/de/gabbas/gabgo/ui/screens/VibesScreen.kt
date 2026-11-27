package de.gabbas.gabgo.ui.screens

import androidx.compose.foundation.Image
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.ContentCopy
import androidx.compose.material.icons.filled.ContentPaste
import androidx.compose.material.icons.filled.Delete
import androidx.compose.material.icons.filled.Groups
import androidx.compose.material.icons.filled.Person
import androidx.compose.material.icons.filled.QrCode2
import androidx.compose.material.icons.filled.QrCodeScanner
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.FilledTonalButton
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.ListItem
import androidx.compose.material3.ListItemDefaults
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalClipboardManager
import androidx.compose.ui.text.AnnotatedString
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import de.gabbas.gabgo.license.Plan
import de.gabbas.gabgo.model.AgeGroup
import de.gabbas.gabgo.model.Budget
import de.gabbas.gabgo.model.Category
import de.gabbas.gabgo.model.Mood
import de.gabbas.gabgo.platform.QrScanner
import de.gabbas.gabgo.ui.AppController
import de.gabbas.gabgo.ui.components.ChipGroup
import de.gabbas.gabgo.ui.components.SectionTitle
import de.gabbas.gabgo.ui.components.SingleChipGroup
import io.github.alexzhirkevich.qrose.rememberQrCodePainter

@Suppress("DEPRECATION")
@Composable
fun VibesScreen(c: AppController) {
    val clipboard = LocalClipboardManager.current
    var showCode by remember { mutableStateOf(false) }
    var pasted by remember { mutableStateOf("") }
    val me = c.myVibe

    ScreenColumn {
        item {
            Column(contentWidth) {
                Header("Unsere Vibes", "Gemeinsam matchen – für Paare, Familien & Gruppen, ganz ohne Server")

                SectionTitle("1 · Mein Vibe")
                OutlinedTextField(
                    me.name, { c.updateMyVibe(me.copy(name = it.take(24))) }, Modifier.fillMaxWidth(),
                    label = { Text("Mein Name") }, singleLine = true, leadingIcon = { Icon(Icons.Default.Person, null) },
                )
                SectionTitle("Stimmungen")
                ChipGroup(Mood.entries, me.moods, { it.label }) { c.updateMyVibe(me.copy(moods = me.moods.toggle(it))) }
                SectionTitle("Kategorien")
                ChipGroup(Category.entries, me.categories, { it.label }) { c.updateMyVibe(me.copy(categories = me.categories.toggle(it))) }
                SectionTitle("Tags")
                ChipGroup(c.customTags, me.tags, { it }) { c.updateMyVibe(me.copy(tags = me.tags.toggle(it))) }
                SectionTitle("Wer ist dabei?")
                ChipGroup(AgeGroup.entries, me.ageGroups, { it.label }) { c.updateMyVibe(me.copy(ageGroups = me.ageGroups.toggle(it))) }
                SectionTitle("Mein Budget")
                SingleChipGroup(Budget.entries, me.budget, { it.label }) { c.updateMyVibe(me.copy(budget = it)) }
                Spacer(Modifier.height(12.dp))
                Button(onClick = { showCode = !showCode }, Modifier.fillMaxWidth()) {
                    Icon(Icons.Default.QrCode2, null); Spacer(Modifier.width(8.dp))
                    Text(if (showCode) "QR-Code ausblenden" else "Vibe-Code & QR-Code erzeugen")
                }
                if (showCode) {
                    val code = c.myVibeCode()
                    Card(Modifier.fillMaxWidth().padding(top = 12.dp)) {
                        Column(Modifier.padding(16.dp), horizontalAlignment = Alignment.CenterHorizontally) {
                            Box(Modifier.background(Color.White, RoundedCornerShape(16.dp)).padding(16.dp)) {
                                Image(rememberQrCodePainter(code), "Vibe-QR-Code", Modifier.size(220.dp))
                            }
                            Spacer(Modifier.height(10.dp))
                            Text(code, fontFamily = FontFamily.Monospace, style = MaterialTheme.typography.bodySmall)
                            OutlinedButton(onClick = { clipboard.setText(AnnotatedString(code)); c.message = "Vibe-Code kopiert." }) {
                                Icon(Icons.Default.ContentCopy, null); Spacer(Modifier.width(6.dp)); Text("Code kopieren")
                            }
                        }
                    }
                }

                SectionTitle("2 · Andere hinzufügen")
                Text(
                    if (c.isPro) "Unbegrenzte Gruppengröße (Pro)." else "Demo: bis zu ${Plan.FREE_MAX_GROUP_SIZE} Personen. Pro: unbegrenzt.",
                    style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
                if (QrScanner.isSupported) {
                    FilledTonalButton(
                        onClick = { QrScanner.scan { result -> if (result != null) c.importVibe(result) } },
                        Modifier.fillMaxWidth().padding(top = 8.dp),
                    ) { Icon(Icons.Default.QrCodeScanner, null); Spacer(Modifier.width(8.dp)); Text("QR-Code scannen") }
                }
                Row(Modifier.padding(top = 8.dp), verticalAlignment = Alignment.CenterVertically) {
                    OutlinedTextField(
                        pasted, { pasted = it }, Modifier.weight(1f), singleLine = true,
                        label = { Text("Vibe-Code einfügen (GV1.…)") },
                    )
                    IconButton(onClick = { pasted = clipboard.getText()?.text.orEmpty() }) { Icon(Icons.Default.ContentPaste, "Aus Zwischenablage") }
                }
                OutlinedButton(onClick = { if (c.importVibe(pasted)) pasted = "" }, Modifier.fillMaxWidth(), enabled = pasted.isNotBlank()) {
                    Text("Person hinzufügen")
                }

                SectionTitle("3 · Eure Gruppe (${c.groupMembers.size + 1})")
                ListItem(
                    headlineContent = { Text("${me.name} (ich)") },
                    supportingContent = { Text(summary(me)) },
                    leadingContent = { Icon(Icons.Default.Person, null) },
                    colors = ListItemDefaults.colors(containerColor = MaterialTheme.colorScheme.surfaceContainer),
                )
                c.groupMembers.forEach { p ->
                    ListItem(
                        headlineContent = { Text(p.name) },
                        supportingContent = { Text(summary(p)) },
                        leadingContent = { Icon(Icons.Default.Person, null) },
                        trailingContent = { IconButton(onClick = { c.removeMember(p) }) { Icon(Icons.Default.Delete, "Entfernen") } },
                        colors = ListItemDefaults.colors(containerColor = MaterialTheme.colorScheme.surfaceContainer),
                    )
                }
                if (c.groupMembers.isNotEmpty()) {
                    val g = c.group()
                    Card(
                        Modifier.fillMaxWidth().padding(top = 12.dp),
                        colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.secondaryContainer),
                    ) {
                        Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(4.dp)) {
                            Text("Euer Match", fontWeight = FontWeight.Bold)
                            Text("Gemeinsame Stimmungen: " + g.sharedMoods.joinToString { it.label }.ifEmpty { "–" })
                            Text("Gemeinsame Kategorien: " + g.sharedCategories.joinToString { it.label }.ifEmpty { "–" })
                            Text("Gemeinsame Tags: " + g.sharedTags.joinToString(" ").ifEmpty { "–" })
                            Text("Budget: ${g.budget.label}")
                        }
                    }
                }
                Button(
                    onClick = { c.searchGroup() }, enabled = !c.searching,
                    modifier = Modifier.fillMaxWidth().padding(top = 16.dp, bottom = 32.dp).height(52.dp),
                ) {
                    Icon(Icons.Default.Groups, null); Spacer(Modifier.width(8.dp)); Text("Gemeinsame Vorschläge finden")
                }
            }
        }
    }
}

private fun summary(p: de.gabbas.gabgo.vibes.VibeProfile): String =
    (p.moods.map { it.label } + p.categories.map { it.label } + p.tags).take(6).joinToString().ifEmpty { "noch keine Vorlieben" }
