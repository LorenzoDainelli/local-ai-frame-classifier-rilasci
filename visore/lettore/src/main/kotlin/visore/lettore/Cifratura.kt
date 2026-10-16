package visore.lettore

import java.io.ByteArrayOutputStream
import java.io.File
import java.io.RandomAccessFile
import java.security.SecureRandom
import javax.crypto.Cipher
import javax.crypto.spec.GCMParameterSpec
import javax.crypto.spec.SecretKeySpec
import org.json.JSONException
import org.json.JSONObject

val FIRMA = "VISORE-FILE".toByteArray(Charsets.US_ASCII) + byteArrayOf(0)

const val VERSIONE = 1
const val VERSIONE_COL_POSTO = 2

const val BLOCCO = 1024 * 1024
const val SIGILLO = 16
const val PREFISSO = 8
const val CONTATORE = 4

const val COSTO = 65536
val COSTI_AMMESSI = setOf(32768, 65536, 131072, 262144)
const val BLOCCO_SCRYPT = 8
const val PARALLELO = 1
const val LUNGHEZZA_CHIAVE = 32

val PROVA = "officina-visore-prova".toByteArray(Charsets.UTF_8)

fun controllaIParametri(costo: Int, blocco: Int, parallelo: Int) {
    if (costo !in COSTI_AMMESSI || blocco != BLOCCO_SCRYPT || parallelo != PARALLELO) {
        throw ErroreVisore(
            "Questo pacchetto chiede di calcolare la password in un modo che il " +
                "programma non conosce: forse la sua carta d'identita' e' stata " +
                "modificata. Per sicurezza non lo apro: rifallo dal computer.",
            "parametri_sconosciuti")
    }
}

fun quantiBlocchi(dimensione: Long): Int =
    if (dimensione <= 0L) 1 else ((dimensione + BLOCCO - 1L) / BLOCCO).toInt()

class Chiave(byte: ByteArray) {

    private val segreto: SecretKeySpec

    init {
        if (byte.size != LUNGHEZZA_CHIAVE) {
            throw ErroreVisore("Chiave di lunghezza sbagliata.")
        }
        segreto = SecretKeySpec(byte, "AES")
    }

    companion object {

        fun dallaPassword(password: String, sale: ByteArray, costo: Int = COSTO,
                          blocco: Int = BLOCCO_SCRYPT,
                          parallelo: Int = PARALLELO): Chiave {
            controllaIParametri(costo, blocco, parallelo)
            if (password.length < 8) {
                throw ErroreVisore(
                    "La password deve essere lunga almeno otto caratteri. E' " +
                        "la stessa del forziere sul computer (regola 115).")
            }
            return Chiave(Scrypt.deriva(password.toByteArray(Charsets.UTF_8), sale,
                costo, blocco, parallelo, LUNGHEZZA_CHIAVE))
        }

        fun controllaLaPassword(password: String, sale: ByteArray, prova: String,
                                costo: Int = COSTO, blocco: Int = BLOCCO_SCRYPT,
                                parallelo: Int = PARALLELO): Chiave {
            val chiave = dallaPassword(password, sale, costo, blocco, parallelo)
            if (!chiave.apre(prova)) {
                throw PasswordSbagliata(
                    "La password non apre questo pacchetto. E' la stessa del " +
                        "forziere sul computer (regola 115): se li' e' cambiata " +
                        "dopo l'ultimo travaso, il pacchetto ha ancora quella " +
                        "vecchia, e si rifa'.")
            }
            return chiave
        }
    }

    fun apre(prova: String): Boolean = try {
        decifra(nonce(ByteArray(PREFISSO), 0), Esadecimale.byte(prova),
            accompagnamento(0, true, PROVA.size.toLong())).contentEquals(PROVA)
    } catch (guaio: Exception) {
        false
    }

    fun cifraByte(dati: ByteArray, posto: String): ByteArray {
        val prefisso = ByteArray(PREFISSO)
        SORTE.nextBytes(prefisso)

        val fuori = ByteArrayOutputStream(dati.size + 128)
        fuori.write(intestazione(prefisso, dati.size.toLong()))
        var numero = 0
        var inizio = 0
        while (true) {
            val fine = minOf(inizio + BLOCCO, dati.size)
            val ultimo = inizio + BLOCCO >= dati.size
            fuori.write(cifra(nonce(prefisso, numero),
                dati.copyOfRange(inizio, fine),
                accompagnamento(numero, ultimo, dati.size.toLong(), VERSIONE_COL_POSTO, posto)))
            if (ultimo) {
                break
            }
            inizio += BLOCCO
            numero += 1
        }
        return fuori.toByteArray()
    }

    private fun cifra(nonce: ByteArray, aperto: ByteArray,
                      accompagnamento: ByteArray): ByteArray {
        val cifratore = Cipher.getInstance("AES/GCM/NoPadding")
        cifratore.init(Cipher.ENCRYPT_MODE, segreto, GCMParameterSpec(SIGILLO * 8, nonce))
        cifratore.updateAAD(accompagnamento)
        return cifratore.doFinal(aperto)
    }

    fun scorri(sorgente: File, posto: String, tocca: (ByteArray) -> Unit) {
        RandomAccessFile(sorgente, "r").use { dentro ->
            val testa = leggiIntestazione(dentro)
            dentro.seek(testa.inizio.toLong())
            val quanti = quantiBlocchi(testa.dimensione)
            for (numero in 0 until quanti) {
                tocca(apriUnBlocco(prendi(dentro, BLOCCO + SIGILLO), testa,
                    numero, numero == quanti - 1, posto))
            }
        }
    }

    fun leggiTutto(sorgente: File, posto: String): ByteArray {
        val fuori = ByteArrayOutputStream()
        scorri(sorgente, posto) { fuori.write(it) }
        return fuori.toByteArray()
    }

    fun leggiPezzo(sorgente: File, da: Long, quanti: Int, posto: String): ByteArray {
        RandomAccessFile(sorgente, "r").use { dentro ->
            val testa = leggiIntestazione(dentro)
            val dimensione = testa.dimensione
            val primoByte = maxOf(0L, minOf(da, dimensione))
            val ultimoByte = maxOf(primoByte, minOf(primoByte + quanti, dimensione))
            if (ultimoByte == primoByte) {
                return ByteArray(0)
            }
            val totale = quantiBlocchi(dimensione)
            val primo = (primoByte / BLOCCO).toInt()
            val ultimoUtile = ((ultimoByte - 1L) / BLOCCO).toInt()
            dentro.seek(testa.inizio.toLong() + primo.toLong() * (BLOCCO + SIGILLO))
            val fuori = ByteArrayOutputStream()
            for (numero in primo..ultimoUtile) {
                fuori.write(apriUnBlocco(prendi(dentro, BLOCCO + SIGILLO), testa,
                    numero, numero == totale - 1, posto))
            }
            val aperto = fuori.toByteArray()
            val scarto = (primoByte - primo.toLong() * BLOCCO).toInt()
            return aperto.copyOfRange(scarto, scarto + (ultimoByte - primoByte).toInt())
        }
    }

    fun decifraFile(sorgente: File, destinazione: File, posto: String): String {
        val impronta = Blake2b.Impronta()
        destinazione.parentFile?.mkdirs()
        destinazione.outputStream().buffered().use { fuori ->
            scorri(sorgente, posto) { pezzo ->
                fuori.write(pezzo)
                impronta.aggiungi(pezzo)
            }
        }
        return Esadecimale.scritta(impronta.finisci())
    }

    fun dimensioneInChiaro(sorgente: File): Long =
        RandomAccessFile(sorgente, "r").use { leggiIntestazione(it).dimensione }

    private fun apriUnBlocco(chiuso: ByteArray, testa: Intestazione, numero: Int,
                             ultimo: Boolean, posto: String): ByteArray {
        if (chiuso.isEmpty()) {
            throw PacchettoRovinato(
                "Questo file del pacchetto finisce prima di quanto dichiara. " +
                    "E' stato copiato male, o la copia si e' interrotta. Si " +
                    "ricostruisce il pacchetto dal computer.")
        }
        try {
            return decifra(nonce(testa.prefisso, numero), chiuso,
                accompagnamento(numero, ultimo, testa.dimensione, testa.versione, posto))
        } catch (guaio: Exception) {
            throw PacchettoRovinato(
                "Questo file del pacchetto non si apre: o la password non e' " +
                    "quella con cui e' stato fatto, o il file e' rovinato. Se " +
                    "gli altri file si aprono, e' rovinato solo lui e basta " +
                    "ricopiarlo.")
        }
    }

    private fun decifra(nonce: ByteArray, chiuso: ByteArray,
                        accompagnamento: ByteArray): ByteArray {
        val cifratore = Cipher.getInstance("AES/GCM/NoPadding")
        cifratore.init(Cipher.DECRYPT_MODE, segreto, GCMParameterSpec(SIGILLO * 8, nonce))
        cifratore.updateAAD(accompagnamento)
        return cifratore.doFinal(chiuso)
    }
}

private val SORTE = SecureRandom()

class Intestazione(val prefisso: ByteArray, val dimensione: Long, val inizio: Int,
                   val versione: Int)

fun intestazione(prefisso: ByteArray, dimensione: Long): ByteArray {
    val testa = ("{\"blocco\": " + BLOCCO +
        ", \"cifra\": \"AES-256-GCM\"" +
        ", \"dimensione\": " + dimensione +
        ", \"prefisso\": \"" + Esadecimale.scritta(prefisso) + "\"" +
        ", \"versione\": " + VERSIONE_COL_POSTO + "}").toByteArray(Charsets.UTF_8)
    val fuori = ByteArrayOutputStream()
    fuori.write(FIRMA)
    fuori.write((testa.size ushr 8) and 0xff)
    fuori.write(testa.size and 0xff)
    fuori.write(testa)
    return fuori.toByteArray()
}

fun accompagnamento(numero: Int, ultimo: Boolean, dimensione: Long,
                    versione: Int = VERSIONE, posto: String = ""): ByteArray {
    val fuori = ByteArrayOutputStream()
    fuori.write("visore-$versione".toByteArray(Charsets.US_ASCII))
    fuori.write(0)
    if (versione >= VERSIONE_COL_POSTO) {
        val nome = posto.toByteArray(Charsets.UTF_8)
        fuori.write((nome.size ushr 8) and 0xff)
        fuori.write(nome.size and 0xff)
        fuori.write(nome)
    }
    fuori.write(byteArrayOf(
        (numero ushr 24).toByte(), (numero ushr 16).toByte(),
        (numero ushr 8).toByte(), numero.toByte(),
    ))
    fuori.write(if (ultimo) 1 else 0)
    for (spostamento in 56 downTo 0 step 8) {
        fuori.write(((dimensione ushr spostamento) and 0xffL).toInt())
    }
    return fuori.toByteArray()
}

fun nonce(prefisso: ByteArray, numero: Int): ByteArray {
    val fuori = ByteArray(PREFISSO + CONTATORE)
    prefisso.copyInto(fuori, 0, 0, minOf(PREFISSO, prefisso.size))
    fuori[PREFISSO] = (numero ushr 24).toByte()
    fuori[PREFISSO + 1] = (numero ushr 16).toByte()
    fuori[PREFISSO + 2] = (numero ushr 8).toByte()
    fuori[PREFISSO + 3] = numero.toByte()
    return fuori
}

private fun prendi(dentro: RandomAccessFile, quanti: Int): ByteArray {
    val stanza = ByteArray(quanti)
    var presi = 0
    while (presi < quanti) {
        val adesso = dentro.read(stanza, presi, quanti - presi)
        if (adesso <= 0) {
            break
        }
        presi += adesso
    }
    return if (presi == quanti) stanza else stanza.copyOf(presi)
}

private fun leggiIntestazione(dentro: RandomAccessFile): Intestazione {
    val firma = prendi(dentro, FIRMA.size)
    if (!firma.contentEquals(FIRMA)) {
        throw PacchettoRovinato("Questo file non fa parte di un pacchetto del Visore.")
    }
    val misura = prendi(dentro, 2)
    if (misura.size != 2) {
        throw PacchettoRovinato("Questo file del pacchetto e' tagliato.")
    }
    val quanto = ((misura[0].toInt() and 0xff) shl 8) or (misura[1].toInt() and 0xff)
    val grezza = prendi(dentro, quanto)
    if (grezza.size != quanto) {
        throw PacchettoRovinato("Questo file del pacchetto e' tagliato.")
    }
    val testa = try {
        JSONObject(String(grezza, Charsets.UTF_8))
    } catch (guaio: JSONException) {
        throw PacchettoRovinato("Questo file del pacchetto ha l'intestazione rovinata.")
    }
    val versione = testa.optInt("versione", -1)
    if (versione in 1 until VERSIONE_COL_POSTO) {
        throw PacchettoRovinato(
            "Questo file e' stato scritto da una versione precedente del programma, " +
                "che non lo legava al suo posto nel pacchetto. Il pacchetto va " +
                "rifatto dal computer.")
    }
    if (versione != VERSIONE_COL_POSTO) {
        throw ErroreVisore(
            "Questo pacchetto e' stato scritto da una versione piu' nuova del " +
                "programma (regola 372). Si rifa' il pacchetto dal computer.",
            "formato_troppo_nuovo")
    }
    if (testa.optInt("blocco", -1) != BLOCCO) {
        throw PacchettoRovinato("Questo file del pacchetto usa blocchi di un'altra misura.")
    }
    val prefisso = testa.optString("prefisso", "")
    val dimensione = testa.optLong("dimensione", -1L)
    if (dimensione < 0L || prefisso.length != PREFISSO * 2) {
        throw PacchettoRovinato("Questo file del pacchetto ha l'intestazione rovinata.")
    }
    return Intestazione(
        prefisso = Esadecimale.byte(prefisso),
        dimensione = dimensione,
        inizio = FIRMA.size + 2 + quanto,
        versione = versione,
    )
}
