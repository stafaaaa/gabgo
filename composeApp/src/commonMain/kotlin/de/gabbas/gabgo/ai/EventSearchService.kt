package de.gabbas.gabgo.ai

import de.gabbas.gabgo.model.SearchOutcome
import de.gabbas.gabgo.model.SearchQuery
import de.gabbas.gabgo.model.SearchStatus
import kotlinx.coroutines.CancellationException
import kotlinx.datetime.LocalDate

/** Runs the live search on the primary provider and, if configured, on the fallback provider. */
class EventSearchService(private val providers: List<LiveSearchProvider>) {

    suspend fun search(query: SearchQuery, today: LocalDate): SearchOutcome {
        if (providers.isEmpty()) {
            return SearchOutcome(
                SearchStatus.ERROR,
                message = "Bitte zuerst in den Einstellungen einen API-Key für Google Gemini oder Perplexity hinterlegen.",
            )
        }
        val userPrompt = PromptBuilder.userPrompt(query, today)
        var last: SearchOutcome? = null
        val errors = mutableListOf<String>()
        for (provider in providers) {
            val outcome = try {
                val answer = provider.search(PromptBuilder.SYSTEM_PROMPT, userPrompt)
                ResultParser.parse(answer.text, query, provider.type, answer.sources)
            } catch (e: CancellationException) {
                throw e
            } catch (e: Exception) {
                errors += e.message ?: e::class.simpleName.orEmpty()
                SearchOutcome(SearchStatus.ERROR, provider = provider.type, message = e.message ?: "Unbekannter Fehler")
            }
            if (outcome.status == SearchStatus.VERIFIED) return outcome
            if (last == null || last.status == SearchStatus.ERROR) last = outcome
        }
        val result = last!!
        return if (result.status == SearchStatus.ERROR && errors.size > 1) {
            result.copy(message = errors.joinToString("\n"))
        } else result
    }
}
