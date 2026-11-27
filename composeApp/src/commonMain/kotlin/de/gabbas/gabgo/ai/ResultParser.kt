package de.gabbas.gabgo.ai

import de.gabbas.gabgo.calendar.IcsGenerator
import de.gabbas.gabgo.model.AiEventResponse
import de.gabbas.gabgo.model.EventSuggestion
import de.gabbas.gabgo.model.ProviderType
import de.gabbas.gabgo.model.SearchOutcome
import de.gabbas.gabgo.model.SearchQuery
import de.gabbas.gabgo.model.SearchStatus
import de.gabbas.gabgo.model.SourceLink
import kotlinx.serialization.json.Json

/** Parses model output and drops everything that is not backed by a date, place and source link. */
object ResultParser {
    private val json = Json { ignoreUnknownKeys = true; isLenient = true; coerceInputValues = true }

    fun extractJson(text: String): String? {
        val cleaned = text.replace("```json", "```").let { t ->
            val fence = Regex("```\\s*(\\{[\\s\\S]*?\\})\\s*```").find(t)
            fence?.groupValues?.get(1) ?: t
        }
        val start = cleaned.indexOf('{')
        val end = cleaned.lastIndexOf('}')
        return if (start >= 0 && end > start) cleaned.substring(start, end + 1) else null
    }

    fun parse(
        text: String,
        query: SearchQuery,
        provider: ProviderType,
        groundingSources: List<SourceLink>,
    ): SearchOutcome {
        val body = extractJson(text) ?: return SearchOutcome(
            SearchStatus.NO_VERIFIED_DATA, provider = provider, sources = groundingSources,
            message = "Die KI hat keine auswertbaren, verifizierten Live-Daten geliefert.",
        )
        val response = try {
            json.decodeFromString(AiEventResponse.serializer(), body)
        } catch (e: Exception) {
            return SearchOutcome(
                SearchStatus.NO_VERIFIED_DATA, provider = provider, sources = groundingSources,
                message = "Antwort der KI war nicht im erwarteten Format – es werden keine ungeprüften Daten angezeigt.",
            )
        }
        if (groundingSources.isEmpty()) {
            return SearchOutcome(
                SearchStatus.NO_VERIFIED_DATA, provider = provider,
                message = "Die KI hat keine Live-Websuche durchgeführt. Ohne Quellen zeigt GabGo keine Ergebnisse an, um erfundene Termine auszuschließen.",
            )
        }
        val valid = response.results.filter { isVerified(it, query) }.distinctBy { it.id }
        val dropped = response.results.size - valid.size
        if (valid.isEmpty()) {
            return SearchOutcome(
                SearchStatus.NO_VERIFIED_DATA, provider = provider, sources = groundingSources, droppedCount = dropped,
                message = response.message.ifBlank { "Für diese Suche wurden keine verifizierten Live-Termine gefunden." },
            )
        }
        return SearchOutcome(
            SearchStatus.VERIFIED, events = valid, provider = provider, sources = groundingSources,
            droppedCount = dropped, message = response.message,
        )
    }

    fun isVerified(event: EventSuggestion, query: SearchQuery): Boolean {
        if (event.title.isBlank()) return false
        if (!isHttpUrl(event.sourceUrl)) return false
        if (event.ticketUrl != null && event.ticketUrl.isNotBlank() && !isHttpUrl(event.ticketUrl)) return false
        if (event.venue.isBlank() && event.address.isBlank()) return false
        val date = when (val w = IcsGenerator.parseDateTime(event.start)) {
            is IcsGenerator.When.Day -> w.date
            is IcsGenerator.When.Time -> w.dateTime.date
            null -> return false
        }
        val endDate = event.end?.let { IcsGenerator.parseDateTime(it) }?.let {
            when (it) {
                is IcsGenerator.When.Day -> it.date
                is IcsGenerator.When.Time -> it.dateTime.date
            }
        } ?: date
        // Accept events that overlap the requested window (multi-day events, exhibitions).
        return date <= query.dateTo && endDate >= query.dateFrom
    }

    fun isHttpUrl(url: String): Boolean {
        val u = url.trim()
        if (!(u.startsWith("https://") || u.startsWith("http://"))) return false
        val host = u.substringAfter("://").substringBefore('/').substringBefore('?')
        return host.contains('.') && !host.contains(' ')
    }
}
