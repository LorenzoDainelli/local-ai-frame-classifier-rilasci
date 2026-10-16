package visore.lettore

import java.io.File
import java.nio.file.AtomicMoveNotSupportedException
import java.nio.file.Files
import java.nio.file.StandardCopyOption
import java.time.Instant
import java.time.ZoneOffset
import java.time.format.DateTimeFormatter

class Ritorno private constructor(
    private val dove: File,
    private val chiave: Chiave,
    private val banco: BancoCheScrive,
) : AutoCloseable {

    var guaio: String? = null
        private set

    companion object {

        val SCHEMA = listOf(
            "CREATE TABLE IF NOT EXISTS informazioni (" +
                "chiave TEXT PRIMARY KEY, valore TEXT NOT NULL)",
            "CREATE TABLE IF NOT EXISTS cuori (" +
                "impronta TEXT PRIMARY KEY, messo_il TEXT)",
            "CREATE TABLE IF NOT EXISTS raccolte (" +
                "id INTEGER PRIMARY KEY, nome TEXT NOT NULL, creata_il TEXT)",
            "CREATE TABLE IF NOT EXISTS raccolte_scatti (" +
                "raccolta_id INTEGER NOT NULL, impronta TEXT NOT NULL, " +
                "PRIMARY KEY (raccolta_id, impronta))",
            "CREATE TABLE IF NOT EXISTS diario (" +
                "aperto_il TEXT PRIMARY KEY, durata_s INTEGER, " +
                "latitudine REAL, longitudine REAL, quante_foto INTEGER)",
        )

        fun apri(pacchetto: Pacchetto, apre: ApreIlBancoDaScrivere): Ritorno {
            val dove = dentro(pacchetto.cartella, RITORNO)
            var guaio: String? = null
            var daRifare = false

            val banco = if (dove.isFile) {
                try {
                    apre.apri(pacchetto.chiave.leggiTutto(dove, RITORNO))
                } catch (rovinato: ErroreVisore) {
                    mettiDaParte(dove)
                    guaio = "Quello che avevi messo da parte su questo telefono " +
                        "non si rilegge piu'. Riparto da quello che il computer " +
                        "sapeva all'ultimo travaso, e il file che non si legge " +
                        "l'ho spostato accanto senza cancellarlo. Le foto non " +
                        "c'entrano e ci sono tutte."
                    daRifare = true
                    apre.apri(null)
                }
            } else {
                daRifare = true
                apre.apri(null)
            }

            val ritorno = Ritorno(dove, pacchetto.chiave, banco)
            ritorno.guaio = guaio
            for (comando in SCHEMA) {
                banco.esegui(comando)
            }
            var cambiato = false
            if (daRifare) {
                cambiato = ritorno.riprendiDallaScorta(pacchetto.scorta())
            }
            if (ritorno.applicaITolti(pacchetto.scorta().tolti)) {
                cambiato = true
            }
            if (cambiato) {
                ritorno.salva()
            }
            return ritorno
        }

        private fun mettiDaParte(dove: File) {
            val via = File(dove.parentFile, dove.name + ".illeggibile-" + System.currentTimeMillis())
            try {
                Files.move(dove.toPath(), via.toPath())
            } catch (guaio: java.io.IOException) {
                throw ErroreVisore(
                    "Quello che avevi messo da parte su questo telefono non si " +
                        "rilegge, e non riesco nemmeno a spostarlo per non " +
                        "rovinarlo: il telefono e' pieno, oppure la cartella e' " +
                        "di sola lettura.", "ritorno_non_scritto")
            }
        }

        fun adesso(): String = DateTimeFormatter
            .ofPattern("yyyy-MM-dd'T'HH:mm:ss'Z'")
            .withZone(ZoneOffset.UTC)
            .format(Instant.now())
    }

    fun cuori(): List<Cuore> = banco.righe(
        "SELECT impronta, messo_il FROM cuori ORDER BY messo_il, impronta"
    ).map { Cuore(it.testo("impronta") ?: "", it.testo("messo_il") ?: "") }

    fun haIlCuore(impronta: String): Boolean =
        banco.unNumero("SELECT count(*) FROM cuori WHERE impronta = ?", impronta) > 0

    fun raccolte(): List<Raccolta> = banco.righe(
        "SELECT id, nome, creata_il FROM raccolte ORDER BY id"
    ).map { riga ->
        val numero = riga.numero("id") ?: 0L
        Raccolta(
            numero = numero,
            nome = riga.testo("nome") ?: "",
            creataIl = riga.testo("creata_il") ?: "",
            impronte = banco.righe(
                "SELECT impronta FROM raccolte_scatti WHERE raccolta_id = ? " +
                    "ORDER BY impronta", numero,
            ).map { it.testo("impronta") ?: "" },
        )
    }

    fun diario(): List<Apertura> = banco.righe(
        "SELECT aperto_il, durata_s, latitudine, longitudine, quante_foto " +
            "FROM diario ORDER BY aperto_il DESC"
    ).map {
        Apertura(
            apertoIl = it.testo("aperto_il") ?: "",
            durataS = it.numero("durata_s"),
            latitudine = it.reale("latitudine"),
            longitudine = it.reale("longitudine"),
            quanteFoto = it.numero("quante_foto"),
        )
    }

    fun metti(impronta: String, quando: String = adesso()) {
        banco.esegui(
            "INSERT INTO cuori (impronta, messo_il) VALUES (?, ?) " +
                "ON CONFLICT(impronta) DO NOTHING", impronta, quando)
        salva()
    }

    fun togli(impronta: String) {
        banco.esegui("DELETE FROM cuori WHERE impronta = ?", impronta)
        salva()
    }

    fun nuovaRaccolta(nome: String, quando: String = adesso()): Long {
        banco.esegui("INSERT INTO raccolte (nome, creata_il) VALUES (?, ?)",
            nome, quando)
        val numero = banco.ultimoNumero()
        salva()
        return numero
    }

    fun rinominaRaccolta(numero: Long, nome: String) {
        banco.esegui("UPDATE raccolte SET nome = ? WHERE id = ?", nome, numero)
        salva()
    }

    fun mettiNellaRaccolta(numero: Long, impronta: String) {
        banco.esegui(
            "INSERT INTO raccolte_scatti (raccolta_id, impronta) VALUES (?, ?) " +
                "ON CONFLICT(raccolta_id, impronta) DO NOTHING", numero, impronta)
        salva()
    }

    fun togliDallaRaccolta(numero: Long, impronta: String) {
        banco.esegui(
            "DELETE FROM raccolte_scatti WHERE raccolta_id = ? AND impronta = ?",
            numero, impronta)
        salva()
    }

    fun buttaRaccolta(numero: Long) {
        banco.esegui("DELETE FROM raccolte_scatti WHERE raccolta_id = ?", numero)
        banco.esegui("DELETE FROM raccolte WHERE id = ?", numero)
        salva()
    }

    fun apertura(apertoIl: String, durataS: Long?, latitudine: Double? = null,
                 longitudine: Double? = null, quanteFoto: Long? = null) {
        banco.esegui(
            "INSERT INTO diario (aperto_il, durata_s, latitudine, longitudine, " +
                "quante_foto) VALUES (?, ?, ?, ?, ?) " +
                "ON CONFLICT(aperto_il) DO NOTHING",
            apertoIl, durataS, latitudine, longitudine, quanteFoto)
        salva()
    }

    override fun close() {
        banco.close()
    }

    private fun salva() {
        banco.esegui(
            "INSERT INTO informazioni (chiave, valore) VALUES ('scritto_il', ?) " +
                "ON CONFLICT(chiave) DO UPDATE SET valore = excluded.valore",
            adesso())
        val chiuso = chiave.cifraByte(banco.byte(), RITORNO)
        val provvisorio = File(dove.parentFile, dove.name + ".parziale")
        try {
            dove.parentFile?.mkdirs()
            provvisorio.writeBytes(chiuso)
            try {
                Files.move(provvisorio.toPath(), dove.toPath(),
                    StandardCopyOption.REPLACE_EXISTING,
                    StandardCopyOption.ATOMIC_MOVE)
            } catch (senzaAtomico: AtomicMoveNotSupportedException) {
                Files.move(provvisorio.toPath(), dove.toPath(),
                    StandardCopyOption.REPLACE_EXISTING)
            }
        } catch (guaio: java.io.IOException) {
            provvisorio.delete()
            throw ErroreVisore(
                "Non riesco a scrivere sul pacchetto: il telefono e' pieno, " +
                    "oppure la cartella e' di sola lettura. Quello che avevi " +
                    "gia' messo da parte e' al sicuro.", "ritorno_non_scritto")
        }
    }

    private fun riprendiDallaScorta(scorta: Scorta): Boolean {
        if (scorta.cuori.isEmpty() && scorta.raccolte.isEmpty()) {
            return false
        }
        for (cuore in scorta.cuori) {
            banco.esegui(
                "INSERT INTO cuori (impronta, messo_il) VALUES (?, ?) " +
                    "ON CONFLICT(impronta) DO NOTHING",
                cuore.impronta, cuore.messoIl)
        }
        for (raccolta in scorta.raccolte) {
            banco.esegui(
                "INSERT INTO raccolte (id, nome, creata_il) VALUES (?, ?, ?) " +
                    "ON CONFLICT(id) DO NOTHING",
                raccolta.numero, raccolta.nome, raccolta.creataIl)
            for (impronta in raccolta.impronte) {
                banco.esegui(
                    "INSERT INTO raccolte_scatti (raccolta_id, impronta) " +
                        "VALUES (?, ?) ON CONFLICT(raccolta_id, impronta) DO NOTHING",
                    raccolta.numero, impronta)
            }
        }
        return true
    }

    private fun applicaITolti(tolti: List<Cuore>): Boolean {
        var cambiato = false
        for (cuore in tolti) {
            if (haIlCuore(cuore.impronta)) {
                banco.esegui("DELETE FROM cuori WHERE impronta = ?", cuore.impronta)
                cambiato = true
            }
        }
        return cambiato
    }
}

class Cuore(val impronta: String, val messoIl: String)

class Raccolta(val numero: Long, val nome: String, val creataIl: String,
               val impronte: List<String>)

class Apertura(val apertoIl: String, val durataS: Long?, val latitudine: Double?,
               val longitudine: Double?, val quanteFoto: Long?)

class Scorta(val cuori: List<Cuore>, val tolti: List<Cuore>,
             val raccolte: List<Raccolta>)
