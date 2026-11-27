@file:OptIn(ExperimentalForeignApi::class, BetaInteropApi::class)

package de.gabbas.gabgo.platform

import kotlinx.cinterop.BetaInteropApi
import kotlinx.cinterop.ExperimentalForeignApi
import kotlinx.cinterop.addressOf
import kotlinx.cinterop.reinterpret
import kotlinx.cinterop.usePinned
import platform.CoreCrypto.CC_SHA512
import platform.CoreCrypto.CC_SHA512_DIGEST_LENGTH
import platform.Foundation.NSString
import platform.Foundation.NSTemporaryDirectory
import platform.Foundation.NSURL
import platform.Foundation.NSUTF8StringEncoding
import platform.Foundation.NSUserDefaults
import platform.Foundation.create
import platform.Foundation.writeToFile
import platform.UIKit.UIActivityViewController
import platform.UIKit.UIApplication
import platform.UIKit.UIViewController
import platform.UIKit.popoverPresentationController

actual val currentPlatform: PlatformKind = PlatformKind.IOS

private class UserDefaultsStore : KeyValueStore {
    private val defaults = NSUserDefaults.standardUserDefaults
    override fun getString(key: String): String? = defaults.stringForKey(key)
    override fun putString(key: String, value: String?) {
        if (value == null) defaults.removeObjectForKey(key) else defaults.setObject(value, key)
    }
}

actual fun createKeyValueStore(): KeyValueStore = UserDefaultsStore()

internal fun topViewController(): UIViewController? {
    var vc = UIApplication.sharedApplication.keyWindow?.rootViewController
    while (vc?.presentedViewController != null) vc = vc.presentedViewController
    return vc
}

actual object ExternalLauncher {
    actual fun openUrl(url: String): Boolean {
        val nsUrl = NSURL.URLWithString(url) ?: return false
        UIApplication.sharedApplication.openURL(nsUrl, emptyMap<Any?, Any>(), null)
        return true
    }
}

actual object CalendarExporter {
    actual fun exportIcs(fileName: String, icsContent: String): Boolean {
        val path = NSTemporaryDirectory() + fileName
        @Suppress("CAST_NEVER_SUCCEEDS")
        val ok = (icsContent as NSString).writeToFile(path, true, NSUTF8StringEncoding, null)
        if (!ok) return false
        val vc = topViewController() ?: return false
        val sheet = UIActivityViewController(listOf(NSURL.fileURLWithPath(path)), null)
        sheet.popoverPresentationController?.sourceView = vc.view
        vc.presentViewController(sheet, true, null)
        return true
    }
}

interface QrScanCallback {
    fun onResult(value: String?)
}

/** Implemented in Swift (AVFoundation), see iosApp/iosApp/QrScanner.swift. */
interface NativeQrScanner {
    fun scan(callback: QrScanCallback)
}

object IosQrBridge {
    var scanner: NativeQrScanner? = null
}

actual object QrScanner {
    actual val isSupported: Boolean get() = IosQrBridge.scanner != null
    actual fun scan(onResult: (String?) -> Unit) {
        val s = IosQrBridge.scanner ?: return onResult(null)
        s.scan(object : QrScanCallback {
            override fun onResult(value: String?) = onResult(value)
        })
    }
}

actual object Compression {
    actual fun deflate(data: ByteArray): ByteArray = Deflate.compress(data)
    actual fun inflate(data: ByteArray): ByteArray = Deflate.decompress(data)
}

actual object Crypto {
    actual fun sha512(data: ByteArray): ByteArray {
        val out = ByteArray(CC_SHA512_DIGEST_LENGTH)
        val input = if (data.isEmpty()) ByteArray(1) else data
        input.usePinned { inp ->
            out.usePinned { o -> CC_SHA512(inp.addressOf(0), data.size.toUInt(), o.addressOf(0).reinterpret()) }
        }
        return out
    }
}
