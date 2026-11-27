package de.gabbas.gabgo.platform

import android.app.Activity
import android.content.ActivityNotFoundException
import android.content.Context
import android.content.Intent
import android.net.Uri
import androidx.core.content.FileProvider
import java.io.ByteArrayOutputStream
import java.io.File
import java.lang.ref.WeakReference
import java.security.MessageDigest
import java.util.zip.Deflater
import java.util.zip.Inflater

object AndroidPlatform {
    lateinit var appContext: Context
        private set
    private var activity: WeakReference<Activity>? = null
    private var launchScan: (() -> Unit)? = null
    private var pendingScan: ((String?) -> Unit)? = null

    fun attach(activity: Activity, launchScan: () -> Unit) {
        appContext = activity.applicationContext
        this.activity = WeakReference(activity)
        this.launchScan = launchScan
    }

    fun detach(activity: Activity) {
        if (this.activity?.get() === activity) { this.activity = null; launchScan = null }
    }

    internal fun startScan(onResult: (String?) -> Unit) {
        val launcher = launchScan ?: return onResult(null)
        pendingScan = onResult
        launcher()
    }

    fun deliverScanResult(value: String?) {
        pendingScan?.invoke(value)
        pendingScan = null
    }

    internal fun startActivity(intent: Intent): Boolean {
        val ctx: Context = activity?.get() ?: appContext.also { intent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK) }
        return try { ctx.startActivity(intent); true } catch (e: ActivityNotFoundException) { false }
    }
}

actual val currentPlatform: PlatformKind = PlatformKind.ANDROID

private class SharedPrefsStore(context: Context) : KeyValueStore {
    private val prefs = context.getSharedPreferences("gabgo", Context.MODE_PRIVATE)
    override fun getString(key: String): String? = prefs.getString(key, null)
    override fun putString(key: String, value: String?) {
        prefs.edit().apply { if (value == null) remove(key) else putString(key, value) }.apply()
    }
}

actual fun createKeyValueStore(): KeyValueStore = SharedPrefsStore(AndroidPlatform.appContext)

actual object ExternalLauncher {
    actual fun openUrl(url: String): Boolean =
        AndroidPlatform.startActivity(Intent(Intent.ACTION_VIEW, Uri.parse(url)))
}

actual object CalendarExporter {
    actual fun exportIcs(fileName: String, icsContent: String): Boolean {
        val ctx = AndroidPlatform.appContext
        val dir = File(ctx.cacheDir, "ics").apply { mkdirs() }
        val file = File(dir, fileName).apply { writeText(icsContent) }
        val uri = FileProvider.getUriForFile(ctx, "${ctx.packageName}.fileprovider", file)
        val view = Intent(Intent.ACTION_VIEW).setDataAndType(uri, "text/calendar")
            .addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
        if (AndroidPlatform.startActivity(Intent.createChooser(view, "Zum Kalender hinzufügen"))) return true
        val send = Intent(Intent.ACTION_SEND).setType("text/calendar").putExtra(Intent.EXTRA_STREAM, uri)
            .addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
        return AndroidPlatform.startActivity(Intent.createChooser(send, "Termin teilen"))
    }
}

actual object QrScanner {
    actual val isSupported: Boolean = true
    actual fun scan(onResult: (String?) -> Unit) = AndroidPlatform.startScan(onResult)
}

actual object Compression {
    actual fun deflate(data: ByteArray): ByteArray = jvmDeflate(data)
    actual fun inflate(data: ByteArray): ByteArray = jvmInflate(data)
}

actual object Crypto {
    actual fun sha512(data: ByteArray): ByteArray = MessageDigest.getInstance("SHA-512").digest(data)
}

internal fun jvmDeflate(data: ByteArray): ByteArray {
    val d = Deflater(Deflater.BEST_COMPRESSION).apply { setInput(data); finish() }
    val out = ByteArrayOutputStream(); val buf = ByteArray(1024)
    while (!d.finished()) out.write(buf, 0, d.deflate(buf))
    d.end(); return out.toByteArray()
}

internal fun jvmInflate(data: ByteArray): ByteArray {
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
