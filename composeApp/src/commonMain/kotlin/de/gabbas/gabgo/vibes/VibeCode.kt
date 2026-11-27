package de.gabbas.gabgo.vibes

import de.gabbas.gabgo.model.AgeGroup
import de.gabbas.gabgo.model.Budget
import de.gabbas.gabgo.model.Category
import de.gabbas.gabgo.model.Mood
import de.gabbas.gabgo.platform.Compression
import kotlin.io.encoding.Base64
import kotlin.io.encoding.ExperimentalEncodingApi
import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable
import kotlinx.serialization.json.Json

/** One person's taste profile, shared via QR code or copy & paste. Short field names keep codes small. */
@Serializable
data class VibeProfile(
    @SerialName("n") val name: String,
    @SerialName("m") val moods: Set<Mood> = emptySet(),
    @SerialName("c") val categories: Set<Category> = emptySet(),
    @SerialName("t") val tags: Set<String> = emptySet(),
    @SerialName("a") val ageGroups: Set<AgeGroup> = emptySet(),
    @SerialName("b") val budget: Budget = Budget.ANY,
)

data class WeightedItem<T>(val item: T, val count: Int)

/** Result of merging several profiles: what everybody shares and what only some like. */
data class GroupVibe(
    val members: List<VibeProfile>,
    val moods: List<WeightedItem<Mood>>,
    val categories: List<WeightedItem<Category>>,
    val tags: List<WeightedItem<String>>,
    val ageGroups: Set<AgeGroup>,
    val budget: Budget,
) {
    val size: Int get() = members.size
    val sharedMoods: Set<Mood> get() = moods.filter { it.count == size }.map { it.item }.toSet()
    val sharedCategories: Set<Category> get() = categories.filter { it.count == size }.map { it.item }.toSet()
    val sharedTags: Set<String> get() = tags.filter { it.count == size }.map { it.item }.toSet()

    /** Items liked by at least half of the group – used as search filters. */
    fun majorityMoods() = moods.filter { it.count * 2 >= size }.map { it.item }.toSet()
    fun majorityCategories() = categories.filter { it.count * 2 >= size }.map { it.item }.toSet()
    fun majorityTags() = tags.filter { it.count * 2 >= size }.map { it.item }.toSet()

    fun describeForPrompt(): String = buildString {
        append("Gruppe aus $size Personen (${members.joinToString { it.name }}). ")
        fun <T> line(label: String, items: List<WeightedItem<T>>, name: (T) -> String) {
            if (items.isEmpty()) return
            append(label).append(": ")
            append(items.joinToString { "${name(it.item)} (${it.count}/$size)" })
            append(". ")
        }
        line("Stimmungen", moods) { it.label }
        line("Kategorien", categories) { it.label }
        line("Tags", tags) { it }
        if (ageGroups.isNotEmpty()) append("Altersgruppen dabei: ${ageGroups.joinToString { it.promptLabel }}. ")
        append("Budget (kleinstes gemeinsames): ${budget.promptLabel}. ")
        append("Bevorzuge Vorschläge, die möglichst viele Personen glücklich machen – zuerst Gemeinsamkeiten aller.")
    }
}

object VibeCode {
    const val PREFIX = "GV1."
    private val json = Json { ignoreUnknownKeys = true; encodeDefaults = false }

    @OptIn(ExperimentalEncodingApi::class)
    private val base64 = Base64.UrlSafe.withPadding(Base64.PaddingOption.ABSENT_OPTIONAL)

    @OptIn(ExperimentalEncodingApi::class)
    fun encode(profile: VibeProfile): String {
        val normalized = profile.copy(tags = profile.tags.map { normalizeTag(it) }.filter { it.length > 1 }.toSet())
        val raw = json.encodeToString(VibeProfile.serializer(), normalized).encodeToByteArray()
        return PREFIX + base64.encode(Compression.deflate(raw))
    }

    /** Accepts a raw code or any text containing one (e.g. a chat message or QR payload). */
    @OptIn(ExperimentalEncodingApi::class)
    fun decode(text: String): VibeProfile {
        val start = text.indexOf(PREFIX)
        require(start >= 0) { "Kein GabGo-Vibe-Code gefunden." }
        val body = text.substring(start + PREFIX.length)
            .takeWhile { it.isLetterOrDigit() || it == '-' || it == '_' }
        require(body.isNotEmpty()) { "Vibe-Code ist leer." }
        val raw = try {
            Compression.inflate(base64.decode(body))
        } catch (e: Exception) {
            throw IllegalArgumentException("Vibe-Code ist beschädigt.", e)
        }
        return json.decodeFromString(VibeProfile.serializer(), raw.decodeToString())
    }

    fun merge(profiles: List<VibeProfile>): GroupVibe {
        require(profiles.isNotEmpty()) { "Mindestens eine Person nötig." }
        fun <T> weigh(select: (VibeProfile) -> Set<T>): List<WeightedItem<T>> {
            val counts = linkedMapOf<T, Int>()
            profiles.forEach { p -> select(p).forEach { counts[it] = (counts[it] ?: 0) + 1 } }
            return counts.entries.sortedByDescending { it.value }.map { WeightedItem(it.key, it.value) }
        }
        return GroupVibe(
            members = profiles,
            moods = weigh { it.moods },
            categories = weigh { it.categories },
            tags = weighTags(profiles),
            ageGroups = profiles.flatMap { it.ageGroups }.toSet(),
            budget = profiles.minByOrNull { it.budget.rank }!!.budget,
        )
    }

    /** Tags match case-insensitively (#museum == #Museum); the first spelling wins. */
    private fun weighTags(profiles: List<VibeProfile>): List<WeightedItem<String>> {
        val spelling = linkedMapOf<String, String>()
        val counts = linkedMapOf<String, Int>()
        profiles.forEach { p ->
            p.tags.map { normalizeTag(it) }.filter { it.length > 1 }.distinctBy { it.lowercase() }.forEach { tag ->
                val key = tag.lowercase()
                spelling.getOrPut(key) { tag }
                counts[key] = (counts[key] ?: 0) + 1
            }
        }
        return counts.entries.sortedByDescending { it.value }.map { WeightedItem(spelling.getValue(it.key), it.value) }
    }

    fun normalizeTag(tag: String): String {
        val clean = tag.trim().removePrefix("#").filter { it.isLetterOrDigit() || it == '-' || it == '_' }
        return if (clean.isEmpty()) "" else "#$clean"
    }
}
