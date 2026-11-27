package de.gabbas.gabgo.model

import kotlinx.datetime.LocalDate
import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable

enum class SearchMode(val label: String) {
    GOING_OUT("Ausgehen & Events"),
    FAMILY("Familie & Tagesausflug"),
}

enum class AgeGroup(val label: String, val promptLabel: String) {
    TODDLERS("Kleinkinder", "Kleinkinder (0–3 Jahre)"),
    KIDS("Kinder", "Kinder (4–12 Jahre)"),
    TEENS("Teenager", "Teenager (13–17 Jahre)"),
    ADULTS("Erwachsene/Paare", "Erwachsene bzw. Paare"),
}

enum class Category(val label: String, val musicRelated: Boolean = false) {
    CONCERTS("Konzerte & Live-Musik", musicRelated = true),
    PARTY("Partys & Clubs", musicRelated = true),
    FESTIVALS("Festivals & Stadtfeste"),
    THEME_PARKS("Freizeitparks"),
    MUSEUMS("Museen & Ausstellungen"),
    THEATER("Theater & Shows"),
    ZOOS("Zoos & Tierparks"),
    INDOOR_PLAY("Indoor-Spielplätze"),
    RESTAURANTS("Restaurants & Cafés"),
    WELLNESS("Wellness"),
    HOTELS("Hotels für Wochenendausflüge"),
    OUTDOOR("Sport & Outdoor"),
    MARKETS("Märkte & Flohmärkte"),
    COMEDY("Comedy & Kabarett"),
    ;

    companion object {
        val familyDefaults = listOf(THEME_PARKS, MUSEUMS, THEATER, ZOOS, INDOOR_PLAY, RESTAURANTS, WELLNESS, HOTELS, OUTDOOR)
    }
}

enum class Mood(val label: String) {
    RELAXED("Entspannt"),
    ROMANTIC("Romantisch"),
    ADVENTURE("Abenteuerlich"),
    SOCIAL("Gesellig"),
    CULTURE("Kulturell"),
    PARTY("Ausgelassen"),
    CREATIVE("Kreativ"),
    SPORTY("Sportlich"),
    COZY("Gemütlich"),
}

enum class Budget(val label: String, val promptLabel: String, val rank: Int) {
    FREE("Kostenlos", "kostenlos (0 €)", 0),
    LOW("bis 20 €", "maximal 20 € pro Person", 1),
    MEDIUM("bis 50 €", "maximal 50 € pro Person", 2),
    HIGH("bis 100 €", "maximal 100 € pro Person", 3),
    ANY("Egal", "beliebiges Budget", 4),
}

enum class ProviderType(val label: String) {
    GEMINI("Google Gemini (Google-Suche)"),
    PERPLEXITY("Perplexity Sonar"),
}

data class SearchQuery(
    val city: String,
    val radiusKm: Int,
    val dateFrom: LocalDate,
    val dateTo: LocalDate,
    val budget: Budget = Budget.ANY,
    val moods: Set<Mood> = emptySet(),
    val mode: SearchMode = SearchMode.GOING_OUT,
    val categories: Set<Category> = emptySet(),
    val ageGroups: Set<AgeGroup> = emptySet(),
    val tags: Set<String> = emptySet(),
    val groupContext: String? = null,
    val freeText: String = "",
)

@Serializable
data class EventSuggestion(
    val title: String,
    val category: String = "",
    val description: String = "",
    /** ISO-8601 local date (`2026-11-28`) or date-time (`2026-11-28T19:30`). */
    val start: String,
    val end: String? = null,
    val venue: String = "",
    val address: String = "",
    val city: String = "",
    val priceRange: String = "",
    val sourceUrl: String,
    val ticketUrl: String? = null,
    val openingHours: String? = null,
    val ageGroups: List<String> = emptyList(),
    val tags: List<String> = emptyList(),
    val familyFriendly: Boolean? = null,
) {
    val id: String get() = "${title.trim().lowercase()}|$start|${venue.trim().lowercase()}"
    val fullAddress: String
        get() = listOf(venue, address, city).map { it.trim() }.filter { it.isNotEmpty() }
            .distinct().joinToString(", ")
}

@Serializable
data class SourceLink(val title: String, val url: String)

enum class SearchStatus { VERIFIED, NO_VERIFIED_DATA, ERROR }

data class SearchOutcome(
    val status: SearchStatus,
    val events: List<EventSuggestion> = emptyList(),
    val message: String = "",
    val sources: List<SourceLink> = emptyList(),
    val provider: ProviderType? = null,
    val droppedCount: Int = 0,
)

@Serializable
data class AiEventResponse(
    val status: String = "ok",
    val message: String = "",
    val results: List<EventSuggestion> = emptyList(),
)

@Serializable
data class StoredProviderSettings(
    @SerialName("primary") val primary: ProviderType = ProviderType.GEMINI,
    @SerialName("fallback") val fallbackEnabled: Boolean = true,
    @SerialName("geminiModel") val geminiModel: String = "gemini-2.5-flash",
    @SerialName("perplexityModel") val perplexityModel: String = "sonar-pro",
)
