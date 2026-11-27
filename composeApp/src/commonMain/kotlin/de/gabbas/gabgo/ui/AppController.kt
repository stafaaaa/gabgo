package de.gabbas.gabgo.ui

import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import de.gabbas.gabgo.ai.EventSearchService
import de.gabbas.gabgo.ai.GeminiProvider
import de.gabbas.gabgo.ai.LiveSearchProvider
import de.gabbas.gabgo.ai.PerplexityProvider
import de.gabbas.gabgo.calendar.IcsGenerator
import de.gabbas.gabgo.data.AppRepository
import de.gabbas.gabgo.license.LicensePayload
import de.gabbas.gabgo.license.LicenseResult
import de.gabbas.gabgo.license.LicenseValidator
import de.gabbas.gabgo.license.Plan
import de.gabbas.gabgo.links.LinkBuilder
import de.gabbas.gabgo.model.AgeGroup
import de.gabbas.gabgo.model.Budget
import de.gabbas.gabgo.model.Category
import de.gabbas.gabgo.model.EventSuggestion
import de.gabbas.gabgo.model.Mood
import de.gabbas.gabgo.model.ProviderType
import de.gabbas.gabgo.model.SearchMode
import de.gabbas.gabgo.model.SearchOutcome
import de.gabbas.gabgo.model.SearchQuery
import de.gabbas.gabgo.model.SearchStatus
import de.gabbas.gabgo.model.StoredProviderSettings
import de.gabbas.gabgo.platform.CalendarExporter
import de.gabbas.gabgo.platform.ExternalLauncher
import de.gabbas.gabgo.platform.currentPlatform
import de.gabbas.gabgo.ui.theme.GabGoTheme
import de.gabbas.gabgo.vibes.GroupVibe
import de.gabbas.gabgo.vibes.VibeCode
import de.gabbas.gabgo.vibes.VibeProfile
import io.ktor.client.HttpClient
import io.ktor.client.plugins.HttpTimeout
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Job
import kotlinx.coroutines.launch
import kotlinx.datetime.Clock
import kotlinx.datetime.DatePeriod
import kotlinx.datetime.LocalDate
import kotlinx.datetime.TimeZone
import kotlinx.datetime.plus
import kotlinx.datetime.todayIn

enum class Tab(val label: String) { RADAR("Radar"), VIBES("Unsere Vibes"), FAVORITES("Merkliste"), SETTINGS("Einstellungen") }

enum class DatePreset(val label: String) {
    TODAY("Heute"), TOMORROW("Morgen"), WEEKEND("Wochenende"), WEEK("7 Tage"), MONTH("30 Tage"), CUSTOM("Zeitraum…")
}

class AppController(
    private val repo: AppRepository,
    private val scope: CoroutineScope,
    private val validator: LicenseValidator = LicenseValidator(),
) {
    private val http = HttpClient {
        install(HttpTimeout) {
            requestTimeoutMillis = 150_000
            connectTimeoutMillis = 20_000
            socketTimeoutMillis = 150_000
        }
    }

    fun today(): LocalDate = Clock.System.todayIn(TimeZone.currentSystemDefault())

    // --- global UI ---
    var tab by mutableStateOf(Tab.RADAR)
    var theme by mutableStateOf(repo.theme); private set
    var message by mutableStateOf<String?>(null)
    var selectedEvent by mutableStateOf<EventSuggestion?>(null)

    // --- license / demo ---
    var license by mutableStateOf<LicensePayload?>(repo.licenseKey?.let { (validator.validate(it, today()) as? LicenseResult.Valid)?.payload })
        private set
    var demoUsed by mutableStateOf(repo.demoSearchesUsed); private set
    val isPro: Boolean
        get() = license?.let { p -> p.exp?.let { runCatching { LocalDate.parse(it) }.getOrNull() }?.let { today() <= it } ?: true } == true
    val demoLeft: Int get() = (Plan.FREE_DEMO_SEARCHES - demoUsed).coerceAtLeast(0)

    // --- radar form ---
    var mode by mutableStateOf(SearchMode.GOING_OUT)
    var city by mutableStateOf(repo.lastCity)
    var radiusKm by mutableStateOf(25)
    var datePreset by mutableStateOf(DatePreset.WEEKEND)
    var customFrom by mutableStateOf<LocalDate?>(null)
    var customTo by mutableStateOf<LocalDate?>(null)
    var budget by mutableStateOf(Budget.ANY)
    var moods by mutableStateOf(emptySet<Mood>())
    var categories by mutableStateOf(emptySet<Category>())
    var ageGroups by mutableStateOf(emptySet<AgeGroup>())
    var selectedTags by mutableStateOf(emptySet<String>())
    var freeText by mutableStateOf("")

    var searching by mutableStateOf(false); private set
    var outcome by mutableStateOf<SearchOutcome?>(null); private set
    var lastSearchWasGroup by mutableStateOf(false); private set
    private var searchJob: Job? = null

    // --- persistent lists ---
    var favorites by mutableStateOf(repo.favorites); private set
    var customTags by mutableStateOf(repo.customTags); private set

    // --- settings ---
    var geminiKey by mutableStateOf(repo.geminiKey); private set
    var perplexityKey by mutableStateOf(repo.perplexityKey); private set
    var providerSettings by mutableStateOf(repo.providerSettings); private set

    // --- vibes ---
    var myVibe by mutableStateOf(repo.myVibe ?: VibeProfile(name = "Ich")); private set
    var groupMembers by mutableStateOf(repo.groupMembers); private set

    fun dateRange(): Pair<LocalDate, LocalDate> {
        val t = today()
        return when (datePreset) {
            DatePreset.TODAY -> t to t
            DatePreset.TOMORROW -> t.plus(DatePeriod(days = 1)).let { it to it }
            DatePreset.WEEKEND -> {
                val dow = t.dayOfWeek.ordinal // Monday = 0 … Sunday = 6
                val start = if (dow >= 4) t else t.plus(DatePeriod(days = 4 - dow))
                start to t.plus(DatePeriod(days = 6 - dow))
            }
            DatePreset.WEEK -> t to t.plus(DatePeriod(days = 6))
            DatePreset.MONTH -> t to t.plus(DatePeriod(days = 29))
            DatePreset.CUSTOM -> (customFrom ?: t) to (customTo ?: customFrom ?: t)
        }
    }

    fun buildQuery(): SearchQuery {
        val (from, to) = dateRange()
        return SearchQuery(
            city = city.trim(), radiusKm = radiusKm, dateFrom = from, dateTo = to, budget = budget,
            moods = moods, mode = mode,
            categories = if (mode == SearchMode.FAMILY && categories.isEmpty()) Category.familyDefaults.toSet() else categories,
            ageGroups = ageGroups, tags = selectedTags, freeText = freeText,
        )
    }

    private fun providers(): List<LiveSearchProvider> {
        val s = providerSettings
        val gemini = geminiKey.takeIf { it.isNotBlank() }?.let { GeminiProvider(http, it, s.geminiModel.ifBlank { "gemini-2.5-flash" }) }
        val pplx = perplexityKey.takeIf { it.isNotBlank() }?.let { PerplexityProvider(http, it, s.perplexityModel.ifBlank { "sonar-pro" }) }
        val ordered = if (s.primary == ProviderType.GEMINI) listOf(gemini, pplx) else listOf(pplx, gemini)
        return (if (s.fallbackEnabled) ordered else ordered.take(1)).filterNotNull()
    }

    fun searchRadar() {
        if (city.isBlank()) { message = "Bitte eine Stadt eingeben."; return }
        repo.lastCity = city.trim()
        lastSearchWasGroup = false
        runSearch(buildQuery())
    }

    fun searchGroup() {
        if (city.isBlank()) { message = "Bitte im Radar eine Stadt eingeben – die Gruppensuche nutzt Ort und Zeitraum aus dem Radar."; tab = Tab.RADAR; return }
        val group = group()
        val base = buildQuery()
        val query = base.copy(
            moods = base.moods + group.majorityMoods(),
            categories = (categories + group.majorityCategories()).filterNot { mode == SearchMode.FAMILY && it.musicRelated }.toSet(),
            tags = base.tags + group.majorityTags(),
            ageGroups = base.ageGroups + group.ageGroups,
            budget = if (group.budget.rank < base.budget.rank) group.budget else base.budget,
            groupContext = group.describeForPrompt(),
        )
        lastSearchWasGroup = true
        tab = Tab.RADAR
        runSearch(query)
    }

    private fun runSearch(query: SearchQuery) {
        if (!isPro && demoLeft <= 0) {
            message = "Deine ${Plan.FREE_DEMO_SEARCHES} Demo-Suchen sind aufgebraucht. Schalte GabGo Pro in den Einstellungen frei."
            tab = Tab.SETTINGS
            return
        }
        val providers = providers()
        searchJob?.cancel()
        searching = true
        searchJob = scope.launch {
            try {
                val result = EventSearchService(providers).search(query, today())
                outcome = result
                if (!isPro && result.status != SearchStatus.ERROR) {
                    demoUsed += 1
                    repo.demoSearchesUsed = demoUsed
                }
            } finally {
                searching = false
            }
        }
    }

    fun cancelSearch() { searchJob?.cancel(); searching = false }

    // --- favorites ---
    fun isFavorite(e: EventSuggestion) = favorites.any { it.id == e.id }
    fun toggleFavorite(e: EventSuggestion) {
        favorites = if (isFavorite(e)) favorites.filterNot { it.id == e.id } else listOf(e) + favorites
        repo.favorites = favorites
    }

    // --- tags ---
    fun addTag(raw: String): Boolean {
        val tag = VibeCode.normalizeTag(raw)
        if (tag.length < 2) { message = "Tag ist leer."; return false }
        if (customTags.any { it.equals(tag, ignoreCase = true) }) { message = "$tag gibt es schon."; return false }
        customTags = customTags + tag
        repo.customTags = customTags
        return true
    }

    fun renameTag(old: String, raw: String) {
        val tag = VibeCode.normalizeTag(raw)
        if (tag.length < 2) return
        customTags = customTags.map { if (it == old) tag else it }.distinct()
        repo.customTags = customTags
        if (old in selectedTags) selectedTags = selectedTags - old + tag
        if (old in myVibe.tags) updateMyVibe(myVibe.copy(tags = myVibe.tags - old + tag))
    }

    fun deleteTag(tag: String) {
        customTags = customTags - tag
        repo.customTags = customTags
        selectedTags = selectedTags - tag
        if (tag in myVibe.tags) updateMyVibe(myVibe.copy(tags = myVibe.tags - tag))
    }

    // --- theme / license ---
    fun selectTheme(t: GabGoTheme) {
        if (t.proOnly && !isPro) { message = "„${t.label}“ ist Teil von GabGo Pro."; return }
        theme = t
        repo.theme = t
    }

    fun activateLicense(key: String) {
        when (val r = validator.validate(key, today())) {
            is LicenseResult.Valid -> {
                license = r.payload
                repo.licenseKey = key.filterNot { it.isWhitespace() }
                message = "GabGo Pro freigeschaltet – danke, ${r.payload.name}!"
            }
            is LicenseResult.Invalid -> message = r.reason
        }
    }

    fun removeLicense() {
        license = null
        repo.licenseKey = null
        if (theme.proOnly) selectTheme(GabGoTheme.PULSE)
    }

    // --- settings ---
    fun saveApiKeys(gemini: String, perplexity: String) {
        repo.geminiKey = gemini; repo.perplexityKey = perplexity
        geminiKey = repo.geminiKey; perplexityKey = repo.perplexityKey
        message = "API-Keys gespeichert."
    }

    fun updateProviderSettings(s: StoredProviderSettings) {
        providerSettings = s
        repo.providerSettings = s
    }

    // --- vibes ---
    fun updateMyVibe(v: VibeProfile) { myVibe = v; repo.myVibe = v }

    fun myVibeCode(): String = VibeCode.encode(myVibe)

    val maxGroupSize: Int get() = if (isPro) Int.MAX_VALUE else Plan.FREE_MAX_GROUP_SIZE

    fun importVibe(text: String): Boolean {
        val profile = try { VibeCode.decode(text) } catch (e: Exception) { message = e.message ?: "Vibe-Code ungültig."; return false }
        if (groupMembers.size + 1 >= maxGroupSize) {
            message = "In der Demo sind Gruppen auf ${Plan.FREE_MAX_GROUP_SIZE} Personen begrenzt. GabGo Pro hebt das Limit auf."
            return false
        }
        var p = profile
        var n = 2
        while (groupMembers.any { it.name == p.name } || p.name == myVibe.name) p = profile.copy(name = "${profile.name} ${n++}")
        groupMembers = groupMembers + p
        repo.groupMembers = groupMembers
        message = "${p.name} ist jetzt dabei."
        return true
    }

    fun removeMember(p: VibeProfile) { groupMembers = groupMembers - p; repo.groupMembers = groupMembers }

    fun group(): GroupVibe = VibeCode.merge(listOf(myVibe) + groupMembers)

    // --- actions ---
    fun exportCalendar(e: EventSuggestion) {
        val ok = runCatching { CalendarExporter.exportIcs(IcsGenerator.fileName(e), IcsGenerator.generate(e)) }.getOrElse { false }
        if (!ok) message = "Kalenderdatei konnte nicht geöffnet werden."
    }

    fun openRoute(e: EventSuggestion) = open(LinkBuilder.mapsUrl(e.fullAddress, currentPlatform))
    fun openUber(e: EventSuggestion) = open(LinkBuilder.uberUrl(e.fullAddress))
    fun open(url: String) { if (!ExternalLauncher.openUrl(url)) message = "Link konnte nicht geöffnet werden: $url" }
}
