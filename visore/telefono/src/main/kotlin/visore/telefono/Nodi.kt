package visore.telefono

import visore.lettore.Riga

class Nodo(
    val numero: Long,
    val genitore: Long?,
    val nome: String,
    val quantiQui: Int,
    val quantiColRamo: Int,
) {

    companion object {

        fun da(riga: Riga) = Nodo(
            numero = riga.numero("id") ?: 0L,
            genitore = riga.numero("genitore_id"),
            nome = riga.testo("nome") ?: "",
            quantiQui = riga.intero("quanti") ?: 0,
            quantiColRamo = riga.intero("quanti_col_ramo") ?: 0,
        )
    }
}

class RigaDelNodo(val nodo: Nodo, val quantiSotto: Int) {

    val nome: String
        get() = nodo.nome

    val sottotitolo: String
        get() {
            val foto = if (nodo.quantiColRamo == 1) "1 foto"
                       else "${numero(nodo.quantiColRamo)} foto"
            return if (quantiSotto > 0) "$foto · $quantiSotto sotto" else foto
        }

    val siScende: Boolean
        get() = quantiSotto > 0
}

class Piano(
    val dentro: Nodo?,
    val figli: List<RigaDelNodo>,
    val soloQui: Boolean = false,
) {

    val titolo: String
        get() = dentro?.nome ?: SEZIONE

    val siTorna: Boolean
        get() = dentro != null

    val pillole: List<String>
        get() = figli.map { "${it.nome} · ${numero(it.nodo.quantiColRamo)}" }

    val quante: Int
        get() = dentro?.let { if (soloQui) it.quantiQui else it.quantiColRamo } ?: 0

    val cosaSiGuarda: String?
        get() {
            if (dentro == null) {
                return null
            }
            val foto = if (quante == 1) "1 foto" else "${numero(quante)} foto"
            return if (soloQui) "$foto, solo di qui" else "$foto, coi rami sotto"
        }

    val trePuntiVuoto: Boolean
        get() = dentro == null

    val vociDelMenu: List<String>
        get() = if (dentro == null) emptyList() else listOf(SOLO_QUI, ORDINA)

    fun giraSoloQui(): Piano = Piano(dentro, figli, !soloQui)

    companion object {

        const val SEZIONE = "Nodi"
        const val SOLO_QUI = "Solo le foto di qui"
        const val ORDINA = "Ordina"

        fun componi(tutti: List<Nodo>, dentro: Long? = null, soloQui: Boolean = false): Piano {
            val quantiFigli = tutti
                .filter { it.quantiColRamo > 0 }
                .groupingBy { it.genitore }
                .eachCount()
            val figli = tutti
                .filter { it.genitore == dentro }
                .filter { it.quantiColRamo > 0 }
                .map { RigaDelNodo(it, quantiFigli[it.numero] ?: 0) }
            return Piano(
                dentro = dentro?.let { quale -> tutti.firstOrNull { it.numero == quale } },
                figli = figli,
                soloQui = soloQui,
            )
        }
    }
}
