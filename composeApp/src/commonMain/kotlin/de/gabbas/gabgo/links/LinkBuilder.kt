package de.gabbas.gabgo.links

import de.gabbas.gabgo.platform.PlatformKind
import io.ktor.http.encodeURLParameter

object LinkBuilder {
    /** Apple Karten on macOS/iOS, Google Maps on Windows/Android/Linux. */
    fun mapsUrl(address: String, platform: PlatformKind): String {
        val q = address.encodeURLParameter()
        return when (platform) {
            PlatformKind.MACOS -> "maps://?daddr=$q"
            PlatformKind.IOS -> "https://maps.apple.com/?daddr=$q"
            else -> "https://www.google.com/maps/dir/?api=1&destination=$q"
        }
    }

    fun uberUrl(address: String): String =
        "https://m.uber.com/ul/?action=setPickup&pickup=my_location&dropoff[formatted_address]=${address.encodeURLParameter()}"
}
