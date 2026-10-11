package visore.lettore

import java.security.MessageDigest

object Scrypt {

    fun deriva(password: ByteArray, sale: ByteArray, n: Int, r: Int, p: Int,
               lunghezza: Int): ByteArray {
        require(n > 1 && (n and (n - 1)) == 0) {
            "Il costo di scrypt deve essere una potenza di due."
        }
        require(r >= 1 && p >= 1) { "I parametri di scrypt non hanno senso." }

        val parole = inParole(pbkdf2(password, sale, p * 128 * r))
        val quante = 32 * r
        for (blocco in 0 until p) {
            romix(parole, blocco * quante, r, n)
        }
        return pbkdf2(password, inByte(parole), lunghezza)
    }

    private fun romix(dati: IntArray, scarto: Int, r: Int, n: Int) {
        val quante = 32 * r
        val x = IntArray(quante)
        dati.copyInto(x, 0, scarto, scarto + quante)

        val tabella = IntArray(n * quante)
        for (i in 0 until n) {
            x.copyInto(tabella, i * quante, 0, quante)
            mescola(x, r)
        }
        for (i in 0 until n) {
            val quale = (x[(2 * r - 1) * 16] and (n - 1)) * quante
            for (k in 0 until quante) {
                x[k] = x[k] xor tabella[quale + k]
            }
            mescola(x, r)
        }
        x.copyInto(dati, scarto, 0, quante)
    }

    private fun mescola(dati: IntArray, r: Int) {
        val fuori = IntArray(32 * r)
        val pezzo = IntArray(16)
        dati.copyInto(pezzo, 0, (2 * r - 1) * 16, 2 * r * 16)
        for (i in 0 until 2 * r) {
            for (k in 0 until 16) {
                pezzo[k] = pezzo[k] xor dati[i * 16 + k]
            }
            salsa(pezzo)
            val dove = if (i % 2 == 0) i / 2 else r + i / 2
            pezzo.copyInto(fuori, dove * 16, 0, 16)
        }
        fuori.copyInto(dati, 0, 0, 32 * r)
    }

    private fun salsa(x: IntArray) {
        val entrato = x.copyOf()
        var giro = 0
        while (giro < 8) {
            x[4] = x[4] xor gira(x[0] + x[12], 7)
            x[8] = x[8] xor gira(x[4] + x[0], 9)
            x[12] = x[12] xor gira(x[8] + x[4], 13)
            x[0] = x[0] xor gira(x[12] + x[8], 18)
            x[9] = x[9] xor gira(x[5] + x[1], 7)
            x[13] = x[13] xor gira(x[9] + x[5], 9)
            x[1] = x[1] xor gira(x[13] + x[9], 13)
            x[5] = x[5] xor gira(x[1] + x[13], 18)
            x[14] = x[14] xor gira(x[10] + x[6], 7)
            x[2] = x[2] xor gira(x[14] + x[10], 9)
            x[6] = x[6] xor gira(x[2] + x[14], 13)
            x[10] = x[10] xor gira(x[6] + x[2], 18)
            x[3] = x[3] xor gira(x[15] + x[11], 7)
            x[7] = x[7] xor gira(x[3] + x[15], 9)
            x[11] = x[11] xor gira(x[7] + x[3], 13)
            x[15] = x[15] xor gira(x[11] + x[7], 18)
            x[1] = x[1] xor gira(x[0] + x[3], 7)
            x[2] = x[2] xor gira(x[1] + x[0], 9)
            x[3] = x[3] xor gira(x[2] + x[1], 13)
            x[0] = x[0] xor gira(x[3] + x[2], 18)
            x[6] = x[6] xor gira(x[5] + x[4], 7)
            x[7] = x[7] xor gira(x[6] + x[5], 9)
            x[4] = x[4] xor gira(x[7] + x[6], 13)
            x[5] = x[5] xor gira(x[4] + x[7], 18)
            x[11] = x[11] xor gira(x[10] + x[9], 7)
            x[8] = x[8] xor gira(x[11] + x[10], 9)
            x[9] = x[9] xor gira(x[8] + x[11], 13)
            x[10] = x[10] xor gira(x[9] + x[8], 18)
            x[12] = x[12] xor gira(x[15] + x[14], 7)
            x[13] = x[13] xor gira(x[12] + x[15], 9)
            x[14] = x[14] xor gira(x[13] + x[12], 13)
            x[15] = x[15] xor gira(x[14] + x[13], 18)
            giro += 2
        }
        for (i in 0 until 16) {
            x[i] = x[i] + entrato[i]
        }
    }

    private fun gira(valore: Int, quanto: Int): Int =
        (valore shl quanto) or (valore ushr (32 - quanto))

    private fun pbkdf2(password: ByteArray, sale: ByteArray, lunghezza: Int): ByteArray {
        val fuori = ByteArray(lunghezza)
        var scritti = 0
        var numero = 1
        while (scritti < lunghezza) {
            val messaggio = sale + byteArrayOf(
                (numero ushr 24).toByte(), (numero ushr 16).toByte(),
                (numero ushr 8).toByte(), numero.toByte(),
            )
            val pezzo = hmac(password, messaggio)
            val quanti = minOf(pezzo.size, lunghezza - scritti)
            pezzo.copyInto(fuori, scritti, 0, quanti)
            scritti += quanti
            numero += 1
        }
        return fuori
    }

    private fun hmac(chiave: ByteArray, messaggio: ByteArray): ByteArray {
        val sha = MessageDigest.getInstance("SHA-256")
        val quanto = 64
        val corta = if (chiave.size > quanto) sha.digest(chiave) else chiave
        val estesa = ByteArray(quanto)
        corta.copyInto(estesa)
        val dentro = ByteArray(quanto) { (estesa[it].toInt() xor 0x36).toByte() }
        val fuori = ByteArray(quanto) { (estesa[it].toInt() xor 0x5c).toByte() }

        sha.reset()
        sha.update(dentro)
        sha.update(messaggio)
        val mezzo = sha.digest()

        sha.reset()
        sha.update(fuori)
        sha.update(mezzo)
        return sha.digest()
    }

    private fun inParole(byte: ByteArray): IntArray {
        val parole = IntArray(byte.size / 4)
        for (i in parole.indices) {
            parole[i] = (byte[4 * i].toInt() and 0xff) or
                ((byte[4 * i + 1].toInt() and 0xff) shl 8) or
                ((byte[4 * i + 2].toInt() and 0xff) shl 16) or
                ((byte[4 * i + 3].toInt() and 0xff) shl 24)
        }
        return parole
    }

    private fun inByte(parole: IntArray): ByteArray {
        val byte = ByteArray(parole.size * 4)
        for (i in parole.indices) {
            byte[4 * i] = parole[i].toByte()
            byte[4 * i + 1] = (parole[i] ushr 8).toByte()
            byte[4 * i + 2] = (parole[i] ushr 16).toByte()
            byte[4 * i + 3] = (parole[i] ushr 24).toByte()
        }
        return byte
    }
}
