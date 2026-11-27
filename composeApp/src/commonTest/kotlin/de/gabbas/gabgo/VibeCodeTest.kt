package de.gabbas.gabgo

import de.gabbas.gabgo.model.AgeGroup
import de.gabbas.gabgo.model.Budget
import de.gabbas.gabgo.model.Category
import de.gabbas.gabgo.model.Mood
import de.gabbas.gabgo.vibes.VibeCode
import de.gabbas.gabgo.vibes.VibeProfile
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFailsWith
import kotlin.test.assertTrue

class VibeCodeTest {
    private val anna = VibeProfile(
        name = "Anna",
        moods = setOf(Mood.RELAXED, Mood.CULTURE, Mood.ROMANTIC),
        categories = setOf(Category.MUSEUMS, Category.RESTAURANTS, Category.WELLNESS),
        tags = setOf("#Museum", "LowCarb", "#Regenwetter"),
        ageGroups = setOf(AgeGroup.ADULTS),
        budget = Budget.HIGH,
    )
    private val ben = VibeProfile(
        name = "Ben",
        moods = setOf(Mood.RELAXED, Mood.ADVENTURE),
        categories = setOf(Category.MUSEUMS, Category.THEME_PARKS),
        tags = setOf("#museum", "#Outdoor"),
        ageGroups = setOf(AgeGroup.ADULTS, AgeGroup.KIDS),
        budget = Budget.MEDIUM,
    )
    private val cleo = VibeProfile(
        name = "Cleo",
        moods = setOf(Mood.RELAXED, Mood.CULTURE),
        categories = setOf(Category.MUSEUMS, Category.ZOOS),
        tags = setOf("#Museum"),
        ageGroups = setOf(AgeGroup.TODDLERS),
        budget = Budget.ANY,
    )

    @Test
    fun roundTripPreservesProfile() {
        val code = VibeCode.encode(anna)
        assertTrue(code.startsWith("GV1."))
        assertTrue(code.all { it.isLetterOrDigit() || it in "._-" }, "QR/URL-safe alphabet")
        val decoded = VibeCode.decode(code)
        assertEquals(anna.copy(tags = setOf("#Museum", "#LowCarb", "#Regenwetter")), decoded)
    }

    @Test
    fun codeIsCompact() {
        assertTrue(VibeCode.encode(anna).length < 200, "code too long for a comfortable QR code")
    }

    @Test
    fun decodeFindsCodeInsideText() {
        val code = VibeCode.encode(ben)
        assertEquals("Ben", VibeCode.decode("Hey, hier mein GabGo-Vibe: $code – bis später!").name)
    }

    @Test
    fun brokenCodesAreRejected() {
        assertFailsWith<IllegalArgumentException> { VibeCode.decode("kein code") }
        assertFailsWith<IllegalArgumentException> { VibeCode.decode("GV1.") }
        assertFailsWith<IllegalArgumentException> { VibeCode.decode("GV1.AAAAAAAAAAAA") }
    }

    @Test
    fun mergeComputesSharedAndMajority() {
        val g = VibeCode.merge(listOf(anna, ben, cleo))
        assertEquals(3, g.size)
        assertEquals(setOf(Mood.RELAXED), g.sharedMoods)
        assertEquals(setOf(Mood.RELAXED, Mood.CULTURE), g.majorityMoods())
        assertEquals(setOf(Category.MUSEUMS), g.sharedCategories)
        assertEquals(setOf("#Museum"), g.sharedTags)
        assertEquals(setOf(AgeGroup.ADULTS, AgeGroup.KIDS, AgeGroup.TODDLERS), g.ageGroups)
        assertEquals(Budget.MEDIUM, g.budget)
        assertEquals(Mood.RELAXED, g.moods.first().item)
        assertEquals(3, g.moods.first().count)
        val prompt = g.describeForPrompt()
        assertTrue("Anna" in prompt && "Ben" in prompt && "Cleo" in prompt)
        assertTrue("Entspannt (3/3)" in prompt)
    }

    @Test
    fun mergeSurvivesSerialization() {
        val viaCodes = listOf(anna, ben, cleo).map { VibeCode.decode(VibeCode.encode(it)) }
        val direct = VibeCode.merge(listOf(anna, ben, cleo))
        val decoded = VibeCode.merge(viaCodes)
        assertEquals(direct.sharedMoods, decoded.sharedMoods)
        assertEquals(direct.sharedCategories, decoded.sharedCategories)
        assertEquals(direct.budget, decoded.budget)
    }

    @Test
    fun normalizeTag() {
        assertEquals("#Kinderfreundlich", VibeCode.normalizeTag("  Kinderfreundlich "))
        assertEquals("#LowCarb", VibeCode.normalizeTag("##Low Carb!"))
        assertEquals("", VibeCode.normalizeTag("#"))
    }
}
