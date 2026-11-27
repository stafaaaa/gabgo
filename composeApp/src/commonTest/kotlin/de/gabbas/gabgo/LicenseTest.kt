package de.gabbas.gabgo

import de.gabbas.gabgo.license.Ed25519
import de.gabbas.gabgo.license.LicenseResult
import de.gabbas.gabgo.license.LicenseValidator
import kotlinx.datetime.LocalDate
import kotlin.io.encoding.Base64
import kotlin.io.encoding.ExperimentalEncodingApi
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertIs
import kotlin.test.assertTrue

class LicenseTest {
    // Test keypair: private seed = bytes 0..31 (only used for tests, never for real licenses).
    private val testPublicKey = "A6EHv/POEL4dcN0Y50vAmWfk1jCbpQ1fHdyGZBJVMbg="
    private val validKey = "GABGO1-eyJ2IjoxLCJsaWQiOiJURVNULTAwMDEiLCJwbGFuIjoicHJvIiwibmFtZSI6IlRlc3QgVXNlciIsImVtYWlsIjoidGVzdEBnYWJnby5kZSIsImlhdCI6IjIwMjYtMDEtMDEifQ.LjLp1ZswTU0gvMYwJdaNNrehNkxW10_6MUFc_9qoQGZg8WSa1XFcvf0spPruBFSCwbxA3xyeHdLErIWe8ly2CA"
    private val expiredKey = "GABGO1-eyJ2IjoxLCJsaWQiOiJURVNULTAwMDIiLCJwbGFuIjoicHJvIiwibmFtZSI6IkFiZ2VsYXVmZW4iLCJpYXQiOiIyMDI1LTAxLTAxIiwiZXhwIjoiMjAyNS0xMi0zMSJ9.l8EJaCMLKomyWdQ4fvGT0_PTFIVMKT4eJnnumoXg7Atf6syuVoGZgxOkw9GjpjhrttHnQd39RgdAWoQZbsw8BQ"

    /** Signed with the real GabGo production key (generate_gabgo_license.py). */
    private val productionKey = "GABGO1-eyJ2IjoxLCJsaWQiOiIzMzJDQUYzMjk0MTciLCJwbGFuIjoicHJvIiwibmFtZSI6IkdhYkdvIFRlc3RlciIsImlhdCI6IjIwMjYtMTEtMjciLCJlbWFpbCI6Im1vc2dhYjY5QGdtYWlsLmNvbSJ9.j8BbjeqeBjXeKmh-W6P6Y2eDvelWeRBbaU9gNbueLQoCxtOGxy65iKCEvXtaVq9SkPDQOs2AA3wnIR8mcyYcBg"

    private val today = LocalDate(2026, 11, 27)
    private val validator = LicenseValidator(testPublicKey)

    private fun hex(s: String) = s.chunked(2).map { it.toInt(16).toByte() }.toByteArray()

    @Test
    fun ed25519MatchesReferenceSignatures() {
        val pk = hex("03a107bff3ce10be1d70dd18e74bc09967e4d6309ba50d5f1ddc8664125531b8")
        val vectors = listOf(
            ByteArray(0) to "9ca53579530654d5c3df77089ef45eda613e2fedf670e96bedac4639504e5845ef4b95d5793077233dd16817b2532e9c5525872a73a4ad74b759369a9e05c102",
            "GabGo".encodeToByteArray() to "1da88b1e30c3d8f3abb8a47775a772aea1a825e07988c0601c72a77617694a9a6246d37014649e3c4ef4a09959eebbb4a938dde358cffc0de0817577b0a79c0d",
            ByteArray(200) { it.toByte() } to "2e2dbd7439d8a00986fa2ff9aa0afd788e4426c57f5dc4936bb0ab21f7549a5054f3d4cadb93b1e5acaf7619baf02c3298704b83cf85230ea890955920a67609",
        )
        for ((msg, sig) in vectors) {
            assertTrue(Ed25519.verify(hex(sig), msg, pk))
            val flipped = hex(sig).also { it[10] = (it[10].toInt() xor 1).toByte() }
            assertFalse(Ed25519.verify(flipped, msg, pk))
            assertFalse(Ed25519.verify(hex(sig), msg + 1, pk))
        }
    }

    @Test
    fun validLicenseIsAccepted() {
        val r = assertIs<LicenseResult.Valid>(validator.validate(validKey, today))
        assertEquals("Test User", r.payload.name)
        assertEquals("TEST-0001", r.payload.lid)
        assertEquals("pro", r.payload.plan)
    }

    @Test
    fun whitespaceAndLineBreaksAreIgnored() {
        val spaced = validKey.chunked(20).joinToString("\n ")
        assertIs<LicenseResult.Valid>(validator.validate(spaced, today))
    }

    @Test
    @OptIn(ExperimentalEncodingApi::class)
    fun tamperedPayloadIsRejected() {
        val b64 = Base64.UrlSafe.withPadding(Base64.PaddingOption.ABSENT_OPTIONAL)
        val body = b64.decode(validKey.removePrefix("GABGO1-").substringBefore('.')).decodeToString()
        val sig = validKey.substringAfter('.')
        // Change the name / extend the expiry but keep the original signature.
        val forged = body.replace("Test User", "Hacker X")
        assertTrue(forged != body)
        val forgedBody = b64.encode(forged.encodeToByteArray())
        assertIs<LicenseResult.Invalid>(validator.validate("GABGO1-$forgedBody.$sig", today))
    }

    @Test
    fun tamperedSignatureIsRejected() {
        val last = validKey.last()
        val tampered = validKey.dropLast(1) + (if (last == 'A') 'B' else 'A')
        assertIs<LicenseResult.Invalid>(validator.validate(tampered, today))
    }

    @Test
    fun malformedKeysAreRejected() {
        listOf("", "GABGO1-", "GABGO2-abc.def", "GABGO1-nur-ein-teil", "GABGO1-!!!.???").forEach {
            assertIs<LicenseResult.Invalid>(validator.validate(it, today), it)
        }
    }

    @Test
    fun expiredLicenseIsRejected() {
        assertIs<LicenseResult.Invalid>(validator.validate(expiredKey, today))
        assertIs<LicenseResult.Valid>(validator.validate(expiredKey, LocalDate(2025, 6, 1)))
    }

    @Test
    fun productionKeyVerifiesWithEmbeddedPublicKey() {
        assertIs<LicenseResult.Valid>(LicenseValidator().validate(productionKey, today))
        // A license signed with another key must not unlock the real app.
        assertIs<LicenseResult.Invalid>(LicenseValidator().validate(validKey, today))
    }
}
