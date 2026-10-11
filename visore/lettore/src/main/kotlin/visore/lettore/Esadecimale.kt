package visore.lettore

object Esadecimale {

    private const val CIFRE = "0123456789abcdef"

    fun scritta(byte: ByteArray): String {
        val fuori = StringBuilder(byte.size * 2)
        for (b in byte) {
            val valore = b.toInt() and 0xff
            fuori.append(CIFRE[valore ushr 4])
            fuori.append(CIFRE[valore and 0x0f])
        }
        return fuori.toString()
    }

    fun byte(scritta: String): ByteArray {
        if (scritta.length % 2 != 0) {
            throw PacchettoRovinato(
                "Questo pacchetto ha un numero scritto a meta'. Va ricopiato " +
                    "dal computer.")
        }
        val fuori = ByteArray(scritta.length / 2)
        for (i in fuori.indices) {
            val alto = CIFRE.indexOf(scritta[2 * i].lowercaseChar())
            val basso = CIFRE.indexOf(scritta[2 * i + 1].lowercaseChar())
            if (alto < 0 || basso < 0) {
                throw PacchettoRovinato(
                    "Questo pacchetto ha un numero che non e' un numero. Va " +
                        "ricopiato dal computer.")
            }
            fuori[i] = ((alto shl 4) or basso).toByte()
        }
        return fuori
    }
}
