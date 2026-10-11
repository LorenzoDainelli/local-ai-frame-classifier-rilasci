package visore.computer

import java.io.File
import java.util.Base64
import org.json.JSONObject

object PacchettoDiProva {

    const val PAROLA = "tre parole che ricordi"

    fun apparecchia(): File {
        val dove = File.createTempFile("pacchetto-di-prova-", "").let {
            it.delete()
            it.mkdirs()
            it
        }
        dove.deleteOnExit()
        spacchetta(testo("pacchetto-di-prova.txt"), dove)
        return dove
    }

    fun quelloCheCiLeggeIlPython(): JSONObject =
        JSONObject(testo("pacchetto-di-prova.json"))

    private fun testo(nome: String): String =
        PacchettoDiProva::class.java.classLoader.getResourceAsStream(nome)
            ?.bufferedReader()?.use { it.readText() }
            ?: throw IllegalStateException(
                "Manca «$nome» fra le risorse delle prove. Si rifa' con: " +
                    "python strumenti/pacchetto_di_prova.py --rifai")

    private fun spacchetta(testo: String, dove: File) {
        var nome: String? = null
        var quanti = 0
        var pezzi = StringBuilder()

        fun chiudi() {
            val quale = nome ?: return
            val dati = Base64.getDecoder().decode(pezzi.toString())
            check(dati.size == quanti) {
                "«$quale» doveva essere di $quanti byte, ne sono usciti ${dati.size}"
            }
            val fuori = visore.lettore.dentro(dove, quale)
            fuori.parentFile?.mkdirs()
            fuori.writeBytes(dati)
        }

        for (riga in testo.lines()) {
            if (riga.startsWith("#")) {
                continue
            }
            if (riga.isBlank()) {
                chiudi()
                nome = null
                pezzi = StringBuilder()
                continue
            }
            if (nome == null) {
                nome = riga.substringBeforeLast(" ")
                quanti = riga.substringAfterLast(" ").toInt()
                pezzi = StringBuilder()
            } else {
                pezzi.append(riga.trim())
            }
        }
        chiudi()
    }
}
