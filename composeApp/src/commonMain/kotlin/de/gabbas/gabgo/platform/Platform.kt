package de.gabbas.gabgo.platform

enum class PlatformKind { ANDROID, IOS, WINDOWS, MACOS, LINUX }

val PlatformKind.isApple: Boolean get() = this == PlatformKind.IOS || this == PlatformKind.MACOS

/** Persistent key/value storage (settings, API keys, favorites, tags, license state). */
interface KeyValueStore {
    fun getString(key: String): String?
    fun putString(key: String, value: String?)
}

expect val currentPlatform: PlatformKind

expect fun createKeyValueStore(): KeyValueStore

/** Opens ticket links, map routes and Uber deep links in the system handler. */
expect object ExternalLauncher {
    fun openUrl(url: String): Boolean
}

/** Writes an `.ics` file and hands it to the system calendar / share sheet. */
expect object CalendarExporter {
    fun exportIcs(fileName: String, icsContent: String): Boolean
}

/** Camera based QR scanning (Android/iOS). Desktop falls back to pasting the vibe code. */
expect object QrScanner {
    val isSupported: Boolean
    fun scan(onResult: (String?) -> Unit)
}

expect object Compression {
    fun deflate(data: ByteArray): ByteArray
    fun inflate(data: ByteArray): ByteArray
}

expect object Crypto {
    fun sha512(data: ByteArray): ByteArray
}
