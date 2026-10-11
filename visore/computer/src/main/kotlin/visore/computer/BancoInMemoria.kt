package visore.computer

import java.sql.Connection
import java.sql.DriverManager
import java.sql.PreparedStatement
import java.sql.Types
import org.sqlite.SQLiteConnection
import visore.lettore.ApreIlBanco
import visore.lettore.ApreIlBancoDaScrivere
import visore.lettore.Banco
import visore.lettore.BancoCheScrive
import visore.lettore.ErroreVisore
import visore.lettore.Riga

object BancoInMemoria : ApreIlBanco {

    override fun apri(byte: ByteArray): Banco = apriDavvero(byte)
}

object BancoDaScrivereInMemoria : ApreIlBancoDaScrivere {

    override fun apri(byte: ByteArray?): BancoCheScrive = apriDavvero(byte)
}

private fun apriDavvero(byte: ByteArray?): BancoCheScrive {
    val connessione = DriverManager.getConnection("jdbc:sqlite::memory:")
    if (byte != null) {
        try {
            (connessione as SQLiteConnection).deserialize("main", byte)
        } catch (guaio: Exception) {
            connessione.close()
            throw ErroreVisore(
                "Questo database si e' decifrato, ma dentro non c'e' un " +
                    "database. Il pacchetto va ricopiato dal computer.",
                "pacchetto_rovinato")
        }
    }
    return BancoAperto(connessione)
}

private class BancoAperto(private val connessione: Connection) : BancoCheScrive {

    override fun righe(sql: String, vararg valori: Any?): List<Riga> {
        connessione.prepareStatement(sql).use { domanda ->
            metti(domanda, valori)
            domanda.executeQuery().use { risposta ->
                val quante = risposta.metaData.columnCount
                val colonne = (1..quante).map { risposta.metaData.getColumnLabel(it) }
                val fuori = mutableListOf<Riga>()
                while (risposta.next()) {
                    fuori.add(Riga(colonne, (1..quante).map { risposta.getObject(it) }))
                }
                return fuori
            }
        }
    }

    override fun esegui(sql: String, vararg valori: Any?) {
        connessione.prepareStatement(sql).use { comando ->
            metti(comando, valori)
            comando.executeUpdate()
        }
    }

    override fun ultimoNumero(): Long =
        righe("SELECT last_insert_rowid()").firstOrNull()?.numero(0) ?: 0L

    override fun byte(): ByteArray = (connessione as SQLiteConnection).serialize("main")

    override fun close() {
        connessione.close()
    }

    private fun metti(domanda: PreparedStatement, valori: Array<out Any?>) {
        for ((posizione, valore) in valori.withIndex()) {
            when (valore) {
                null -> domanda.setNull(posizione + 1, Types.NULL)
                is Int -> domanda.setInt(posizione + 1, valore)
                is Long -> domanda.setLong(posizione + 1, valore)
                is Double -> domanda.setDouble(posizione + 1, valore)
                else -> domanda.setString(posizione + 1, valore.toString())
            }
        }
    }
}
