package de.gabbas.gabgo.platform

import java.awt.Desktop
import java.io.ByteArrayOutputStream
import java.io.File
import java.net.URI
import java.security.MessageDigest
import java.util.Properties
import java.util.zip.Deflater
import java.util.zip.Inflater

private val osName = System.getProperty("os.name").orEmpty().lowercase()

actual val currentPlatform: PlatformKind = when {
    osName.contains("win") -> PlatformKind.WINDOWS
    osName.contains("mac") || osName.contains("darwin") -> PlatformKind.MACOS
    else -> PlatformKind.LINUX
}

internal fun appDataDir(): File {
    val home = System.getProperty("user.home")
    val dir = when (currentPlatform) {
        PlatformKind.WINDOWS -> File(System.getenv("APPDATA") ?: "$home\\AppData\\Roaming", "GabGo")
        PlatformKind.MACOS -> File(home, "Library/Application Support/GabGo")
        else -> File(System.getenv("XDG_CONFIG_HOME") ?: "$home/.config", "gabgo")
    }
    return dir.apply { mkdirs() }
}

private class PropertiesStore(private val file: File) : KeyValueStore {
    private val props = Properties().apply { if (file.exists()) file.reader(Charsets.UTF_8).use { load(it) } }

    override fun getString(key: String): String? = synchronized(props) { props.getProperty(key) }

    override fun putString(key: String, value: String?) = synchronized(props) {
        if (value == null) props.remove(key) else props.setProperty(key, value)
        val tmp = File(file.parentFile, file.name + ".tmp")
        tmp.writer(Charsets.UTF_8).use { props.store(it, "GabGo") }
        if (!tmp.renameTo(file)) { file.delete(); tmp.renameTo(file) }
        Unit
    }
}

actual fun createKeyValueStore(): KeyValueStore = PropertiesStore(File(appDataDir(), "settings.properties"))

private fun openExternally(target: String): Boolean {
    val cmd = when (currentPlatform) {
        PlatformKind.WINDOWS -> listOf("rundll32", "url.dll,FileProtocolHandler", target)
        PlatformKind.MACOS -> listOf("open", target)
        else -> listOf("xdg-open", target)
    }
    return runCatching { ProcessBuilder(cmd).start(); true }.getOrDefault(false)
}

actual object ExternalLauncher {
    actual fun openUrl(url: String): Boolean {
        val safe = url.replace("[", "%5B").replace("]", "%5D").replace(" ", "%20")
        val viaDesktop = runCatching {
            if (Desktop.isDesktopSupported() && Desktop.getDesktop().isSupported(Desktop.Action.BROWSE)) {
                Desktop.getDesktop().browse(URI(safe)); true
            } else false
        }.getOrDefault(false)
        return viaDesktop || openExternally(safe)
    }
}

private fun withoutStamp(ics: String) = ics.lineSequence().filterNot { it.startsWith("DTSTAMP:") }.joinToString("\n")

actual object CalendarExporter {
    actual fun exportIcs(fileName: String, icsContent: String): Boolean {
        val home = File(System.getProperty("user.home"))
        val downloads = File(home, "Downloads").takeIf { it.isDirectory } ?: File(appDataDir(), "export").apply { mkdirs() }
        val base = fileName.removeSuffix(".ics")
        val file = generateSequence(1) { it + 1 }
            .map { n -> File(downloads, if (n == 1) fileName else "$base-$n.ics") }
            .first { !it.exists() || withoutStamp(it.readText(Charsets.UTF_8)) == withoutStamp(icsContent) }
            .apply { writeText(icsContent, Charsets.UTF_8) }
        val opened = runCatching {
            if (Desktop.isDesktopSupported() && Desktop.getDesktop().isSupported(Desktop.Action.OPEN)) {
                Desktop.getDesktop().open(file); true
            } else false
        }.getOrDefault(false)
        return opened || openExternally(file.absolutePath)
    }
}

actual object QrScanner {
    actual val isSupported: Boolean = false
    actual fun scan(onResult: (String?) -> Unit) = onResult(null)
}

actual object Compression {
    actual fun deflate(data: ByteArray): ByteArray {
        val d = Deflater(Deflater.BEST_COMPRESSION).apply { setInput(data); finish() }
        val out = ByteArrayOutputStream(); val buf = ByteArray(1024)
        while (!d.finished()) out.write(buf, 0, d.deflate(buf))
        d.end(); return out.toByteArray()
    }

    actual fun inflate(data: ByteArray): ByteArray {
        val i = Inflater().apply { setInput(data) }
        val out = ByteArrayOutputStream(); val buf = ByteArray(1024)
        while (!i.finished()) {
            val n = i.inflate(buf)
            if (n == 0 && (i.needsInput() || i.needsDictionary())) throw IllegalArgumentException("Ungültige Daten")
            out.write(buf, 0, n)
            if (out.size() > 1_000_000) throw IllegalArgumentException("Zu groß")
        }
        i.end(); return out.toByteArray()
    }
}

actual object Crypto {
    actual fun sha512(data: ByteArray): ByteArray = MessageDigest.getInstance("SHA-512").digest(data)
}
