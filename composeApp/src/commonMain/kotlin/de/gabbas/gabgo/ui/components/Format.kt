package de.gabbas.gabgo.ui.components

import de.gabbas.gabgo.calendar.IcsGenerator
import kotlinx.datetime.LocalDate

private val weekdays = listOf("Mo.", "Di.", "Mi.", "Do.", "Fr.", "Sa.", "So.")

fun formatDate(d: LocalDate): String =
    "${weekdays[d.dayOfWeek.ordinal]} ${d.dayOfMonth.toString().padStart(2, '0')}.${d.monthNumber.toString().padStart(2, '0')}.${d.year}"

fun formatShortDate(d: LocalDate): String =
    "${d.dayOfMonth.toString().padStart(2, '0')}.${d.monthNumber.toString().padStart(2, '0')}."

fun formatWhen(start: String, end: String?): String {
    fun one(v: String): Pair<String, LocalDate?> = when (val w = IcsGenerator.parseDateTime(v)) {
        is IcsGenerator.When.Day -> formatDate(w.date) to w.date
        is IcsGenerator.When.Time -> {
            val t = w.dateTime
            "${formatDate(t.date)} · ${t.hour.toString().padStart(2, '0')}:${t.minute.toString().padStart(2, '0')} Uhr" to t.date
        }
        null -> v to null
    }
    val (s, sd) = one(start)
    if (end.isNullOrBlank()) return s
    return when (val w = IcsGenerator.parseDateTime(end)) {
        is IcsGenerator.When.Time -> if (w.dateTime.date == sd) {
            "$s – ${w.dateTime.hour.toString().padStart(2, '0')}:${w.dateTime.minute.toString().padStart(2, '0')} Uhr"
        } else "$s – ${one(end).first}"
        is IcsGenerator.When.Day -> if (w.date == sd) s else "$s – ${formatDate(w.date)}"
        null -> s
    }
}
