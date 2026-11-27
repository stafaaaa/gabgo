package de.gabbas.gabgo.license

import de.gabbas.gabgo.platform.Crypto

/**
 * Pure Kotlin Ed25519 signature verification (RFC 8032), ported from TweetNaCl.
 * Only verification is needed in the app – signing happens externally with the private key.
 */
object Ed25519 {
    private fun gf(vararg init: Long): LongArray = LongArray(16).also { init.copyInto(it) }

    private val gf0 = gf()
    private val gf1 = gf(1)

    private val L = longArrayOf(
        0xed, 0xd3, 0xf5, 0x5c, 0x1a, 0x63, 0x12, 0x58, 0xd6, 0x9c, 0xf7, 0xa2, 0xde, 0xf9, 0xde, 0x14,
        0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0x10,
    )

    // Curve constants derived at start-up instead of hard-coding limbs.
    private val D: LongArray
    private val D2: LongArray
    private val SQRT_M1: LongArray
    private val BX: LongArray
    private val BY: LongArray

    init {
        // d = -121665 / 121666
        val num = gf(0xDB41, 1)
        val den = gf(0xDB42, 1)
        val inv = gf(); inv25519(inv, den)
        val d = gf(); mul(d, num, inv); sub(d, gf0, d)
        D = d
        D2 = gf().also { add(it, d, d) }
        // sqrt(-1) = 2^((p-1)/4)
        SQRT_M1 = powSqrtM1()
        // Base point: y = 4/5, x recovered with even sign.
        val four = gf(4)
        val five = gf(5)
        val inv5 = gf(); inv25519(inv5, five)
        BY = gf().also { mul(it, four, inv5) }
        val yBytes = ByteArray(32); pack25519(yBytes, BY)
        val neg = arrayOf(gf(), gf(), gf(), gf())
        check(unpackneg(neg, yBytes) == 0)
        // unpackneg returns -B; B.x = -(neg.x)
        BX = gf().also { sub(it, gf0, neg[0]) }
    }

    private fun powSqrtM1(): LongArray {
        // (p-1)/4 = 2^253 - 5 ; computes 2^(2^253 - 5)
        // exponent bits: 2^253 - 5 = 0b1...1011 (253 bits: ones except bit 2)
        val base = gf(2)
        val r = gf(1)
        for (bit in 252 downTo 0) {
            sqr(r, r)
            if (bit != 2) mul(r, r, base)
        }
        return r
    }

    private fun set(r: LongArray, a: LongArray) = a.copyInto(r)

    private fun car25519(o: LongArray) {
        for (i in 0 until 16) {
            o[i] += 1L shl 16
            val c = o[i] shr 16
            if (i < 15) o[i + 1] += c - 1 else o[0] += 38 * (c - 1)
            o[i] -= c shl 16
        }
    }

    private fun sel25519(p: LongArray, q: LongArray, b: Int) {
        val c = (b - 1).toLong().inv()
        for (i in 0 until 16) {
            val t = c and (p[i] xor q[i])
            p[i] = p[i] xor t
            q[i] = q[i] xor t
        }
    }

    private fun pack25519(o: ByteArray, n: LongArray) {
        val m = gf()
        val t = n.copyOf()
        car25519(t); car25519(t); car25519(t)
        repeat(2) {
            m[0] = t[0] - 0xffed
            for (i in 1 until 15) {
                m[i] = t[i] - 0xffff - ((m[i - 1] shr 16) and 1)
                m[i - 1] = m[i - 1] and 0xffff
            }
            m[15] = t[15] - 0x7fff - ((m[14] shr 16) and 1)
            val b = ((m[15] shr 16) and 1).toInt()
            m[14] = m[14] and 0xffff
            sel25519(t, m, 1 - b)
        }
        for (i in 0 until 16) {
            o[2 * i] = (t[i] and 0xff).toByte()
            o[2 * i + 1] = (t[i] shr 8).toByte()
        }
    }

    private fun neq25519(a: LongArray, b: LongArray): Boolean {
        val c = ByteArray(32); val d = ByteArray(32)
        pack25519(c, a); pack25519(d, b)
        return !c.contentEquals(d)
    }

    private fun par25519(a: LongArray): Int {
        val d = ByteArray(32); pack25519(d, a)
        return d[0].toInt() and 1
    }

    private fun unpack25519(o: LongArray, n: ByteArray) {
        for (i in 0 until 16) o[i] = (n[2 * i].toLong() and 0xff) + ((n[2 * i + 1].toLong() and 0xff) shl 8)
        o[15] = o[15] and 0x7fff
    }

    private fun add(o: LongArray, a: LongArray, b: LongArray) { for (i in 0 until 16) o[i] = a[i] + b[i] }
    private fun sub(o: LongArray, a: LongArray, b: LongArray) { for (i in 0 until 16) o[i] = a[i] - b[i] }

    private fun mul(o: LongArray, a: LongArray, b: LongArray) {
        val t = LongArray(31)
        for (i in 0 until 16) for (j in 0 until 16) t[i + j] += a[i] * b[j]
        for (i in 0 until 15) t[i] += 38 * t[i + 16]
        for (i in 0 until 16) o[i] = t[i]
        car25519(o); car25519(o)
    }

    private fun sqr(o: LongArray, a: LongArray) = mul(o, a, a)

    private fun inv25519(o: LongArray, i: LongArray) {
        val c = i.copyOf()
        for (a in 253 downTo 0) {
            sqr(c, c)
            if (a != 2 && a != 4) mul(c, c, i)
        }
        set(o, c)
    }

    private fun pow2523(o: LongArray, i: LongArray) {
        val c = i.copyOf()
        for (a in 250 downTo 0) {
            sqr(c, c)
            if (a != 1) mul(c, c, i)
        }
        set(o, c)
    }

    private fun pointAdd(p: Array<LongArray>, q: Array<LongArray>) {
        val a = gf(); val b = gf(); val c = gf(); val d = gf(); val t = gf()
        val e = gf(); val f = gf(); val g = gf(); val h = gf()
        sub(a, p[1], p[0]); sub(t, q[1], q[0]); mul(a, a, t)
        add(b, p[0], p[1]); add(t, q[0], q[1]); mul(b, b, t)
        mul(c, p[3], q[3]); mul(c, c, D2)
        mul(d, p[2], q[2]); add(d, d, d)
        sub(e, b, a); sub(f, d, c); add(g, d, c); add(h, b, a)
        mul(p[0], e, f); mul(p[1], h, g); mul(p[2], g, f); mul(p[3], e, h)
    }

    private fun cswap(p: Array<LongArray>, q: Array<LongArray>, b: Int) {
        for (i in 0 until 4) sel25519(p[i], q[i], b)
    }

    private fun pack(r: ByteArray, p: Array<LongArray>) {
        val tx = gf(); val ty = gf(); val zi = gf()
        inv25519(zi, p[2])
        mul(tx, p[0], zi); mul(ty, p[1], zi)
        pack25519(r, ty)
        r[31] = (r[31].toInt() xor (par25519(tx) shl 7)).toByte()
    }

    private fun scalarmult(p: Array<LongArray>, q: Array<LongArray>, s: ByteArray) {
        set(p[0], gf0); set(p[1], gf1); set(p[2], gf1); set(p[3], gf0)
        for (i in 255 downTo 0) {
            val b = (s[i / 8].toInt() shr (i and 7)) and 1
            cswap(p, q, b)
            pointAdd(q, p)
            pointAdd(p, p)
            cswap(p, q, b)
        }
    }

    private fun scalarbase(p: Array<LongArray>, s: ByteArray) {
        val q = arrayOf(BX.copyOf(), BY.copyOf(), gf1.copyOf(), gf())
        mul(q[3], BX, BY)
        scalarmult(p, q, s)
    }

    private fun unpackneg(r: Array<LongArray>, p: ByteArray): Int {
        val t = gf(); val chk = gf(); val num = gf(); val den = gf()
        val den2 = gf(); val den4 = gf(); val den6 = gf()
        set(r[2], gf1)
        unpack25519(r[1], p)
        sqr(num, r[1]); mul(den, num, D); sub(num, num, r[2]); add(den, r[2], den)
        sqr(den2, den); sqr(den4, den2); mul(den6, den4, den2); mul(t, den6, num); mul(t, t, den)
        pow2523(t, t); mul(t, t, num); mul(t, t, den); mul(t, t, den); mul(r[0], t, den)
        sqr(chk, r[0]); mul(chk, chk, den)
        if (neq25519(chk, num)) mul(r[0], r[0], sqrtM1OrInit())
        sqr(chk, r[0]); mul(chk, chk, den)
        if (neq25519(chk, num)) return -1
        if (par25519(r[0]) == ((p[31].toInt() and 0xff) shr 7)) sub(r[0], gf0, r[0])
        mul(r[3], r[0], r[1])
        return 0
    }

    // SQRT_M1 is needed while the base point is derived inside init; it is assigned before that.
    private fun sqrtM1OrInit(): LongArray = SQRT_M1

    private fun modL(r: ByteArray, x: LongArray) {
        var carry: Long
        for (i in 63 downTo 32) {
            carry = 0
            var j = i - 32
            while (j < i - 12) {
                x[j] += carry - 16 * x[i] * L[j - (i - 32)]
                carry = (x[j] + 128) shr 8
                x[j] -= carry shl 8
                j++
            }
            x[j] += carry
            x[i] = 0
        }
        carry = 0
        for (j in 0 until 32) {
            x[j] += carry - (x[31] shr 4) * L[j]
            carry = x[j] shr 8
            x[j] = x[j] and 255
        }
        for (j in 0 until 32) x[j] -= carry * L[j]
        for (i in 0 until 32) {
            x[i + 1] += x[i] shr 8
            r[i] = (x[i] and 255).toByte()
        }
    }

    private fun reduce(h: ByteArray): ByteArray {
        val x = LongArray(64) { h[it].toLong() and 0xff }
        val r = ByteArray(32)
        modL(r, x)
        return r
    }

    /** True if S < L (rejects malleable signatures). */
    private fun scalarIsCanonical(s: ByteArray): Boolean {
        for (i in 31 downTo 0) {
            val a = s[i].toInt() and 0xff
            val b = L[i].toInt()
            if (a < b) return true
            if (a > b) return false
        }
        return false
    }

    fun verify(signature: ByteArray, message: ByteArray, publicKey: ByteArray): Boolean {
        if (signature.size != 64 || publicKey.size != 32) return false
        val sBytes = signature.copyOfRange(32, 64)
        if (!scalarIsCanonical(sBytes)) return false
        val q = arrayOf(gf(), gf(), gf(), gf())
        if (unpackneg(q, publicKey) != 0) return false
        val h = reduce(Crypto.sha512(signature.copyOfRange(0, 32) + publicKey + message))
        val p = arrayOf(gf(), gf(), gf(), gf())
        scalarmult(p, q, h)
        val sb = arrayOf(gf(), gf(), gf(), gf())
        scalarbase(sb, sBytes)
        pointAdd(p, sb)
        val t = ByteArray(32)
        pack(t, p)
        return t.contentEquals(signature.copyOfRange(0, 32))
    }
}
