package visore.lettore

fun interface ApreIlBanco {
    fun apri(byte: ByteArray): Banco
}

fun interface ApreIlBancoDaScrivere {

    fun apri(byte: ByteArray?): BancoCheScrive
}

interface BancoCheScrive : Banco {

    fun esegui(sql: String, vararg valori: Any?)

    fun ultimoNumero(): Long

    fun byte(): ByteArray
}

interface Banco : AutoCloseable {

    fun righe(sql: String, vararg valori: Any?): List<Riga>

    fun unNumero(sql: String, vararg valori: Any?): Long =
        righe(sql, *valori).firstOrNull()?.numero(0) ?: 0L
}

class Riga(private val colonne: List<String>, private val valori: List<Any?>) {

    fun testo(nome: String): String? = quale(nome)?.toString()

    fun testo(posizione: Int): String? = valori.getOrNull(posizione)?.toString()

    fun numero(nome: String): Long? = when (val v = quale(nome)) {
        null -> null
        is Number -> v.toLong()
        else -> v.toString().toLongOrNull()
    }

    fun numero(posizione: Int): Long? = when (val v = valori.getOrNull(posizione)) {
        null -> null
        is Number -> v.toLong()
        else -> v.toString().toLongOrNull()
    }

    fun intero(nome: String): Int? = numero(nome)?.toInt()

    fun reale(nome: String): Double? = when (val v = quale(nome)) {
        null -> null
        is Number -> v.toDouble()
        else -> v.toString().toDoubleOrNull()
    }

    fun ce(nome: String): Boolean = quale(nome) != null

    fun nomi(): List<String> = colonne

    private fun quale(nome: String): Any? {
        val dove = colonne.indexOf(nome)
        return if (dove < 0) null else valori[dove]
    }
}
