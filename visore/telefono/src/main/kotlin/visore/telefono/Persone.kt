package visore.telefono

import visore.lettore.Riga

class Persona(
    val numero: Long,
    val nome: String,
    val volto: String?,
    val quanti: Int,
    val dalGiorno: String?,
    val alGiorno: String?,
) {

    val sottoLaFaccia: List<String>
        get() = listOf(nome, numero(quanti))

    val periodo: String?
        get() {
            val dal = dalGiorno?.take(4)?.takeIf { it.length == 4 }
            val al = alGiorno?.take(4)?.takeIf { it.length == 4 }
            return when {
                dal == null && al == null -> null
                dal == al -> dal
                dal == null || al == null -> dal ?: al
                else -> "$dal−$al"
            }
        }

    companion object {

        fun da(riga: Riga) = Persona(
            numero = riga.numero("id") ?: 0L,
            nome = riga.testo("nome") ?: "",
            volto = riga.testo("volto"),
            quanti = riga.intero("quanti") ?: 0,
            dalGiorno = riga.testo("dal_giorno"),
            alGiorno = riga.testo("al_giorno"),
        )
    }
}

class SchermataDellePersone(val persone: List<Persona>) {

    val colonne: Int = SchermataDeiGiorni.COLONNE

    val quante: Int
        get() = persone.size

    val vuota: Boolean
        get() = persone.isEmpty()

    val frasePerIlVuoto: String
        get() = "Qui ci sono le persone a cui hai dato un nome sul computer. " +
            "Per ora non ce n'e' nessuna."

    companion object {
        const val SEZIONE = "Persone"
    }
}

class InsiemeA(val persona: Persona, val quanteInsieme: Int) {

    val sotto: String
        get() = numero(quanteInsieme)

    companion object {

        const val TITOLO = "spesso insieme a"

        fun quante(schermoGrande: Boolean): Int = if (schermoGrande) 4 else 3

        fun da(riga: Riga) = InsiemeA(
            persona = Persona.da(riga),
            quanteInsieme = riga.intero("quante") ?: 0,
        )
    }
}

class DentroUnaPersona(
    val persona: Persona,
    val insieme: List<InsiemeA>,
    val conLaltra: InsiemeA? = null,
) {

    val titolo: String
        get() = conLaltra?.let { "${persona.nome} e ${it.persona.nome}" } ?: persona.nome

    val facce: List<Persona>
        get() = conLaltra?.let { listOf(persona, it.persona) } ?: listOf(persona)

    val crocetta: Boolean
        get() = conLaltra != null

    val quante: Int
        get() = conLaltra?.quanteInsieme ?: persona.quanti

    val sottotitolo: String
        get() {
            val foto = if (quante == 1) "1 foto" else "${numero(quante)} foto"
            if (conLaltra != null) {
                return "$foto insieme"
            }
            return persona.periodo?.let { "$foto · $it" } ?: foto
        }

    val mostraLaRiga: Boolean
        get() = conLaltra == null && insieme.isNotEmpty()

    fun conAnche(altra: InsiemeA) = DentroUnaPersona(persona, insieme, altra)

    fun senzaLaltra() = DentroUnaPersona(persona, insieme, null)
}
