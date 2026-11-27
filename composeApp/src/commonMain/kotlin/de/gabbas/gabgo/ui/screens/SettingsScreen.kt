package de.gabbas.gabgo.ui.screens

import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Delete
import androidx.compose.material.icons.filled.Edit
import androidx.compose.material.icons.filled.Lock
import androidx.compose.material.icons.filled.Verified
import androidx.compose.material.icons.filled.Visibility
import androidx.compose.material.icons.filled.VisibilityOff
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.ListItem
import androidx.compose.material3.ListItemDefaults
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.RadioButton
import androidx.compose.material3.Switch
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.text.input.VisualTransformation
import androidx.compose.ui.unit.dp
import de.gabbas.gabgo.license.Plan
import de.gabbas.gabgo.model.ProviderType
import de.gabbas.gabgo.ui.AppController
import de.gabbas.gabgo.ui.components.SectionTitle
import de.gabbas.gabgo.ui.components.SingleChipGroup
import de.gabbas.gabgo.ui.theme.GabGoTheme
import de.gabbas.gabgo.ui.theme.colorScheme

@OptIn(ExperimentalLayoutApi::class)
@Composable
fun SettingsScreen(c: AppController) {
    var gemini by remember { mutableStateOf(c.geminiKey) }
    var pplx by remember { mutableStateOf(c.perplexityKey) }
    var licenseInput by remember { mutableStateOf("") }
    var newTag by remember { mutableStateOf("") }
    var editing by remember { mutableStateOf<String?>(null) }
    var editValue by remember { mutableStateOf("") }
    val s = c.providerSettings

    ScreenColumn {
        item {
            Column(contentWidth.padding(bottom = 32.dp)) {
                Header("Einstellungen", "KI-Zugang, Themes, Tags & Lizenz")

                SectionTitle("GabGo Pro")
                Card(colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surfaceContainerHigh)) {
                    Column(Modifier.padding(16.dp).fillMaxWidth(), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                        val lic = c.license
                        if (lic != null) {
                            Row(verticalAlignment = Alignment.CenterVertically) {
                                Icon(Icons.Default.Verified, null, tint = MaterialTheme.colorScheme.primary)
                                Spacer(Modifier.width(8.dp))
                                Text("Pro aktiv – ${lic.name}", fontWeight = FontWeight.Bold)
                            }
                            Text("Lizenz ${lic.lid} · ausgestellt ${lic.iat}" + (lic.exp?.let { " · gültig bis $it" } ?: " · unbegrenzt"), style = MaterialTheme.typography.bodySmall)
                            TextButton(onClick = { c.removeLicense() }) { Text("Lizenz entfernen") }
                        } else {
                            Text("Demo: ${c.demoLeft} von ${Plan.FREE_DEMO_SEARCHES} kostenlosen Suchen übrig.", fontWeight = FontWeight.SemiBold)
                            Text("Pro: unbegrenzte Suchen, unbegrenzte Gruppengröße, alle Themes – dauerhaft offline freigeschaltet.", style = MaterialTheme.typography.bodySmall)
                            OutlinedTextField(licenseInput, { licenseInput = it }, Modifier.fillMaxWidth(), label = { Text("Lizenzschlüssel (GABGO1-…)") }, maxLines = 4)
                            Button(onClick = { c.activateLicense(licenseInput) }, enabled = licenseInput.isNotBlank()) { Text("Freischalten") }
                        }
                    }
                }

                SectionTitle("Live-Theme")
                FlowRow(horizontalArrangement = Arrangement.spacedBy(10.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
                    GabGoTheme.entries.forEach { t -> ThemeTile(t, selected = c.theme == t, locked = t.proOnly && !c.isPro) { c.selectTheme(t) } }
                }

                SectionTitle("KI-Live-Suche (BYOK)")
                Text(
                    "GabGo nutzt nur Modelle mit echter Live-Websuche. Deine Keys bleiben lokal auf diesem Gerät.",
                    style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
                ProviderType.entries.forEach { p ->
                    Row(Modifier.fillMaxWidth().clickable { c.updateProviderSettings(s.copy(primary = p)) }, verticalAlignment = Alignment.CenterVertically) {
                        RadioButton(selected = s.primary == p, onClick = { c.updateProviderSettings(s.copy(primary = p)) })
                        Text("Primär: ${p.label}")
                    }
                }
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Column(Modifier.weight(1f)) {
                        Text("Fallback-Verbindung")
                        Text("Wenn der primäre Anbieter ausfällt oder nichts Verifiziertes findet, wird der andere gefragt.", style = MaterialTheme.typography.bodySmall)
                    }
                    Switch(s.fallbackEnabled, { c.updateProviderSettings(s.copy(fallbackEnabled = it)) })
                }
                SecretField("Google Gemini API-Key", gemini) { gemini = it }
                OutlinedTextField(
                    s.geminiModel, { c.updateProviderSettings(s.copy(geminiModel = it.trim())) }, Modifier.fillMaxWidth().padding(top = 6.dp),
                    label = { Text("Gemini-Modell (mit google_search)") }, singleLine = true,
                )
                SecretField("Perplexity API-Key", pplx) { pplx = it }
                Text("Perplexity-Modell", Modifier.padding(top = 6.dp), style = MaterialTheme.typography.labelMedium)
                SingleChipGroup(listOf("sonar", "sonar-pro"), s.perplexityModel, { it }) { c.updateProviderSettings(s.copy(perplexityModel = it)) }
                Button(onClick = { c.saveApiKeys(gemini, pplx) }, Modifier.padding(top = 8.dp)) { Text("Keys speichern") }

                SectionTitle("Eigene Tags")
                c.customTags.forEach { tag ->
                    if (editing == tag) {
                        Row(verticalAlignment = Alignment.CenterVertically) {
                            OutlinedTextField(editValue, { editValue = it }, Modifier.weight(1f), singleLine = true)
                            TextButton(onClick = { c.renameTag(tag, editValue); editing = null }) { Text("OK") }
                        }
                    } else {
                        ListItem(
                            headlineContent = { Text(tag) },
                            trailingContent = {
                                Row {
                                    IconButton(onClick = { editing = tag; editValue = tag }) { Icon(Icons.Default.Edit, "Bearbeiten") }
                                    IconButton(onClick = { c.deleteTag(tag) }) { Icon(Icons.Default.Delete, "Löschen") }
                                }
                            },
                            colors = ListItemDefaults.colors(containerColor = MaterialTheme.colorScheme.background),
                        )
                    }
                }
                Row(verticalAlignment = Alignment.CenterVertically) {
                    OutlinedTextField(newTag, { newTag = it }, Modifier.weight(1f), singleLine = true, placeholder = { Text("#NeuerTag") })
                    TextButton(onClick = { if (c.addTag(newTag)) newTag = "" }) { Text("Hinzufügen") }
                }
                Spacer(Modifier.height(16.dp))
                Text("GabGo 1.0.0 · de.gabbas.gabgo", style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
            }
        }
    }
}

@Composable
private fun SecretField(label: String, value: String, onChange: (String) -> Unit) {
    var visible by remember { mutableStateOf(false) }
    OutlinedTextField(
        value, onChange, Modifier.fillMaxWidth().padding(top = 8.dp), label = { Text(label) }, singleLine = true,
        visualTransformation = if (visible) VisualTransformation.None else PasswordVisualTransformation(),
        trailingIcon = {
            IconButton(onClick = { visible = !visible }) { Icon(if (visible) Icons.Default.VisibilityOff else Icons.Default.Visibility, null) }
        },
    )
}

@Composable
private fun ThemeTile(t: GabGoTheme, selected: Boolean, locked: Boolean, onClick: () -> Unit) {
    val cs = t.colorScheme()
    OutlinedButton(
        onClick = onClick, shape = RoundedCornerShape(16.dp),
        border = BorderStroke(if (selected) 3.dp else 1.dp, if (selected) MaterialTheme.colorScheme.primary else MaterialTheme.colorScheme.outlineVariant),
    ) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Box(Modifier.size(28.dp).background(cs.background, CircleShape), contentAlignment = Alignment.Center) {
                Box(Modifier.size(14.dp).background(cs.primary, CircleShape))
            }
            Spacer(Modifier.width(8.dp))
            Text(t.label)
            if (locked) { Spacer(Modifier.width(6.dp)); Icon(Icons.Default.Lock, "Pro", Modifier.size(16.dp)) }
        }
    }
}
