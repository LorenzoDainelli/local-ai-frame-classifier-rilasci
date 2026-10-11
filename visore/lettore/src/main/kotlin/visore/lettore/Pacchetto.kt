package visore.lettore

import java.io.File

class Pacchetto(
    val cartella: File,
    val carta: Carta,
    val chiave: Chiave,
    val dentro: Banco,
) : AutoCloseable {

    companion object {

        fun apri(cartella: File, password: String, apre: ApreIlBanco): Pacchetto {
            val carta = Carta.leggi(cartella)
            carta.controllaIlFormato()
            val chiave = carta.chiave(password)

            val dove = dentro(cartella, DATI)
            if (!dove.isFile) {
                throw ErroreVisore(
                    "Questo pacchetto non ha il suo database: e' rimasto a meta'. " +
                        "Va ricopiato dal computer.", "pacchetto_senza_dati")
            }
            return Pacchetto(cartella, carta, chiave, apre.apri(chiave.leggiTutto(dove)))
        }
    }

    override fun close() {
        dentro.close()
    }

    val completo: Boolean
        get() = carta.completa

    fun informazioni(): Map<String, String> {
        val detto = mutableMapOf<String, String>()
        for (riga in dentro.righe("SELECT chiave, valore FROM informazioni")) {
            detto[riga.testo("chiave") ?: ""] = riga.testo("valore") ?: ""
        }
        detto["telefono"] = carta.telefono
        detto["stato"] = carta.stato
        detto["versione_formato"] = carta.versioneFormato.toString()
        return detto
    }

    fun quanti(): Int = dentro.unNumero("SELECT count(*) FROM scatti").toInt()

    fun giorni(): List<Giorno> = dentro.righe(
        "SELECT s.giorno, count(*) AS quanti, " +
            "       group_concat(DISTINCT l.nome) AS luoghi " +
            "FROM scatti s LEFT JOIN luoghi l ON l.id = s.luogo_id " +
            "GROUP BY s.giorno " +
            "ORDER BY s.giorno IS NULL, s.giorno DESC",
    ).map { riga ->
        val luoghi = riga.testo("luoghi")
        Giorno(
            giorno = riga.testo("giorno"),
            quanti = riga.intero("quanti") ?: 0,
            luoghi = if (luoghi.isNullOrEmpty()) emptyList() else luoghi.split(","),
        )
    }

    fun scatti(quanti: Int = 100, da: Int = 0): List<Riga> = dentro.righe(
        "SELECT * FROM scatti " +
            "ORDER BY giorno IS NULL, giorno DESC, istante_utc DESC " +
            "LIMIT ? OFFSET ?", quanti, da)

    fun scatto(scattoId: Long): Riga = dentro.righe(
        "SELECT * FROM scatti WHERE id = ?", scattoId).firstOrNull()
        ?: throw ErroreVisore("Questo scatto non e' in questo pacchetto.")

    fun nodi(): List<Riga> = dentro.righe("SELECT * FROM nodi ORDER BY posizione")

    fun persone(): List<Riga> =
        dentro.righe("SELECT * FROM persone ORDER BY quanti DESC, nome")

    fun insiemeA(personaId: Long): List<Riga> = dentro.righe(
        "SELECT p.*, i.quante FROM insieme i " +
            "JOIN persone p ON p.id = i.altra_id " +
            "WHERE i.persona_id = ? ORDER BY i.quante DESC", personaId)

    fun dettagli(scattoId: Long): Dettagli {
        val scatto = scatto(scattoId)
        val luogoId = scatto.numero("luogo_id")
        return Dettagli(
            scatto = scatto,
            luogo = luogoId?.let {
                dentro.righe("SELECT * FROM luoghi WHERE id = ?", it).firstOrNull()
            },
            nodi = dentro.righe(
                "SELECT n.*, e.origine FROM etichette e " +
                    "JOIN nodi n ON n.id = e.nodo_id " +
                    "WHERE e.scatto_id = ? ORDER BY n.posizione", scattoId),
            persone = dentro.righe(
                "SELECT p.*, x.origine FROM persone_negli_scatti x " +
                    "JOIN persone p ON p.id = x.persona_id " +
                    "WHERE x.scatto_id = ? ORDER BY p.quanti DESC, p.nome", scattoId),
        )
    }

    fun cerca(testo: String): Trovato {
        val scritto = testo.trim()
        val pezzo = "%" + scritto + "%"
        val date = if (scritto.length == 4 && scritto.all { it.isDigit() }) {
            dentro.righe(
                "SELECT ? AS anno, count(*) AS quanti FROM scatti " +
                    "WHERE giorno LIKE ?", scritto, "$scritto-%",
            ).filter { (it.intero("quanti") ?: 0) > 0 }
        } else {
            emptyList()
        }
        return Trovato(
            date = date,
            note = dentro.righe(
                "SELECT * FROM scatti WHERE nota LIKE ? ORDER BY giorno DESC", pezzo),
            persone = dentro.righe(
                "SELECT * FROM persone WHERE nome LIKE ? ORDER BY quanti DESC", pezzo),
            nodi = dentro.righe(
                "SELECT * FROM nodi WHERE nome LIKE ? ORDER BY quanti_col_ramo DESC",
                pezzo),
            luoghi = dentro.righe("SELECT * FROM luoghi WHERE nome LIKE ?", pezzo),
            parole = dentro.righe(
                "SELECT s.* FROM scatti s JOIN parole p ON p.scatto_id = s.id " +
                    "WHERE p.parola = ? ORDER BY s.giorno DESC",
                testo.trim().lowercase()),
        )
    }

    fun scorta(): Scorta {
        laScorta?.let { return it }
        val quali = tabelle()
        val cuori = if ("cuori" in quali) {
            dentro.righe("SELECT impronta, messo_il FROM cuori ORDER BY impronta")
                .map { Cuore(it.testo("impronta") ?: "", it.testo("messo_il") ?: "") }
        } else {
            emptyList()
        }
        val tolti = if ("cuori_tolti" in quali) {
            dentro.righe("SELECT impronta, tolto_il FROM cuori_tolti ORDER BY impronta")
                .map { Cuore(it.testo("impronta") ?: "", it.testo("tolto_il") ?: "") }
        } else {
            emptyList()
        }
        val raccolte = if ("raccolte" in quali) {
            dentro.righe("SELECT id, nome, creata_il FROM raccolte ORDER BY id")
                .map { riga ->
                    val numero = riga.numero("id") ?: 0L
                    Raccolta(
                        numero = numero,
                        nome = riga.testo("nome") ?: "",
                        creataIl = riga.testo("creata_il") ?: "",
                        impronte = if ("raccolte_scatti" in quali) {
                            dentro.righe(
                                "SELECT impronta FROM raccolte_scatti " +
                                    "WHERE raccolta_id = ? ORDER BY impronta", numero,
                            ).map { it.testo("impronta") ?: "" }
                        } else {
                            emptyList()
                        },
                    )
                }
        } else {
            emptyList()
        }
        return Scorta(cuori, tolti, raccolte).also { laScorta = it }
    }

    private var laScorta: Scorta? = null

    fun tabelle(): Set<String> = dentro.righe(
        "SELECT name FROM sqlite_master WHERE type = 'table'"
    ).mapNotNull { it.testo("name") }.toSet()

    fun miniatura(scattoId: Long): ByteArray {
        val riga = scatto(scattoId)
        val posto = riga.testo("mini")
            ?: throw ErroreVisore("Questo scatto non ha una miniatura.")
        return chiave.leggiTutto(dentro(cartella, posto))
    }

    fun originale(scattoId: Long): ByteArray {
        val riga = scatto(scattoId)
        return chiave.leggiTutto(dentro(cartella, riga.testo("posto") ?: ""))
    }

    fun movimento(scattoId: Long): ByteArray? {
        val riga = scatto(scattoId)
        val posto = riga.testo("posto_movimento") ?: return null
        if (posto.isEmpty()) {
            return null
        }
        return chiave.leggiTutto(dentro(cartella, posto))
    }

    fun pezzo(scattoId: Long, da: Long, quanti: Int): ByteArray {
        val riga = scatto(scattoId)
        return chiave.leggiPezzo(dentro(cartella, riga.testo("posto") ?: ""), da, quanti)
    }

    fun tiraFuori(scattoId: Long, destinazione: File): String {
        val riga = scatto(scattoId)
        return chiave.decifraFile(dentro(cartella, riga.testo("posto") ?: ""), destinazione)
    }

    fun verifica(solo: Int? = null): Verifica {
        val esito = Verifica()
        val righe = if (solo == null) {
            dentro.righe(
                "SELECT id, impronta, posto, posto_movimento, mini FROM scatti " +
                    "ORDER BY id")
        } else {
            dentro.righe(
                "SELECT id, impronta, posto, posto_movimento, mini FROM scatti " +
                    "ORDER BY id LIMIT ?", solo)
        }

        for (riga in righe) {
            val posto = riga.testo("posto") ?: ""
            val impronta = rileggi(posto, esito)
            if (impronta != null && impronta != riga.testo("impronta")) {
                esito.guasti.add(Guasto(
                    posto, "il contenuto non e' quello che il database dichiara"))
            }
            for (altro in listOf(riga.testo("posto_movimento"), riga.testo("mini"))) {
                if (!altro.isNullOrEmpty()) {
                    rileggi(altro, esito)
                }
            }
        }
        return esito
    }

    private fun rileggi(posto: String, esito: Verifica): String? {
        val dove = dentro(cartella, posto)
        if (!dove.isFile) {
            esito.guasti.add(Guasto(posto, "manca dal pacchetto"))
            return null
        }
        val impronta = Blake2b.Impronta()
        var quanto = 0L
        return try {
            chiave.scorri(dove) { pezzo ->
                impronta.aggiungi(pezzo)
                quanto += pezzo.size.toLong()
            }
            esito.letti += 1
            esito.peso += quanto
            Esadecimale.scritta(impronta.finisci())
        } catch (guaio: PacchettoRovinato) {
            esito.guasti.add(Guasto(posto, guaio.frase))
            null
        }
    }
}

class Giorno(val giorno: String?, val quanti: Int, val luoghi: List<String>)

class Trovato(
    val persone: List<Riga>,
    val nodi: List<Riga>,
    val luoghi: List<Riga>,
    val parole: List<Riga>,
    val date: List<Riga> = emptyList(),
    val note: List<Riga> = emptyList(),
)

class Dettagli(
    val scatto: Riga,
    val luogo: Riga?,
    val nodi: List<Riga>,
    val persone: List<Riga>,
)

class Guasto(val posto: String, val perche: String)

class Verifica(
    var letti: Int = 0,
    var peso: Long = 0,
    val guasti: MutableList<Guasto> = mutableListOf(),
) {

    val tuttoAPosto: Boolean
        get() = guasti.isEmpty()

    fun aParole(): String = if (tuttoAPosto) {
        "$letti file riletti, tutti interi (${peso / (1024 * 1024)} MB)"
    } else {
        "$letti file riletti, ${guasti.size} non tornano"
    }
}
