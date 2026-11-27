package de.gabbas.gabgo.calendar

import de.gabbas.gabgo.model.EventSuggestion
import kotlinx.datetime.Clock
import kotlinx.datetime.DatePeriod
import kotlinx.datetime.Instant
import kotlinx.datetime.LocalDate
import kotlinx.datetime.LocalDateTime
import kotlinx.datetime.TimeZone
import kotlinx.datetime.plus
import kotlinx.datetime.toInstant
import kotlinx.datetime.toLocalDateTime
import kotlin.time.Duration.Companion.hours

/** RFC 5545 compliant iCalendar export for a single event. */
object IcsGenerator {
    private const val CRLF = "\r\n"

    fun generate(
        event: EventSuggestion,
        timeZone: TimeZone = TimeZone.currentSystemDefault(),
        now: Instant = Clock.System.now(),
    ): String {
        val lines = mutableListOf(
            "BEGIN:VCALENDAR",
            "VERSION:2.0",
            "PRODID:-//Gabbas//GabGo//DE",
            "CALSCALE:GREGORIAN",
            "METHOD:PUBLISH",
            "BEGIN:VEVENT",
            "UID:${uid(event)}@gabgo.gabbas.de",
            "DTSTAMP:${formatUtc(now)}",
        )
        val start = parseDateTime(event.start)
        val end = event.end?.let { parseDateTime(it) }
        when (start) {
            is When.Day -> {
                val endDay = (end as? When.Day)?.date?.takeIf { it >= start.date } ?: start.date
                lines += "DTSTART;VALUE=DATE:${formatDate(start.date)}"
                lines += "DTEND;VALUE=DATE:${formatDate(endDay.plus(DatePeriod(days = 1)))}"
            }
            is When.Time -> {
                val startInstant = instantOf(event.start) ?: start.dateTime.toInstant(timeZone)
                val endInstant = when (end) {
                    is When.Time -> event.end?.let { instantOf(it) } ?: end.dateTime.toInstant(timeZone)
                    is When.Day -> LocalDateTime(end.date.year, end.date.month, end.date.dayOfMonth, 23, 59).toInstant(timeZone)
                    null -> startInstant + 2.hours
                }.let { if (it > startInstant) it else startInstant + 2.hours }
                lines += "DTSTART:${formatUtc(startInstant)}"
                lines += "DTEND:${formatUtc(endInstant)}"
            }
            null -> throw IllegalArgumentException("Ungültiges Startdatum: ${event.start}")
        }
        lines += "SUMMARY:${escape(event.title)}"
        val location = event.fullAddress
        if (location.isNotBlank()) lines += "LOCATION:${escape(location)}"
        val description = buildString {
            if (event.description.isNotBlank()) append(event.description.trim()).append("\n\n")
            if (event.priceRange.isNotBlank()) append("Preis: ").append(event.priceRange).append('\n')
            event.openingHours?.takeIf { it.isNotBlank() }?.let { append("Öffnungszeiten: ").append(it).append('\n') }
            append("Quelle: ").append(event.sourceUrl)
            event.ticketUrl?.takeIf { it.isNotBlank() && it != event.sourceUrl }?.let { append("\nTickets: ").append(it) }
        }
        lines += "DESCRIPTION:${escape(description)}"
        lines += "URL:${event.ticketUrl?.takeIf { it.isNotBlank() } ?: event.sourceUrl}"
        lines += "END:VEVENT"
        lines += "END:VCALENDAR"
        return lines.joinToString(CRLF) { fold(it) } + CRLF
    }

    fun fileName(event: EventSuggestion): String {
        val slug = event.title.lowercase()
            .replace("ä", "ae").replace("ö", "oe").replace("ü", "ue").replace("ß", "ss")
            .replace(Regex("[^a-z0-9]+"), "-").trim('-').take(40).ifEmpty { "event" }
        return "gabgo-$slug.ics"
    }

    sealed interface When {
        data class Day(val date: LocalDate) : When
        data class Time(val dateTime: LocalDateTime) : When
    }

    fun parseDateTime(value: String): When? {
        val v = value.trim().replace(' ', 'T').removeSuffix("Z")
        if (v.length == 10) return runCatching { When.Day(LocalDate.parse(v)) }.getOrNull()
        val m = Regex("""^(\d{4}-\d{2}-\d{2}T\d{2}:\d{2})(:\d{2})?(\.\d+)?([+-]\d{2}:?\d{2})?$""").matchEntire(v) ?: return null
        val normalized = m.groupValues[1] + m.groupValues[2].ifEmpty { ":00" }
        return runCatching { When.Time(LocalDateTime.parse(normalized)) }.getOrNull()
    }

    /** Exact instant when the value carries `Z` or a UTC offset, e.g. `2026-11-28T19:30+01:00`. */
    private fun instantOf(value: String): Instant? {
        val v = value.trim().replace(' ', 'T')
        val withSeconds = if (v.length > 16 && v[16] != ':') v.substring(0, 16) + ":00" + v.substring(16) else v
        return runCatching { Instant.parse(withSeconds) }.getOrNull()
    }

    internal fun escape(text: String): String = text
        .replace("\\", "\\\\")
        .replace(";", "\\;")
        .replace(",", "\\,")
        .replace("\r\n", "\\n")
        .replace("\n", "\\n")

    /** Folds content lines longer than 75 octets (RFC 5545 §3.1). */
    internal fun fold(line: String): String {
        val bytes = line.encodeToByteArray()
        if (bytes.size <= 75) return line
        val sb = StringBuilder()
        var lineBytes = 0
        var limit = 75
        for (ch in line) {
            val size = ch.toString().encodeToByteArray().size
            if (lineBytes + size > limit) {
                sb.append(CRLF).append(' ')
                lineBytes = 1
                limit = 75
            }
            sb.append(ch)
            lineBytes += size
        }
        return sb.toString()
    }

    private fun formatDate(d: LocalDate) =
        "${d.year.toString().padStart(4, '0')}${d.monthNumber.pad()}${d.dayOfMonth.pad()}"

    private fun formatUtc(instant: Instant): String {
        val t = instant.toLocalDateTime(TimeZone.UTC)
        return "${formatDate(t.date)}T${t.hour.pad()}${t.minute.pad()}${t.second.pad()}Z"
    }

    private fun Int.pad() = toString().padStart(2, '0')

    private fun uid(event: EventSuggestion): String {
        var h = 1125899906842597L
        for (c in event.id) h = 31 * h + c.code
        return h.toULong().toString(16)
    }
}
