package visore.telefono

import visore.lettore.Giorno

enum class Sistema { IPHONE, ANDROID }

class Intestazione(
    val sistema: Sistema,
    val data: String,
    val luogo: String?,
    val quanti: Int,
) {

    val righe: Int
        get() = if (sistema == Sistema.IPHONE) 2 else 1

    val trePunti: Boolean
        get() = sistema == Sistema.IPHONE

    val sinistra: String
        get() = data

    val secondaria: String
        get() {
            val conto = if (sistema == Sistema.IPHONE) {
                if (quanti == 1) "1 scatto" else "${numero(quanti)} scatti"
            } else {
                numero(quanti)
            }
            return if (luogo.isNullOrBlank()) conto else "$luogo · $conto"
        }
}

class Gruppo(val intestazione: Intestazione, val quanti: Int, val senzaData: Boolean)

class Cima(val nuove: Int, val preferitiERaccolte: Int) {

    val frase: String?
        get() = when {
            nuove <= 0 -> null
            nuove == 1 -> "1 foto nuova con l'ultimo travaso"
            else -> "${numero(nuove)} foto nuove con l'ultimo travaso"
        }

    val porta: String
        get() = "Preferiti e raccolte · ${numero(preferitiERaccolte)}"
}

class SchermataDeiGiorni(
    val cima: Cima,
    val gruppi: List<Gruppo>,
    val anni: List<String>,
    val colonne: Int = COLONNE,
) {

    val quante: Int
        get() = gruppi.sumOf { it.quanti }

    val frasePerIlVuoto: String
        get() = "Qui non c'e' ancora niente: l'ultimo travaso non e' stato fatto."

    val vuota: Boolean
        get() = gruppi.isEmpty()

    companion object {

        const val COLONNE = 3

        fun componi(
            giorni: List<Giorno>,
            sistema: Sistema,
            nuove: Int = 0,
            preferitiERaccolte: Int = 0,
        ): SchermataDeiGiorni {
            val gruppi = giorni.map { giorno ->
                val senzaData = giorno.giorno.isNullOrBlank()
                Gruppo(
                    intestazione = Intestazione(
                        sistema = sistema,
                        data = if (senzaData) SENZA_DATA else inItaliano(giorno.giorno!!),
                        luogo = giorno.luoghi.firstOrNull(),
                        quanti = giorno.quanti,
                    ),
                    quanti = giorno.quanti,
                    senzaData = senzaData,
                )
            }
            return SchermataDeiGiorni(
                cima = Cima(nuove, preferitiERaccolte),
                gruppi = gruppi,
                anni = anni(giorni),
            )
        }

        const val SENZA_DATA = "Senza data"

        fun anni(giorni: List<Giorno>): List<String> = giorni
            .mapNotNull { it.giorno?.take(4)?.takeIf { anno -> anno.length == 4 } }
            .distinct()
    }
}

private val MESI = listOf(
    "gennaio", "febbraio", "marzo", "aprile", "maggio", "giugno",
    "luglio", "agosto", "settembre", "ottobre", "novembre", "dicembre",
)

internal fun inItaliano(giorno: String): String {
    val pezzi = giorno.split("-")
    if (pezzi.size < 3) {
        return giorno
    }
    val mese = pezzi[1].toIntOrNull() ?: return giorno
    val quanti = pezzi[2].take(2).toIntOrNull() ?: return giorno
    if (mese !in 1..12) {
        return giorno
    }
    return "$quanti ${MESI[mese - 1]}"
}

internal fun numero(quanti: Int): String {
    val cifre = quanti.toString()
    val pezzi = StringBuilder()
    for ((quante, cifra) in cifre.reversed().withIndex()) {
        if (quante > 0 && quante % 3 == 0) {
            pezzi.append('.')
        }
        pezzi.append(cifra)
    }
    return pezzi.reverse().toString()
}
