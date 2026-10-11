package visore.telefono

enum class Genere {
    FOTO, LIVE, VIDEO;

    companion object {

        fun di(detto: String?): Genere = when (detto?.lowercase()) {
            "live" -> LIVE
            "video" -> VIDEO
            else -> FOTO
        }
    }
}

enum class CosaFaIlTocco { ASSAGGIO, COMANDI }

class FotoAperta(
    val genere: Genere,
    val sistema: Sistema,
    val comandiAlzati: Boolean = false,
    val siApre: Boolean = true,
) {

    val segnoLive: Boolean
        get() = genere == Genere.LIVE

    val tocco: CosaFaIlTocco
        get() = if (genere == Genere.LIVE) CosaFaIlTocco.ASSAGGIO else CosaFaIlTocco.COMANDI

    val comandiSiChiamanoTrascinando: Boolean
        get() = genere == Genere.LIVE

    val qualcosaSopraLaFoto: Boolean
        get() = false

    val cuore: DoveIlCuore
        get() = if (sistema == Sistema.IPHONE) DoveIlCuore.BARRA_IN_BASSO
                else DoveIlCuore.IN_ALTO_A_DESTRA

    val doppioTocco: Boolean
        get() = true

    val frase: String?
        get() = if (siApre) null else NON_SI_APRE

    companion object {
        const val NON_SI_APRE = "Questa foto non si apre."

        const val SEGNO_LIVE = "LIVE"

        const val CUORE = "cuore"
    }
}

enum class DoveIlCuore { BARRA_IN_BASSO, IN_ALTO_A_DESTRA }

class Informazioni(
    val quando: String?,
    val luogo: String?,
    val latitudine: Double?,
    val longitudine: Double?,
    val nodi: List<Etichetta>,
    val persone: List<Etichetta>,
    val nota: String?,
) {

    val riga: String?
        get() {
            val punto = if (latitudine != null && longitudine != null) {
                "${coordinata(latitudine)}, ${coordinata(longitudine)}"
            } else {
                null
            }
            return listOfNotNull(luogo?.takeIf { it.isNotBlank() }, punto)
                .takeIf { it.isNotEmpty() }?.joinToString(" · ")
        }

    val notaScritta: String?
        get() = nota?.takeIf { it.isNotBlank() }?.let { "«$it»" }
}

class Etichetta(val nome: String, val origine: String?) {

    val segno: String?
        get() = when (origine?.lowercase()) {
            "sistema", "volto" -> "dal programma"
            "a_mano" -> "detto da te"
            else -> null
        }

    val scritta: String
        get() = segno?.let { "$nome · $it" } ?: nome
}

internal fun coordinata(quanto: Double): String {
    val segno = if (quanto < 0) "−" else ""
    val intero = kotlin.math.abs(quanto)
    val migliaia = kotlin.math.round(intero * 10000.0).toLong()
    val decimali = (migliaia % 10000).toString().padStart(4, '0')
    return "$segno${migliaia / 10000}.$decimali"
}
