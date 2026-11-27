package de.gabbas.gabgo

import de.gabbas.gabgo.calendar.IcsGenerator
import de.gabbas.gabgo.model.EventSuggestion
import kotlinx.datetime.Instant
import kotlinx.datetime.LocalDate
import kotlinx.datetime.TimeZone
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFailsWith
import kotlin.test.assertIs
import kotlin.test.assertNull
import kotlin.test.assertTrue

class IcsGeneratorTest {
    private val berlin = TimeZone.of("Europe/Berlin")
    private val now = Instant.parse("2026-11-27T06:00:00Z")

    private fun event(start: String, end: String? = null) = EventSuggestion(
        title = "Weihnachtsmarkt am Römer; Glühwein, Musik",
        description = "Großer Markt\nmit Bühne",
        start = start, end = end,
        venue = "Römerberg", address = "Römerberg 1", city = "Frankfurt am Main",
        priceRange = "Eintritt frei",
        sourceUrl = "https://www.frankfurt.de/weihnachtsmarkt",
        ticketUrl = "https://tickets.example.com/roemer",
    )

    private fun unfold(ics: String) = ics.replace("\r\n ", "")

    @Test
    fun timedEventUsesUtcAndCrlf() {
        val ics = IcsGenerator.generate(event("2026-12-05T18:30", "2026-12-05T22:00"), berlin, now)
        assertTrue(ics.startsWith("BEGIN:VCALENDAR\r\nVERSION:2.0\r\n"))
        assertTrue(ics.endsWith("END:VEVENT\r\nEND:VCALENDAR\r\n"))
        assertTrue(ics.split("\n").dropLast(1).all { it.endsWith("\r") }, "every line must end with CRLF")
        val u = unfold(ics)
        assertTrue("DTSTART:20261205T173000Z" in u)
        assertTrue("DTEND:20261205T210000Z" in u)
        assertTrue("DTSTAMP:20261127T060000Z" in u)
        assertTrue("SUMMARY:Weihnachtsmarkt am Römer\\; Glühwein\\, Musik" in u)
        assertTrue("LOCATION:Römerberg\\, Römerberg 1\\, Frankfurt am Main" in u)
        assertTrue("URL:https://tickets.example.com/roemer" in u)
        assertTrue("Großer Markt\\nmit Bühne" in u)
    }

    @Test
    fun explicitOffsetWinsOverDeviceTimeZone() {
        val u = unfold(IcsGenerator.generate(event("2026-07-01T20:00+03:00", "2026-07-01T22:30:00+03:00"), berlin, now))
        assertTrue("DTSTART:20260701T170000Z" in u)
        assertTrue("DTEND:20260701T193000Z" in u)
    }

    @Test
    fun missingEndDefaultsToTwoHours() {
        val u = unfold(IcsGenerator.generate(event("2026-07-01 20:00"), berlin, now))
        assertTrue("DTSTART:20260701T180000Z" in u)
        assertTrue("DTEND:20260701T200000Z" in u)
    }

    @Test
    fun allDayEventsUseExclusiveEndDate() {
        val u = unfold(IcsGenerator.generate(event("2026-12-24", "2026-12-26"), berlin, now))
        assertTrue("DTSTART;VALUE=DATE:20261224" in u)
        assertTrue("DTEND;VALUE=DATE:20261227" in u)
    }

    @Test
    fun longLinesAreFoldedAt75Octets() {
        val ics = IcsGenerator.generate(event("2026-12-05T18:30"), berlin, now)
        ics.split("\r\n").forEach { assertTrue(it.encodeToByteArray().size <= 75, "too long: $it") }
    }

    @Test
    fun invalidStartThrows() {
        assertFailsWith<IllegalArgumentException> { IcsGenerator.generate(event("demnächst"), berlin, now) }
    }

    @Test
    fun parsesCommonDateFormats() {
        assertEquals(LocalDate(2026, 3, 1), assertIs<IcsGenerator.When.Day>(IcsGenerator.parseDateTime("2026-03-01")).date)
        assertIs<IcsGenerator.When.Time>(IcsGenerator.parseDateTime("2026-03-01T19:00:00+01:00"))
        assertIs<IcsGenerator.When.Time>(IcsGenerator.parseDateTime("2026-03-01T19:00Z"))
        assertNull(IcsGenerator.parseDateTime("März 2026"))
    }

    @Test
    fun fileNameIsSafe() {
        assertEquals("gabgo-weihnachtsmarkt-am-roemer-gluehwein-musi.ics", IcsGenerator.fileName(event("2026-12-05")))
    }
}
