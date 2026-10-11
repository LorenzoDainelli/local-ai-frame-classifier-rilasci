package visore.telefono

import visore.lettore.Raccolta

class SchermataDeiPreferiti(
    val quantiCuori: Int,
    val raccolte: List<RigaDellaRaccolta>,
) {

    val titolo: String = TITOLO

    val colonne: Int = SchermataDeiGiorni.COLONNE

    val quante: String
        get() = if (quantiCuori == 1) "1 foto" else "${numero(quantiCuori)} foto"

    val titoloDelleRaccolte: String?
        get() = if (raccolte.isEmpty()) null else RACCOLTE

    val vuota: Boolean
        get() = quantiCuori == 0 && raccolte.isEmpty()

    val frasePerIlVuoto: String
        get() = "Qui finiscono le foto a cui metti il cuore e le raccolte che " +
            "fai tu. Per ora non ce n'e' nessuna."

    companion object {

        const val TITOLO = "Preferiti"
        const val RACCOLTE = "RACCOLTE"

        fun componi(quantiCuori: Int, raccolte: List<Raccolta>) = SchermataDeiPreferiti(
            quantiCuori = quantiCuori,
            raccolte = raccolte.map { RigaDellaRaccolta(it) },
        )
    }
}

class RigaDellaRaccolta(val raccolta: Raccolta) {

    val nome: String
        get() = raccolta.nome

    val quante: String
        get() = if (raccolta.impronte.size == 1) "1 foto"
                else "${numero(raccolta.impronte.size)} foto"

    val sottotitolo: String
        get() {
            val giorno = raccolta.creataIl.take(10).takeIf { it.length == 10 }
            val quando = giorno?.let { inItaliano(it) }
            return if (quando == null) quante else "$quante · fatta qui il $quando"
        }
}

class MentreSiSceglie(val scelte: Set<String> = emptySet()) {

    val titolo: String
        get() = when (scelte.size) {
            0 -> "Scegli"
            1 -> "1 scelta"
            else -> "${numero(scelte.size)} scelte"
        }

    val fine: String = FINE_SCELTA

    val dove: List<String>
        get() = listOf(CUORE, RACCOLTA)

    val siPuoFare: Boolean
        get() = scelte.isNotEmpty()

    fun con(impronta: String) = MentreSiSceglie(scelte + impronta)

    fun senza(impronta: String) = MentreSiSceglie(scelte - impronta)

    fun tutteDelGiorno(delGiorno: List<String>): MentreSiSceglie =
        if (delGiorno.all { it in scelte }) {
            MentreSiSceglie(scelte - delGiorno.toSet())
        } else {
            MentreSiSceglie(scelte + delGiorno)
        }

    fun tuttoIlGiorno(delGiorno: List<String>): Boolean =
        delGiorno.isNotEmpty() && delGiorno.all { it in scelte }

    companion object {
        const val FINE_SCELTA = "Fine"
        const val TUTTE = "tutte"
        const val CUORE = "Preferiti"
        const val RACCOLTA = "In una raccolta"
    }
}
