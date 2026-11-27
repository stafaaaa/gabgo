package de.gabbas.gabgo.ai

import de.gabbas.gabgo.model.ProviderType
import de.gabbas.gabgo.model.SourceLink
import io.ktor.client.HttpClient
import io.ktor.client.request.header
import io.ktor.client.request.post
import io.ktor.client.request.setBody
import io.ktor.client.statement.bodyAsText
import io.ktor.http.ContentType
import io.ktor.http.contentType
import io.ktor.http.isSuccess
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.contentOrNull
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import kotlinx.serialization.json.put
import kotlinx.serialization.json.putJsonArray
import kotlinx.serialization.json.putJsonObject

data class AiAnswer(val text: String, val sources: List<SourceLink>)

class AiException(message: String) : Exception(message)

/** Only providers with real live web access are allowed for the event search. */
interface LiveSearchProvider {
    val type: ProviderType
    suspend fun search(systemPrompt: String, userPrompt: String): AiAnswer
}

private val json = Json { ignoreUnknownKeys = true }

private fun JsonObject.str(key: String): String? = (this[key] as? kotlinx.serialization.json.JsonPrimitive)?.contentOrNull

private fun errorMessage(status: Int, body: String): String {
    val detail = runCatching {
        val o = json.parseToJsonElement(body).jsonObject
        (o["error"] as? JsonObject)?.str("message") ?: o.str("detail") ?: o.str("message")
    }.getOrNull()
    return when (status) {
        400 -> "Anfrage abgelehnt (400)${detail?.let { ": $it" } ?: ""}"
        401, 403 -> "API-Key ungültig oder ohne Berechtigung ($status)."
        429 -> "Kontingent/Rate-Limit erreicht (429). Bitte später erneut versuchen."
        else -> "Fehler $status${detail?.let { ": $it" } ?: ""}"
    }
}

/** Google Gemini with the `google_search` grounding tool enabled. */
class GeminiProvider(
    private val http: HttpClient,
    private val apiKey: String,
    private val model: String = "gemini-2.5-flash",
    private val baseUrl: String = "https://generativelanguage.googleapis.com/v1beta",
) : LiveSearchProvider {
    override val type = ProviderType.GEMINI

    fun requestBody(systemPrompt: String, userPrompt: String): JsonObject = buildJsonObject {
        putJsonObject("systemInstruction") {
            putJsonArray("parts") { add(buildJsonObject { put("text", systemPrompt) }) }
        }
        putJsonArray("contents") {
            add(buildJsonObject {
                put("role", "user")
                putJsonArray("parts") { add(buildJsonObject { put("text", userPrompt) }) }
            })
        }
        putJsonArray("tools") { add(buildJsonObject { putJsonObject("google_search") {} }) }
        putJsonObject("generationConfig") { put("temperature", 0.1) }
    }

    override suspend fun search(systemPrompt: String, userPrompt: String): AiAnswer {
        val response = http.post("$baseUrl/models/$model:generateContent") {
            header("x-goog-api-key", apiKey)
            contentType(ContentType.Application.Json)
            setBody(requestBody(systemPrompt, userPrompt).toString())
        }
        val body = response.bodyAsText()
        if (!response.status.isSuccess()) throw AiException("Gemini: " + errorMessage(response.status.value, body))
        return parseResponse(body)
    }

    companion object {
        fun parseResponse(body: String): AiAnswer {
            val root = json.parseToJsonElement(body).jsonObject
            val candidate = root["candidates"]?.jsonArray?.firstOrNull()?.jsonObject
                ?: throw AiException("Gemini: leere Antwort.")
            val text = candidate["content"]?.jsonObject?.get("parts")?.jsonArray
                ?.mapNotNull { it.jsonObject.str("text") }?.joinToString("") ?: ""
            val chunks = candidate["groundingMetadata"]?.jsonObject?.get("groundingChunks") as? JsonArray
            val sources = chunks.orEmpty().mapNotNull { c ->
                val web = c.jsonObject["web"]?.jsonObject ?: return@mapNotNull null
                val uri = web.str("uri") ?: return@mapNotNull null
                SourceLink(web.str("title") ?: uri, uri)
            }.distinctBy { it.url }
            return AiAnswer(text, sources)
        }
    }
}

/** Perplexity Sonar (`sonar` / `sonar-pro`) – always searches the live web and returns citations. */
class PerplexityProvider(
    private val http: HttpClient,
    private val apiKey: String,
    private val model: String = "sonar-pro",
    private val baseUrl: String = "https://api.perplexity.ai",
) : LiveSearchProvider {
    override val type = ProviderType.PERPLEXITY

    fun requestBody(systemPrompt: String, userPrompt: String): JsonObject = buildJsonObject {
        put("model", model)
        put("temperature", 0.1)
        putJsonArray("messages") {
            add(buildJsonObject { put("role", "system"); put("content", systemPrompt) })
            add(buildJsonObject { put("role", "user"); put("content", userPrompt) })
        }
    }

    override suspend fun search(systemPrompt: String, userPrompt: String): AiAnswer {
        val response = http.post("$baseUrl/chat/completions") {
            header("Authorization", "Bearer $apiKey")
            contentType(ContentType.Application.Json)
            setBody(requestBody(systemPrompt, userPrompt).toString())
        }
        val body = response.bodyAsText()
        if (!response.status.isSuccess()) throw AiException("Perplexity: " + errorMessage(response.status.value, body))
        return parseResponse(body)
    }

    companion object {
        fun parseResponse(body: String): AiAnswer {
            val root = json.parseToJsonElement(body).jsonObject
            val text = root["choices"]?.jsonArray?.firstOrNull()?.jsonObject
                ?.get("message")?.jsonObject?.str("content")
                ?: throw AiException("Perplexity: leere Antwort.")
            val results = (root["search_results"] as? JsonArray).orEmpty().mapNotNull { r ->
                val o = r.jsonObject
                val url = o.str("url") ?: return@mapNotNull null
                SourceLink(o.str("title") ?: url, url)
            }
            val citations = (root["citations"] as? JsonArray).orEmpty().mapNotNull {
                it.jsonPrimitive.contentOrNull?.let { url -> SourceLink(url, url) }
            }
            return AiAnswer(text, (results + citations).distinctBy { it.url })
        }
    }
}

