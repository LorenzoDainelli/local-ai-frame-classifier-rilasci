package visore.telefono

class SchermataDiApertura(
    val titolo: String,
    val quantiScatti: Int,
    val copiatoIl: String?,
    val firma: Firma?,
) {

    val riga: String
        get() {
            val scatti = if (quantiScatti == 1) "1 scatto" else "${numero(quantiScatti)} scatti"
            val quando = copiatoIl?.let { inItaliano(it) }
            return if (quando == null) scatti else "$scatti, copiati il $quando"
        }

    val promessa: String
        get() = "La chiave vive solo finche' l'app e' aperta."

    companion object {

        const val TITOLO = "Visore"

        const val PASSWORD = "Password"

        fun componi(
            quantiScatti: Int,
            copiatoIl: String? = null,
            firma: Firma? = null,
        ) = SchermataDiApertura(TITOLO, quantiScatti, copiatoIl, firma)
    }
}

class Firma(val giorniRimasti: Int) {

    val scaduta: Boolean
        get() = giorniRimasti <= 0

    val frase: String
        get() = when {
            giorniRimasti <= 0 -> "Firma scaduta: va rinnovata dal computer."
            giorniRimasti == 1 -> "Firma valida ancora 1 giorno"
            else -> "Firma valida ancora $giorniRimasti giorni"
        }
}

class TastoApri(val sbagliate: Int = 0, val restano: Int = 0) {

    val acceso: Boolean
        get() = restano <= 0

    val scritta: String
        get() = if (acceso) APRI else "$APRI · $restano"

    val riempimento: Double
        get() {
            val quanto = attesaDopo(sbagliate)
            return if (quanto <= 0) 1.0 else (quanto - restano).toDouble() / quanto
        }

    val avviso: String?
        get() = if (sbagliate > 0) "Password sbagliata." else null

    fun sbagliata(): TastoApri {
        val quante = sbagliate + 1
        return TastoApri(quante, attesaDopo(quante))
    }

    fun unSecondo(): TastoApri = TastoApri(sbagliate, if (restano > 0) restano - 1 else 0)

    companion object {

        const val APRI = "Apri"

        fun attesaDopo(sbagliate: Int): Int = when {
            sbagliate <= 0 -> 0
            sbagliate >= 30 -> Int.MAX_VALUE
            else -> 1 shl (sbagliate - 1)
        }
    }
}

object QuandoVaMale {

    val nonSiApre: List<String> = listOf(
        "Il pacchetto non si apre",
        "Ricopialo dal computer, col cavo. Le foto sul PC non sono toccate, e i " +
            "preferiti che hai messo qui restano dentro il pacchetto.",
    )

    val aMeta: String =
        "Questo pacchetto e' stato copiato a meta': manca qualche foto. " +
            "Si continua con quello che c'e'."
}
