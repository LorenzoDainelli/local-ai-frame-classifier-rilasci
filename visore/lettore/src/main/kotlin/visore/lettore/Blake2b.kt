package visore.lettore

object Blake2b {

    fun di(dati: ByteArray, lunghezza: Int = 32): ByteArray {
        val calcolo = Impronta(lunghezza)
        calcolo.aggiungi(dati)
        return calcolo.finisci()
    }

    fun scritta(dati: ByteArray, lunghezza: Int = 32): String =
        inEsadecimale(di(dati, lunghezza))

    fun inEsadecimale(byte: ByteArray): String = Esadecimale.scritta(byte)

    class Impronta(private val lunghezza: Int = 32) {

        private val stato = IV.copyOf()
        private val pezzo = ByteArray(128)
        private var quanti = 0
        private var contati = 0L
        private var finita = false

        init {
            require(lunghezza in 1..64) { "Un'impronta BLAKE2b va da 1 a 64 byte." }
            stato[0] = stato[0] xor 0x01010000L xor lunghezza.toLong()
        }

        fun aggiungi(dati: ByteArray, da: Int = 0, fino: Int = dati.size) {
            var i = da
            while (i < fino) {
                if (quanti == 128) {
                    contati += 128
                    comprimi(false)
                    quanti = 0
                }
                val quanto = minOf(128 - quanti, fino - i)
                dati.copyInto(pezzo, quanti, i, i + quanto)
                quanti += quanto
                i += quanto
            }
        }

        fun finisci(): ByteArray {
            check(!finita) { "Questa impronta e' gia' stata chiusa." }
            finita = true
            contati += quanti.toLong()
            java.util.Arrays.fill(pezzo, quanti, 128, 0)
            comprimi(true)
            val fuori = ByteArray(lunghezza)
            for (i in 0 until lunghezza) {
                fuori[i] = (stato[i / 8] ushr (8 * (i % 8))).toByte()
            }
            return fuori
        }

        fun scritta(): String = inEsadecimale(finisci())

        private fun comprimi(ultimo: Boolean) {
            val m = LongArray(16)
            for (i in 0 until 16) {
                var valore = 0L
                for (b in 7 downTo 0) {
                    valore = (valore shl 8) or (pezzo[i * 8 + b].toLong() and 0xff)
                }
                m[i] = valore
            }

            val v = LongArray(16)
            stato.copyInto(v, 0, 0, 8)
            IV.copyInto(v, 8, 0, 8)
            v[12] = v[12] xor contati
            if (ultimo) {
                v[14] = v[14].inv()
            }

            for (giro in 0 until 12) {
                val s = SIGMA[giro]
                gira(v, 0, 4, 8, 12, m[s[0]], m[s[1]])
                gira(v, 1, 5, 9, 13, m[s[2]], m[s[3]])
                gira(v, 2, 6, 10, 14, m[s[4]], m[s[5]])
                gira(v, 3, 7, 11, 15, m[s[6]], m[s[7]])
                gira(v, 0, 5, 10, 15, m[s[8]], m[s[9]])
                gira(v, 1, 6, 11, 12, m[s[10]], m[s[11]])
                gira(v, 2, 7, 8, 13, m[s[12]], m[s[13]])
                gira(v, 3, 4, 9, 14, m[s[14]], m[s[15]])
            }
            for (i in 0 until 8) {
                stato[i] = stato[i] xor v[i] xor v[i + 8]
            }
        }
    }

    private fun gira(v: LongArray, a: Int, b: Int, c: Int, d: Int,
                     x: Long, y: Long) {
        v[a] = v[a] + v[b] + x
        v[d] = ruota(v[d] xor v[a], 32)
        v[c] = v[c] + v[d]
        v[b] = ruota(v[b] xor v[c], 24)
        v[a] = v[a] + v[b] + y
        v[d] = ruota(v[d] xor v[a], 16)
        v[c] = v[c] + v[d]
        v[b] = ruota(v[b] xor v[c], 63)
    }

    private fun ruota(valore: Long, quanto: Int): Long =
        (valore ushr quanto) or (valore shl (64 - quanto))

    private val IV = longArrayOf(
        0x6a09e667f3bcc908uL.toLong(), 0xbb67ae8584caa73buL.toLong(),
        0x3c6ef372fe94f82buL.toLong(), 0xa54ff53a5f1d36f1uL.toLong(),
        0x510e527fade682d1uL.toLong(), 0x9b05688c2b3e6c1fuL.toLong(),
        0x1f83d9abfb41bd6buL.toLong(), 0x5be0cd19137e2179uL.toLong(),
    )

    private val SIGMA = arrayOf(
        intArrayOf(0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15),
        intArrayOf(14, 10, 4, 8, 9, 15, 13, 6, 1, 12, 0, 2, 11, 7, 5, 3),
        intArrayOf(11, 8, 12, 0, 5, 2, 15, 13, 10, 14, 3, 6, 7, 1, 9, 4),
        intArrayOf(7, 9, 3, 1, 13, 12, 11, 14, 2, 6, 5, 10, 4, 0, 15, 8),
        intArrayOf(9, 0, 5, 7, 2, 4, 10, 15, 14, 1, 11, 12, 6, 8, 3, 13),
        intArrayOf(2, 12, 6, 10, 0, 11, 8, 3, 4, 13, 7, 5, 15, 14, 1, 9),
        intArrayOf(12, 5, 1, 15, 14, 13, 4, 10, 0, 7, 6, 3, 9, 2, 8, 11),
        intArrayOf(13, 11, 7, 14, 12, 1, 3, 9, 5, 0, 15, 4, 8, 6, 2, 10),
        intArrayOf(6, 15, 14, 9, 11, 3, 0, 8, 12, 2, 13, 7, 1, 4, 10, 5),
        intArrayOf(10, 2, 8, 4, 7, 6, 1, 5, 15, 11, 9, 14, 3, 12, 13, 0),
        intArrayOf(0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15),
        intArrayOf(14, 10, 4, 8, 9, 15, 13, 6, 1, 12, 0, 2, 11, 7, 5, 3),
    )
}
