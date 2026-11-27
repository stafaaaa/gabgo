@file:OptIn(ExperimentalForeignApi::class)

package de.gabbas.gabgo.platform

import kotlinx.cinterop.ExperimentalForeignApi
import kotlinx.cinterop.UByteVar
import kotlinx.cinterop.alloc
import kotlinx.cinterop.convert
import kotlinx.cinterop.memScoped
import kotlinx.cinterop.ptr
import kotlinx.cinterop.reinterpret
import kotlinx.cinterop.refTo
import kotlinx.cinterop.value
import platform.zlib.Z_BEST_COMPRESSION
import platform.zlib.Z_BUF_ERROR
import platform.zlib.Z_OK
import platform.zlib.compress2
import platform.zlib.compressBound
import platform.zlib.uLongfVar
import platform.zlib.uncompress

/** zlib-format (RFC 1950) – byte-compatible with java.util.zip.Deflater/Inflater on Android & Desktop. */
internal object Deflate {
    fun compress(data: ByteArray): ByteArray = memScoped {
        val bound = compressBound(data.size.convert()).toInt()
        val out = ByteArray(bound)
        val len = alloc<uLongfVar>().apply { value = bound.convert() }
        val src = if (data.isEmpty()) ByteArray(1) else data
        val rc = compress2(out.refTo(0).getPointer(this).reinterpret<UByteVar>(), len.ptr,
            src.refTo(0).getPointer(this).reinterpret(), data.size.convert(), Z_BEST_COMPRESSION)
        require(rc == Z_OK) { "Komprimierung fehlgeschlagen ($rc)" }
        out.copyOf(len.value.toInt())
    }

    fun decompress(data: ByteArray): ByteArray {
        require(data.isNotEmpty()) { "Ungültige Daten" }
        var size = maxOf(1024, data.size * 8)
        while (size <= 1_048_576) {
            val result = memScoped {
                val out = ByteArray(size)
                val len = alloc<uLongfVar>().apply { value = size.convert() }
                val rc = uncompress(out.refTo(0).getPointer(this).reinterpret<UByteVar>(), len.ptr,
                    data.refTo(0).getPointer(this).reinterpret(), data.size.convert())
                when (rc) {
                    Z_OK -> out.copyOf(len.value.toInt())
                    Z_BUF_ERROR -> null
                    else -> throw IllegalArgumentException("Ungültige Daten ($rc)")
                }
            }
            if (result != null) return result
            size *= 2
        }
        throw IllegalArgumentException("Zu groß")
    }
}
