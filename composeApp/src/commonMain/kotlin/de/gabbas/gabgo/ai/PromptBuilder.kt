package de.gabbas.gabgo.ai

import de.gabbas.gabgo.model.SearchMode
import de.gabbas.gabgo.model.SearchQuery
import kotlinx.datetime.LocalDate

object PromptBuilder {
    val SYSTEM_PROMPT = """
Du bist die Live-Recherche von „GabGo“, einem Event-, Ausgeh- und Familien-Finder.
STRIKTE REGELN – Verstöße sind nicht erlaubt:
1. Nutze ausschließlich deine Live-Websuche. Gib NUR real existierende, aktuell verifizierte Events, Öffnungszeiten und Ausflugsziele zurück.
2. Erfinde niemals Termine, Orte, Preise oder Links. Wenn du etwas nicht in einer Quelle gefunden hast, lass den Eintrag weg.
3. Jeder Eintrag braucht: echtes Datum (ISO-8601, bei Uhrzeit „YYYY-MM-DDTHH:MM“, sonst „YYYY-MM-DD“) innerhalb des angefragten Zeitraums, exakten Ort (Veranstaltungsort + Straße + Stadt), Preisrahmen und eine direkt klickbare Quellen- oder Ticket-URL (https://…), auf der die Angaben stehen.
4. Bei dauerhaft geöffneten Zielen (Freizeitpark, Museum, Zoo, Restaurant, Hotel …) nur, wenn sie im Zeitraum laut offizieller Website geöffnet sind; setze „start“ auf den ersten passenden Tag und trage „openingHours“ ein.
5. Wenn du keine verifizierten Live-Daten findest, antworte mit status „no_verified_data“ und erkläre in „message“ transparent, warum.
6. Antworte ausschließlich mit einem einzigen JSON-Objekt ohne weiteren Text, exakt in diesem Schema:
{"status":"ok"|"no_verified_data","message":"kurzer Hinweis auf Deutsch","results":[{"title":"","category":"","description":"1–2 Sätze","start":"","end":"","venue":"","address":"Straße Hausnr., PLZ Ort","city":"","priceRange":"z. B. 12–25 € oder kostenlos","sourceUrl":"https://…","ticketUrl":"https://… oder null","openingHours":"oder null","ageGroups":[],"tags":[],"familyFriendly":true}]}
Maximal 8 Ergebnisse, sortiert nach Passung. Sprache: Deutsch.
""".trim()

    fun userPrompt(query: SearchQuery, today: LocalDate): String = buildString {
        appendLine("Heute ist $today.")
        appendLine("Suche im Umkreis von ${query.radiusKm} km um „${query.city}“.")
        appendLine("Zeitraum: ${query.dateFrom} bis ${query.dateTo} (nur Termine in diesem Zeitraum).")
        appendLine("Budget: ${query.budget.promptLabel}.")
        when (query.mode) {
            SearchMode.GOING_OUT -> appendLine("Modus: Ausgehen & Events.")
            SearchMode.FAMILY -> appendLine(
                "Modus: Familien- & Tagesausflug (musikunabhängig). Schwerpunkt auf Ausflugszielen, nicht auf Konzerten oder Partys."
            )
        }
        if (query.ageGroups.isNotEmpty()) {
            appendLine("Geeignet für: ${query.ageGroups.joinToString { it.promptLabel }}.")
        }
        if (query.categories.isNotEmpty()) {
            appendLine("Kategorien: ${query.categories.joinToString { it.label }}.")
        }
        if (query.moods.isNotEmpty()) appendLine("Stimmung: ${query.moods.joinToString { it.label }}.")
        if (query.tags.isNotEmpty()) appendLine("Eigene Tags/Wünsche: ${query.tags.joinToString(" ")}.")
        query.groupContext?.let { appendLine(it) }
        if (query.freeText.isNotBlank()) appendLine("Zusätzlicher Wunsch: ${query.freeText.trim()}")
        append("Gib nur verifizierte Ergebnisse mit Quellen-URL im geforderten JSON-Schema zurück.")
    }
}
