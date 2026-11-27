package de.gabbas.gabgo.license

import kotlin.io.encoding.Base64
import kotlin.io.encoding.ExperimentalEncodingApi
import kotlinx.datetime.LocalDate
import kotlinx.serialization.Serializable
import kotlinx.serialization.json.Json

@Serializable
data class LicensePayload(
    val v: Int = 1,
    val lid: String = "",
    val plan: String = "",
    val name: String = "",
    val email: String? = null,
    val iat: String = "",
    val exp: String? = null,
)

sealed interface LicenseResult {
    data class Valid(val payload: LicensePayload) : LicenseResult
    data class Invalid(val reason: String) : LicenseResult
}

@OptIn(ExperimentalEncodingApi::class)
class LicenseValidator(publicKeyBase64: String = GABGO_LICENSE_PUBLIC_KEY) {
    private val publicKey = Base64.Default.decode(publicKeyBase64)
    private val json = Json { ignoreUnknownKeys = true }
    private val urlSafe = Base64.UrlSafe.withPadding(Base64.PaddingOption.ABSENT_OPTIONAL)

    fun validate(licenseKey: String, today: LocalDate? = null): LicenseResult {
        val key = licenseKey.filterNot { it.isWhitespace() }
        if (!key.startsWith(PREFIX)) return LicenseResult.Invalid("Der Schlüssel muss mit $PREFIX beginnen.")
        val parts = key.removePrefix(PREFIX).split('.')
        if (parts.size != 2) return LicenseResult.Invalid("Ungültiges Schlüsselformat.")
        val body: ByteArray
        val signature: ByteArray
        try {
            body = urlSafe.decode(parts[0])
            signature = urlSafe.decode(parts[1])
        } catch (e: IllegalArgumentException) {
            return LicenseResult.Invalid("Schlüssel ist beschädigt.")
        }
        if (!Ed25519.verify(signature, body, publicKey)) {
            return LicenseResult.Invalid("Signatur ungültig – der Schlüssel wurde verändert oder ist nicht echt.")
        }
        val payload = try {
            json.decodeFromString(LicensePayload.serializer(), body.decodeToString())
        } catch (e: Exception) {
            return LicenseResult.Invalid("Lizenzdaten nicht lesbar.")
        }
        if (payload.plan != "pro") return LicenseResult.Invalid("Unbekannter Lizenztyp.")
        val exp = payload.exp
        if (exp != null && today != null) {
            val expDate = runCatching { LocalDate.parse(exp) }.getOrNull()
                ?: return LicenseResult.Invalid("Ablaufdatum ungültig.")
            if (today > expDate) return LicenseResult.Invalid("Lizenz ist am $exp abgelaufen.")
        }
        return LicenseResult.Valid(payload)
    }

    companion object {
        const val PREFIX = "GABGO1-"
    }
}

object Plan {
    const val FREE_DEMO_SEARCHES = 3
    const val FREE_MAX_GROUP_SIZE = 2
}
