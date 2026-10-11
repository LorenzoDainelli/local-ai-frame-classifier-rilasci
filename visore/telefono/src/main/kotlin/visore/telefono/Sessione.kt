package visore.telefono

import java.io.File
import visore.lettore.ApreIlBanco
import visore.lettore.ApreIlBancoDaScrivere
import visore.lettore.ErroreVisore
import visore.lettore.Pacchetto
import visore.lettore.Ritorno

class Sessione private constructor(
    val pacchetto: Pacchetto,
    val ritorno: Ritorno,
) : AutoCloseable {

    val guaio: String?
        get() = ritorno.guaio

    val completo: Boolean
        get() = pacchetto.completo

    companion object {

        val DOVE_SI_CERCA = setOf(
            Dove.NODI, Dove.PERSONE, Dove.LUOGHI, Dove.DATE, Dove.NOTE, Dove.PAROLE)

        const val NUOVE = "nuove_ultimo_travaso"

        fun apri(cartella: File, password: String, porta: PortaDelBanco): Sessione {
            val pacchetto = Pacchetto.apri(cartella, password, porta.perLeggere)
            val ritorno = try {
                Ritorno.apri(pacchetto, porta.perScrivere)
            } catch (guaio: Throwable) {
                pacchetto.close()
                throw guaio
            }
            return Sessione(pacchetto, ritorno)
        }
    }

    fun giorni(sistema: Sistema): SchermataDeiGiorni = SchermataDeiGiorni.componi(
        giorni = pacchetto.giorni(),
        sistema = sistema,
        nuove = pacchetto.informazioni()[NUOVE]?.toIntOrNull() ?: 0,
        preferitiERaccolte = ritorno.cuori().size + ritorno.raccolte().size,
    )

    fun nodi(dentro: Long? = null, soloQui: Boolean = false): Piano =
        Piano.componi(pacchetto.nodi().map { Nodo.da(it) }, dentro, soloQui)

    fun persone(): SchermataDellePersone =
        SchermataDellePersone(pacchetto.persone().map { Persona.da(it) })

    fun persona(quale: Long): DentroUnaPersona {
        val chi = pacchetto.persone().map { Persona.da(it) }.firstOrNull { it.numero == quale }
            ?: throw ErroreVisore(
                "Questa persona non e' in questo pacchetto.", "persona_assente")
        return DentroUnaPersona(chi, pacchetto.insiemeA(quale).map { InsiemeA.da(it) })
    }

    fun cerca(scritto: String): SchermataDiRicerca {
        val parole = SchermataDiRicerca.paroleDi(scritto)
        val nodi = mutableSetOf<String>()
        val persone = mutableSetOf<String>()
        val luoghi = mutableSetOf<String>()
        val scatti = mutableSetOf<Long>()
        val date = mutableListOf<String>()
        val note = mutableListOf<String>()
        for (parola in parole) {
            val trovato = pacchetto.cerca(parola)
            trovato.nodi.mapNotNullTo(nodi) { it.testo("nome") }
            trovato.persone.mapNotNullTo(persone) { it.testo("nome") }
            trovato.luoghi.mapNotNullTo(luoghi) { it.testo("nome") }
            trovato.parole.mapNotNullTo(scatti) { it.numero("id") }
            for (riga in trovato.date) {
                val quanti = riga.intero("quanti") ?: 0
                val anno = riga.testo("anno") ?: parola
                val quante = if (quanti == 1) "1 foto" else "${numero(quanti)} foto"
                date += "$anno · $quante"
            }
            for (riga in trovato.note) {
                riga.testo("nota")?.let { note += SchermataDiRicerca.pezzoDiNota(it, parola) }
            }
        }
        return SchermataDiRicerca.componi(
            scritto = scritto,
            dove = DOVE_SI_CERCA,
            nodi = nodi.toList(),
            persone = persone.toList(),
            luoghi = luoghi.toList(),
            date = date.distinct(),
            note = note.distinct(),
            perSomiglianza = scatti.size,
        )
    }

    fun paroleSenzaRisposta(scritto: String): List<String> =
        SchermataDiRicerca.paroleDi(scritto)
            .filter { pacchetto.cerca(it).parole.isEmpty() }

    fun informazioni(scattoId: Long): Informazioni {
        val dettagli = pacchetto.dettagli(scattoId)
        val scatto = dettagli.scatto
        return Informazioni(
            quando = scatto.testo("data_locale") ?: scatto.testo("giorno"),
            luogo = dettagli.luogo?.testo("nome"),
            latitudine = scatto.reale("latitudine"),
            longitudine = scatto.reale("longitudine"),
            nodi = dettagli.nodi.map {
                Etichetta(it.testo("nome") ?: "", it.testo("origine"))
            },
            persone = dettagli.persone.map {
                Etichetta(it.testo("nome") ?: "", it.testo("origine"))
            },
            nota = scatto.testo("nota"),
        )
    }

    fun preferiti(): SchermataDeiPreferiti = SchermataDeiPreferiti.componi(
        quantiCuori = ritorno.cuori().size,
        raccolte = ritorno.raccolte(),
    )

    override fun close() {
        try {
            ritorno.close()
        } finally {
            pacchetto.close()
        }
    }
}

interface PortaDelBanco {

    val perLeggere: ApreIlBanco

    val perScrivere: ApreIlBancoDaScrivere
}

object PortaNonAncoraScelta : PortaDelBanco {

    const val CODICE = "banco_del_telefono_non_scelto"

    const val FRASE =
        "Su questo telefono il database del pacchetto non si sa ancora aprire: " +
            "e' una decisione che si prende con un telefono vero in mano, e non " +
            "e' ancora stata presa (regola 387). Il pacchetto non e' stato " +
            "toccato."

    override val perLeggere = ApreIlBanco { throw ErroreVisore(FRASE, CODICE) }

    override val perScrivere = ApreIlBancoDaScrivere { throw ErroreVisore(FRASE, CODICE) }
}
