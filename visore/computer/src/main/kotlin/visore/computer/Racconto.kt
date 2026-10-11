package visore.computer

import org.json.JSONArray
import org.json.JSONObject
import visore.lettore.BLOCCO
import visore.lettore.Blake2b
import visore.lettore.Pacchetto

fun racconta(pacchetto: Pacchetto, verifica: Boolean = true): JSONObject {
    val detto = JSONObject()
    detto.put("telefono", pacchetto.carta.telefono)
    detto.put("archivio", pacchetto.carta.archivio)
    detto.put("completo", pacchetto.completo)
    detto.put("versione_formato", pacchetto.carta.versioneFormato)
    detto.put("quanti", pacchetto.quanti())

    val giorni = JSONArray()
    for (giorno in pacchetto.giorni()) {
        giorni.put(JSONObject()
            .put("giorno", giorno.giorno ?: JSONObject.NULL)
            .put("quanti", giorno.quanti)
            .put("luoghi", JSONArray(giorno.luoghi)))
    }
    detto.put("giorni", giorni)

    detto.put("nodi", JSONArray(pacchetto.nodi().map { it.testo("nome") }))
    detto.put("persone", JSONArray(pacchetto.persone().map { it.testo("nome") }))

    val scatti = JSONArray()
    for (riga in pacchetto.scatti(quanti = 500)) {
        scatti.put(JSONObject()
            .put("id", riga.numero("id"))
            .put("impronta", riga.testo("impronta"))
            .put("genere", riga.testo("genere"))
            .put("giorno", riga.testo("giorno") ?: JSONObject.NULL)
            .put("posto", riga.testo("posto"))
            .put("dimensione", riga.numero("dimensione")))
    }
    detto.put("scatti", scatti)

    val informazioni = JSONObject()
    for ((chiave, valore) in pacchetto.informazioni()) {
        informazioni.put(chiave, valore)
    }
    detto.put("informazioni", informazioni)

    detto.put("dettagli", dettagli(pacchetto))
    detto.put("cerca", cerca(pacchetto, parola(pacchetto)))
    detto.put("cerca_anno", cerca(pacchetto, anno(pacchetto)))

    val scorta = pacchetto.scorta()
    detto.put("scorta", JSONObject()
        .put("cuori", JSONArray(scorta.cuori.map {
            JSONObject().put("impronta", it.impronta).put("messo_il", it.messoIl)
        }))
        .put("tolti", JSONArray(scorta.tolti.map {
            JSONObject().put("impronta", it.impronta).put("tolto_il", it.messoIl)
        }))
        .put("raccolte", JSONArray(scorta.raccolte.map {
            JSONObject()
                .put("id", it.numero)
                .put("nome", it.nome)
                .put("creata_il", it.creataIl)
                .put("impronte", JSONArray(it.impronte))
        })))
    detto.put("pezzi", pezzi(pacchetto))

    if (verifica) {
        val esito = pacchetto.verifica()
        detto.put("verifica", JSONObject()
            .put("letti", esito.letti)
            .put("peso", esito.peso)
            .put("tutto_a_posto", esito.tuttoAPosto)
            .put("guasti", JSONArray(esito.guasti.map {
                JSONObject().put("posto", it.posto).put("perche", it.perche)
            })))
    }
    return detto
}

private fun pezzi(pacchetto: Pacchetto): JSONArray {
    val fuori = JSONArray()
    val scatti = pacchetto.scatti(quanti = 500)
    if (scatti.isEmpty()) {
        return fuori
    }
    val piuGrosso = scatti.sortedWith(
        compareByDescending<visore.lettore.Riga> { it.numero("dimensione") ?: 0L }
            .thenBy { it.numero("id") ?: 0L }).first()
    val quale = piuGrosso.numero("id") ?: 0L
    val dimensione = piuGrosso.numero("dimensione") ?: 0L

    for (da in listOf(0L, maxOf(0L, BLOCCO - 50L), maxOf(0L, dimensione - 100L))) {
        val pezzo = pacchetto.pezzo(quale, da, 100)
        fuori.put(JSONObject()
            .put("id", quale)
            .put("da", da)
            .put("quanti", 100)
            .put("lungo", pezzo.size)
            .put("impronta", Blake2b.scritta(pezzo)))
    }
    return fuori
}

private fun parola(pacchetto: Pacchetto): String =
    pacchetto.nodi().firstOrNull()?.testo("nome") ?: ""

private fun anno(pacchetto: Pacchetto): String =
    pacchetto.giorni().firstOrNull { it.giorno != null }?.giorno?.take(4) ?: ""

private fun dettagli(pacchetto: Pacchetto): JSONObject {
    val primo = pacchetto.scatti(quanti = 1).firstOrNull() ?: return JSONObject()
    val dentro = pacchetto.dettagli(primo.numero("id") ?: 0L)
    return JSONObject()
        .put("id", primo.numero("id"))
        .put("luogo", dentro.luogo?.testo("nome") ?: JSONObject.NULL)
        .put("nota", dentro.scatto.testo("nota") ?: JSONObject.NULL)
        .put("nodi", JSONArray(dentro.nodi.map {
            JSONArray(listOf(it.testo("nome"), it.testo("origine")))
        }))
        .put("persone", JSONArray(dentro.persone.map {
            JSONArray(listOf(it.testo("nome"), it.testo("origine")))
        }))
}

private fun cerca(pacchetto: Pacchetto, testo: String): JSONObject {
    val trovato = pacchetto.cerca(testo)
    return JSONObject()
        .put("testo", testo)
        .put("nodi", JSONArray(trovato.nodi.map { it.testo("nome") }))
        .put("persone", JSONArray(trovato.persone.map { it.testo("nome") }))
        .put("luoghi", JSONArray(trovato.luoghi.map { it.testo("nome") }))
        .put("parole", trovato.parole.size)
        .put("note", JSONArray(trovato.note.map { it.testo("nota") }))
        .put("date", JSONArray(trovato.date.map {
            JSONArray(listOf(it.testo("anno"), it.intero("quanti")))
        }))
}
