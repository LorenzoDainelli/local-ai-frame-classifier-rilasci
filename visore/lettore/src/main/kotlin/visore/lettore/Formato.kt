package visore.lettore

import java.io.File
import org.json.JSONException
import org.json.JSONObject

const val VERSIONE_FORMATO = 1

const val CARTA = "visore.json"
const val DATI = "dati.db"
const val RITORNO = "ritorno.db"
const val FOTO = "foto"
const val MINI = "mini"
const val VOLTI = "volti"
const val SENZA_DATA = "senza-data"

const val COMPLETO = "completo"
const val INTERROTTO = "interrotto"

fun dentro(cartella: File, posto: String): File {
    var dove = cartella
    for (pezzo in posto.split("/")) {
        dove = File(dove, pezzo)
    }
    return dove
}

class Carta(
    val telefono: String,
    val archivio: String,
    val sale: String,
    val prova: String,
    val versioneFormato: Int,
    val versioneOfficina: String,
    val versioneVocabolario: String,
    val stato: String,
    val fattoIl: String,
    val finitoIl: String,
    val quantiScatti: Int,
    val quantiVideo: Int,
    val peso: Long,
    val dalGiorno: String,
    val alGiorno: String,
    val kdf: String,
    val n: Int,
    val r: Int,
    val p: Int,
    val blocco: Int,
    val cifra: String,
    val note: List<String>,
) {

    companion object {

        fun leggi(cartella: File): Carta {
            val dove = File(cartella, CARTA)
            if (!dove.isFile) {
                throw ErroreVisore(
                    "In «${cartella.name}» non c'e' nessun pacchetto del Visore: " +
                        "manca la carta d'identita'. Se la cartella e' quella " +
                        "giusta, il pacchetto va ricopiato dal computer.",
                    "pacchetto_assente")
            }
            val dati = try {
                JSONObject(dove.readText(Charsets.UTF_8))
            } catch (guaio: JSONException) {
                throw ErroreVisore(
                    "La carta d'identita' del pacchetto e' rovinata. Il " +
                        "pacchetto va ricopiato dal computer.", "carta_rovinata")
            } catch (guaio: java.io.IOException) {
                throw ErroreVisore(
                    "La carta d'identita' del pacchetto non si legge. Il " +
                        "pacchetto va ricopiato dal computer.", "carta_rovinata")
            }
            val note = mutableListOf<String>()
            dati.optJSONArray("note")?.let { elenco ->
                for (i in 0 until elenco.length()) {
                    note.add(elenco.optString(i, ""))
                }
            }
            return Carta(
                telefono = dati.optString("telefono", ""),
                archivio = dati.optString("archivio", ""),
                sale = dati.optString("sale", ""),
                prova = dati.optString("prova", ""),
                versioneFormato = dati.optInt("versione_formato", VERSIONE_FORMATO),
                versioneOfficina = dati.optString("versione_officina", ""),
                versioneVocabolario = dati.optString("versione_vocabolario", ""),
                stato = dati.optString("stato", INTERROTTO),
                fattoIl = dati.optString("fatto_il", ""),
                finitoIl = dati.optString("finito_il", ""),
                quantiScatti = dati.optInt("quanti_scatti", 0),
                quantiVideo = dati.optInt("quanti_video", 0),
                peso = dati.optLong("peso", 0L),
                dalGiorno = dati.optString("dal_giorno", ""),
                alGiorno = dati.optString("al_giorno", ""),
                kdf = dati.optString("kdf", "scrypt"),
                n = dati.optInt("n", COSTO),
                r = dati.optInt("r", BLOCCO_SCRYPT),
                p = dati.optInt("p", PARALLELO),
                blocco = dati.optInt("blocco", BLOCCO),
                cifra = dati.optString("cifra", "AES-256-GCM"),
                note = note,
            )
        }
    }

    val completa: Boolean
        get() = stato == COMPLETO

    fun controllaIlFormato() {
        if (versioneFormato > VERSIONE_FORMATO) {
            throw ErroreVisore(
                "Questo pacchetto e' stato fatto da una versione piu' nuova del " +
                    "programma, e questa non lo sa leggere. Aggiorna l'app, " +
                    "oppure rifai il pacchetto con l'Officina che hai.",
                "formato_troppo_nuovo")
        }
    }

    fun piuVecchioDelProgramma(): Boolean = versioneFormato < VERSIONE_FORMATO

    fun chiave(password: String): Chiave =
        Chiave.controllaLaPassword(password, Esadecimale.byte(sale), prova, n, r, p)
}
