package visore.computer

import java.io.File
import kotlin.test.AfterTest
import kotlin.test.BeforeTest
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFailsWith
import kotlin.test.assertFalse
import kotlin.test.assertNotNull
import kotlin.test.assertTrue
import org.json.JSONObject
import visore.lettore.ErroreVisore
import visore.lettore.PacchettoRovinato
import visore.lettore.Pacchetto
import visore.lettore.Ritorno
import visore.lettore.dentro

class SicurezzaTest {

    private lateinit var cartella: File

    @BeforeTest
    fun prima() {
        cartella = PacchettoDiProva.apparecchia()
    }

    @AfterTest
    fun dopo() {
        cartella.deleteRecursively()
    }

    private fun apri(): Pacchetto =
        Pacchetto.apri(cartella, PacchettoDiProva.PAROLA, BancoInMemoria)

    private fun ritocca(cosa: (JSONObject) -> Unit) {
        val carta = File(cartella, "visore.json")
        val dati = JSONObject(carta.readText(Charsets.UTF_8))
        cosa(dati)
        carta.writeText(dati.toString(), Charsets.UTF_8)
    }

    @Test
    fun `due file scambiati di posto non si aprono`() {
        val miniature = File(cartella, "mini").walkTopDown().filter { it.isFile }.toList()
        assertTrue(miniature.size >= 2)
        val uno = miniature[0].readBytes()
        miniature[0].writeBytes(miniature[1].readBytes())
        miniature[1].writeBytes(uno)
        apri().use { pacchetto ->
            val esito = pacchetto.verifica()
            assertFalse(esito.tuttoAPosto)
            assertTrue(esito.guasti.size >= 2)
        }
    }

    @Test
    fun `il database messo al posto di una foto non si apre`() {
        val foto = File(cartella, "foto").walkTopDown().first { it.isFile }
        foto.writeBytes(File(cartella, "dati.db").readBytes())
        apri().use { pacchetto ->
            val posto = foto.relativeTo(cartella).invariantSeparatorsPath
            assertFailsWith<PacchettoRovinato> {
                pacchetto.chiave.leggiTutto(foto, posto)
            }
        }
    }

    @Test
    fun `un percorso non esce dalla cartella del pacchetto`() {
        val guaio = assertFailsWith<ErroreVisore> { dentro(cartella, "../fuori.db") }
        assertEquals("percorso_sospetto", guaio.codice)
        assertFailsWith<ErroreVisore> { dentro(cartella, "foto/../../fuori.db") }
    }

    @Test
    fun `una carta ritoccata nei conti della password non si apre`() {
        ritocca { it.put("n", 1024) }
        val guaio = assertFailsWith<ErroreVisore> { apri() }
        assertEquals("parametri_sconosciuti", guaio.codice)
    }

    @Test
    fun `una carta che chiede conti enormi non fa girare il telefono a vuoto`() {
        ritocca { it.put("n", 1 shl 30) }
        val guaio = assertFailsWith<ErroreVisore> { apri() }
        assertEquals("parametri_sconosciuti", guaio.codice)
    }

    @Test
    fun `un ritorno che non si legge si mette da parte e non si sovrascrive`() {
        val ritorno = dentro(cartella, "ritorno.db")
        val rovinato = "non sono un ritorno cifrato".toByteArray()
        ritorno.writeBytes(rovinato)
        apri().use { pacchetto ->
            Ritorno.apri(pacchetto, BancoDaScrivereInMemoria).use { aperto ->
                assertNotNull(aperto.guaio)
            }
        }
        val messi = cartella.listFiles { file ->
            file.name.startsWith("ritorno.db.illeggibile-")
        }.orEmpty()
        assertEquals(1, messi.size)
        assertTrue(messi[0].readBytes().contentEquals(rovinato))
    }
}
