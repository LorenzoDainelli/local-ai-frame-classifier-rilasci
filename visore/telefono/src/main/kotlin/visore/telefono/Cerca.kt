package visore.telefono

enum class Dove(val comeSiChiama: String) {
    NODI("nodi"),
    PERSONE("persone"),
    LUOGHI("luoghi"),
    DATE("date"),
    NOTE("note"),
    PAROLE("le parole preparate dal PC"),
}

class GruppoTrovato(val titolo: String, val voci: List<String>, val dalPc: Boolean = false)

class SchermataDiRicerca(
    val scritto: String,
    val parole: List<String>,
    val dove: Set<Dove>,
    val gruppi: List<GruppoTrovato>,
) {

    val riga: String?
        get() {
            if (parole.isEmpty()) {
                return null
            }
            val cosa = parole.joinToString(" e ")
            val anno = parole.size == 1 && parole[0].length == 4 &&
                parole[0].all { it.isDigit() }
            val posti = dove.filterNot { anno && it == Dove.DATE }
                .sortedBy { it.ordinal }
                .map { it.comeSiChiama }
            val fra = elencati(posti)
            return if (anno) "cerco $cosa come anno, e fra $fra" else "cerco $cosa fra $fra"
        }

    val vuota: Boolean
        get() = gruppi.all { it.voci.isEmpty() }

    fun perche(nonNelVocabolario: List<String>): String? {
        if (!vuota) {
            return null
        }
        if (nonNelVocabolario.isEmpty()) {
            return "Nessuna foto."
        }
        val quali = nonNelVocabolario.joinToString(" e ")
        val verbo = if (nonNelVocabolario.size == 1) "non e'" else "non sono"
        return "Nessuna foto. Le parole preparate dal PC sono circa duemila, e " +
            "$quali $verbo fra quelle."
    }

    companion object {

        const val SEZIONE = "Cerca"

        const val INVITO = "Cerca"
        const val PER_SOMIGLIANZA = "PER SOMIGLIANZA, CALCOLATA DAL PC"

        val LEGAMI = setOf(
            "di", "da", "del", "della", "dei", "delle", "dello", "degli",
            "il", "lo", "la", "i", "gli", "le", "un", "uno", "una",
            "e", "ed", "a", "al", "alla", "in", "nel", "nella", "con", "per",
            "su", "sul", "sulla", "tra", "fra",
        )

        fun paroleDi(scritto: String): List<String> = scritto
            .lowercase()
            .split(' ', '\t', '\n', ',', ';')
            .map { it.trim() }
            .filter { it.isNotEmpty() && it !in LEGAMI }

        fun componi(
            scritto: String,
            dove: Set<Dove>,
            nodi: List<String> = emptyList(),
            persone: List<String> = emptyList(),
            luoghi: List<String> = emptyList(),
            date: List<String> = emptyList(),
            note: List<String> = emptyList(),
            perSomiglianza: Int = 0,
        ): SchermataDiRicerca {
            val gruppi = mutableListOf<GruppoTrovato>()
            if (date.isNotEmpty()) gruppi += GruppoTrovato("DATE", date)
            if (nodi.isNotEmpty()) gruppi += GruppoTrovato("NODI", nodi)
            if (persone.isNotEmpty()) gruppi += GruppoTrovato("PERSONE", persone)
            if (luoghi.isNotEmpty()) gruppi += GruppoTrovato("LUOGHI", luoghi)
            if (note.isNotEmpty()) gruppi += GruppoTrovato("NOTE", note)
            if (perSomiglianza > 0) {
                val quante = if (perSomiglianza == 1) "1 foto"
                             else "${numero(perSomiglianza)} foto"
                gruppi += GruppoTrovato(PER_SOMIGLIANZA, listOf(quante), dalPc = true)
            }
            return SchermataDiRicerca(scritto, paroleDi(scritto), dove, gruppi)
        }

        fun pezzoDiNota(nota: String, parola: String, quanto: Int = 48): String {
            val pulita = nota.trim().replace(Regex("\\s+"), " ")
            if (pulita.length <= quanto) {
                return "«$pulita»"
            }
            val dove = pulita.lowercase().indexOf(parola.lowercase())
            if (dove < 0) {
                return "«" + pulita.take(quanto).trimEnd() + "...»"
            }
            val da = maxOf(0, dove - quanto / 3)
            val a = minOf(pulita.length, da + quanto)
            val prima = if (da > 0) "..." else ""
            val dopo = if (a < pulita.length) "..." else ""
            return "«$prima" + pulita.substring(da, a).trim() + "$dopo»"
        }

        internal fun elencati(posti: List<String>): String = when (posti.size) {
            0 -> ""
            1 -> posti[0]
            else -> posti.dropLast(1).joinToString(", ") + " e " + posti.last()
        }
    }
}
