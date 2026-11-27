package de.gabbas.gabgo

import de.gabbas.gabgo.ai.ResultParser
import de.gabbas.gabgo.model.ProviderType
import de.gabbas.gabgo.model.SearchQuery
import de.gabbas.gabgo.model.SearchStatus
import de.gabbas.gabgo.model.SourceLink
import kotlinx.datetime.LocalDate
import kotlin.test.Test
import kotlin.test.assertEquals

class ResultParserTest {
    private val query = SearchQuery("Köln", 25, LocalDate(2026, 12, 4), LocalDate(2026, 12, 6))
    private val sources = listOf(SourceLink("koeln.de", "https://www.koeln.de/"))

    private val answer = """
        Hier die Ergebnisse:
        ```json
        {"status":"ok","message":"","results":[
          {"title":"Kölner Lichter","start":"2026-12-05T19:00","venue":"Rheinufer","address":"Konrad-Adenauer-Ufer","city":"Köln","sourceUrl":"https://www.koeln.de/lichter"},
          {"title":"Ohne Quelle","start":"2026-12-05","venue":"Dom","sourceUrl":""},
          {"title":"Falsches Datum","start":"2027-01-10","venue":"Dom","sourceUrl":"https://example.com/x"},
          {"title":"Kein Ort","start":"2026-12-05","sourceUrl":"https://example.com/y"},
          {"title":"Ausstellung","start":"2026-11-01","end":"2027-02-01","venue":"Museum Ludwig","sourceUrl":"https://www.museum-ludwig.de/"}
        ]}
        ```
    """.trimIndent()

    @Test
    fun keepsOnlyVerifiedEvents() {
        val r = ResultParser.parse(answer, query, ProviderType.GEMINI, sources)
        assertEquals(SearchStatus.VERIFIED, r.status)
        assertEquals(listOf("Kölner Lichter", "Ausstellung"), r.events.map { it.title })
        assertEquals(3, r.droppedCount)
    }

    @Test
    fun noGroundingMeansNoResults() {
        val r = ResultParser.parse(answer, query, ProviderType.PERPLEXITY, emptyList())
        assertEquals(SearchStatus.NO_VERIFIED_DATA, r.status)
        assertEquals(0, r.events.size)
    }

    @Test
    fun garbageIsNotShown() {
        assertEquals(SearchStatus.NO_VERIFIED_DATA, ResultParser.parse("Leider nichts gefunden.", query, ProviderType.GEMINI, sources).status)
        assertEquals(SearchStatus.NO_VERIFIED_DATA, ResultParser.parse("{kaputt", query, ProviderType.GEMINI, sources).status)
    }
}
