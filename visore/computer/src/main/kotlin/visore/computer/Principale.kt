package visore.computer

import java.io.File
import org.json.JSONArray
import org.json.JSONObject
import visore.lettore.ErroreVisore
import visore.lettore.Pacchetto
import visore.lettore.Ritorno

fun main(argomenti: Array<String>) {
    val quali = argomenti.filterNot { it.startsWith("--") }
    if (quali.isEmpty()) {
        System.err.println(
            "Serve la cartella di un pacchetto. La password si scrive " +
                "sull'ingresso standard.")
        kotlin.system.exitProcess(64)
    }
    val cartella = File(quali[0])
    val verifica = argomenti.contains("--verifica")
    val gesti = argomenti.contains("--gesti")
    val password = readlnOrNull() ?: ""
    val resto = generateSequence(::readlnOrNull).joinToString("\n")

    try {
        Pacchetto.apri(cartella, password, BancoInMemoria).use { pacchetto ->
            if (gesti) {
                Ritorno.apri(pacchetto, BancoDaScrivereInMemoria).use { ritorno ->
                    fai(ritorno, JSONObject(resto.ifBlank { "{}" }))
                    println(quelloCheHa(ritorno).toString(2))
                }
            } else {
                println(racconta(pacchetto, verifica).toString(2))
            }
        }
    } catch (guaio: ErroreVisore) {
        println(JSONObject()
            .put("errore", guaio.codice.ifEmpty { "errore" })
            .put("frase", guaio.frase)
            .toString(2))
        kotlin.system.exitProcess(2)
    }
}

private fun fai(ritorno: Ritorno, cosa: JSONObject) {
    cosa.optJSONArray("cuori")?.let { quali ->
        for (i in 0 until quali.length()) {
            ritorno.metti(quali.getString(i))
        }
    }
    cosa.optJSONArray("raccolte")?.let { quali ->
        for (i in 0 until quali.length()) {
            val raccolta = quali.getJSONObject(i)
            val numero = ritorno.nuovaRaccolta(raccolta.optString("nome", "senza nome"))
            raccolta.optJSONArray("impronte")?.let { dentro ->
                for (k in 0 until dentro.length()) {
                    ritorno.mettiNellaRaccolta(numero, dentro.getString(k))
                }
            }
        }
    }
    cosa.optJSONArray("diario")?.let { quali ->
        for (i in 0 until quali.length()) {
            val riga = quali.getJSONObject(i)
            ritorno.apertura(
                apertoIl = riga.getString("aperto_il"),
                durataS = if (riga.isNull("durata_s")) null else riga.getLong("durata_s"),
                latitudine = if (riga.isNull("latitudine")) null else riga.getDouble("latitudine"),
                longitudine = if (riga.isNull("longitudine")) null else riga.getDouble("longitudine"),
                quanteFoto = if (riga.isNull("quante_foto")) null else riga.getLong("quante_foto"),
            )
        }
    }
}

private fun quelloCheHa(ritorno: Ritorno): JSONObject = JSONObject()
    .put("guaio", ritorno.guaio ?: JSONObject.NULL)
    .put("cuori", JSONArray(ritorno.cuori().map {
        JSONObject().put("impronta", it.impronta).put("messo_il", it.messoIl)
    }))
    .put("raccolte", JSONArray(ritorno.raccolte().map {
        JSONObject()
            .put("numero", it.numero)
            .put("nome", it.nome)
            .put("creata_il", it.creataIl)
            .put("impronte", JSONArray(it.impronte))
    }))
    .put("diario", JSONArray(ritorno.diario().map {
        JSONObject()
            .put("aperto_il", it.apertoIl)
            .put("durata_s", it.durataS ?: JSONObject.NULL)
            .put("latitudine", it.latitudine ?: JSONObject.NULL)
            .put("longitudine", it.longitudine ?: JSONObject.NULL)
            .put("quante_foto", it.quanteFoto ?: JSONObject.NULL)
    }))
