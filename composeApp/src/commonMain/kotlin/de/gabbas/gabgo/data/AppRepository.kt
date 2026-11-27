package de.gabbas.gabgo.data

import de.gabbas.gabgo.model.EventSuggestion
import de.gabbas.gabgo.model.StoredProviderSettings
import de.gabbas.gabgo.platform.KeyValueStore
import de.gabbas.gabgo.ui.theme.GabGoTheme
import de.gabbas.gabgo.vibes.VibeProfile
import kotlinx.serialization.KSerializer
import kotlinx.serialization.builtins.ListSerializer
import kotlinx.serialization.builtins.serializer
import kotlinx.serialization.json.Json

class AppRepository(private val store: KeyValueStore) {
    private val json = Json { ignoreUnknownKeys = true; encodeDefaults = true }

    private fun <T> read(key: String, serializer: KSerializer<T>): T? =
        store.getString(key)?.let { runCatching { json.decodeFromString(serializer, it) }.getOrNull() }

    private fun <T> write(key: String, serializer: KSerializer<T>, value: T) =
        store.putString(key, json.encodeToString(serializer, value))

    var geminiKey: String
        get() = store.getString(K_GEMINI).orEmpty()
        set(v) = store.putString(K_GEMINI, v.trim().ifEmpty { null })

    var perplexityKey: String
        get() = store.getString(K_PERPLEXITY).orEmpty()
        set(v) = store.putString(K_PERPLEXITY, v.trim().ifEmpty { null })

    var providerSettings: StoredProviderSettings
        get() = read(K_PROVIDER, StoredProviderSettings.serializer()) ?: StoredProviderSettings()
        set(v) = write(K_PROVIDER, StoredProviderSettings.serializer(), v)

    var theme: GabGoTheme
        get() = store.getString(K_THEME)?.let { n -> GabGoTheme.entries.firstOrNull { it.name == n } } ?: GabGoTheme.PULSE
        set(v) = store.putString(K_THEME, v.name)

    var favorites: List<EventSuggestion>
        get() = read(K_FAVORITES, ListSerializer(EventSuggestion.serializer())) ?: emptyList()
        set(v) = write(K_FAVORITES, ListSerializer(EventSuggestion.serializer()), v)

    var customTags: List<String>
        get() = read(K_TAGS, ListSerializer(String.serializer())) ?: DEFAULT_TAGS
        set(v) = write(K_TAGS, ListSerializer(String.serializer()), v)

    var licenseKey: String?
        get() = store.getString(K_LICENSE)
        set(v) = store.putString(K_LICENSE, v)

    var demoSearchesUsed: Int
        get() = store.getString(K_DEMO)?.toIntOrNull() ?: 0
        set(v) = store.putString(K_DEMO, v.toString())

    var myVibe: VibeProfile?
        get() = read(K_VIBE, VibeProfile.serializer())
        set(v) = if (v == null) store.putString(K_VIBE, null) else write(K_VIBE, VibeProfile.serializer(), v)

    var groupMembers: List<VibeProfile>
        get() = read(K_GROUP, ListSerializer(VibeProfile.serializer())) ?: emptyList()
        set(v) = write(K_GROUP, ListSerializer(VibeProfile.serializer()), v)

    var lastCity: String
        get() = store.getString(K_CITY).orEmpty()
        set(v) = store.putString(K_CITY, v)

    companion object {
        val DEFAULT_TAGS = listOf("#Freizeitpark", "#Museum", "#Kinderfreundlich", "#Outdoor", "#LowCarb", "#Regenwetter")
        private const val K_GEMINI = "api.gemini"
        private const val K_PERPLEXITY = "api.perplexity"
        private const val K_PROVIDER = "provider.settings"
        private const val K_THEME = "ui.theme"
        private const val K_FAVORITES = "favorites"
        private const val K_TAGS = "tags.custom"
        private const val K_LICENSE = "license.key"
        private const val K_DEMO = "license.demoUsed"
        private const val K_VIBE = "vibes.me"
        private const val K_GROUP = "vibes.group"
        private const val K_CITY = "radar.city"
    }
}
