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
import org.json.JSONArray
import org.json.JSONObject
import visore.lettore.Blake2b
import visore.lettore.ErroreVisore
import visore.lettore.Pacchetto
import visore.lettore.PasswordSbagliata
import visore.lettore.dentro

class PacchettoTest {

    private lateinit var cartella: File

    @BeforeTest
    fun prima() {
        cartella = PacchettoDiProva.apparecchia()
    }

    @AfterTest
    fun dopo() {
        cartella.deleteRecursively()
    }

    private fun apri(password: String = PacchettoDiProva.PAROLA): Pacchetto =
        Pacchetto.apri(cartella, password, BancoInMemoria)

    @Test
    fun `il Kotlin legge quello che ci legge il Python, campo per campo`() {
        apri().use { pacchetto ->
            assertEquals(
                inOrdine(PacchettoDiProva.quelloCheCiLeggeIlPython()),
                inOrdine(racconta(pacchetto)),
            )
        }
    }

    @Test
    fun `le impronte tornano tutte, che e' il controllo vero`() {
        apri().use { pacchetto ->
            val esito = pacchetto.verifica()
            assertTrue(esito.tuttoAPosto, esito.guasti.map { it.perche }.toString())
            assertTrue(esito.letti > 0)
        }
    }

    @Test
    fun `la password sbagliata si dice subito, e non nomina la password`() {
        val guaio = assertFailsWith<PasswordSbagliata> { apri("tre parole sbagliate") }
        assertFalse(guaio.frase.contains("tre parole"))
        assertEquals("password_sbagliata", guaio.codice)
    }

    @Test
    fun `sbagliare la password non tocca il pacchetto`() {
        val prima = quantiFile()
        assertFailsWith<PasswordSbagliata> { apri("una password qualunque") }
        assertEquals(prima, quantiFile())
        apri().use { assertTrue(it.verifica().tuttoAPosto) }
    }

    @Test
    fun `senza carta d'identita' non si prova nemmeno a decifrare`() {
        File(cartella, "visore.json").delete()
        val guaio = assertFailsWith<ErroreVisore> { apri() }
        assertEquals("pacchetto_assente", guaio.codice)
    }

    @Test
    fun `un pacchetto piu' nuovo dell'app si ferma con una frase`() {
        val carta = File(cartella, "visore.json")
        val dentro = JSONObject(carta.readText())
        dentro.put("versione_formato", 99)
        carta.writeText(dentro.toString(2))

        val guaio = assertFailsWith<ErroreVisore> { apri() }
        assertEquals("formato_troppo_nuovo", guaio.codice)
    }

    @Test
    fun `la carta d'identita' non dice niente dell'archivio`() {
        val carta = File(cartella, "visore.json").readText().lowercase()
        for (parola in listOf("vestiti", "magliette", "tommy", "vacanze", "mare",
                "anna", "marco", "nonna")) {
            assertFalse(carta.contains(parola), "«$parola» non deve stare nella carta")
        }
    }

    @Test
    fun `un file rovinato la verifica lo trova, e gli altri si aprono lo stesso`() {
        val quale = apri().use { it.scatti().first().testo("posto")!! }
        val dove = dentro(cartella, quale)
        val byte = dove.readBytes()
        byte[byte.size - 1] = (byte[byte.size - 1].toInt() xor 0xff).toByte()
        dove.writeBytes(byte)

        apri().use { pacchetto ->
            val esito = pacchetto.verifica()
            assertFalse(esito.tuttoAPosto)
            assertEquals(1, esito.guasti.size)
            assertEquals(quale, esito.guasti.first().posto)
            assertTrue(esito.letti > 0)
        }
    }

    @Test
    fun `un file che sparisce la verifica lo dice`() {
        val quale = apri().use { it.scatti().first().testo("posto")!! }
        assertTrue(dentro(cartella, quale).delete())

        apri().use { pacchetto ->
            val guasti = pacchetto.verifica().guasti
            assertEquals(1, guasti.size)
            assertEquals("manca dal pacchetto", guasti.first().perche)
        }
    }

    @Test
    fun `un pacchetto senza database lo dice invece di aprirsi a meta'`() {
        assertTrue(File(cartella, "dati.db").delete())
        val guaio = assertFailsWith<ErroreVisore> { apri() }
        assertEquals("pacchetto_senza_dati", guaio.codice)
    }

    @Test
    fun `un originale tirato fuori ha l'impronta che dice il database`() {
        apri().use { pacchetto ->
            val riga = pacchetto.scatti().first()
            val quale = riga.numero("id")!!
            val fuori = File(cartella.parentFile, "tirata-fuori.dat")
            try {
                assertEquals(riga.testo("impronta"), pacchetto.tiraFuori(quale, fuori))
                assertEquals(riga.numero("dimensione"), fuori.length())
                assertEquals(riga.testo("impronta"),
                    Blake2b.scritta(pacchetto.originale(quale)))
            } finally {
                fuori.delete()
            }
        }
    }

    @Test
    fun `la live photo si porta dietro il suo movimento`() {
        apri().use { pacchetto ->
            val live = pacchetto.scatti().firstOrNull { it.testo("genere") == "live" }
            assertNotNull(live, "il pacchetto di prova deve avere una live photo")
            val movimento = pacchetto.movimento(live.numero("id")!!)
            assertNotNull(movimento, "senza il .MOV i gesti non hanno cosa muovere")
            assertTrue(movimento.size > 0)
            val ferma = pacchetto.scatti().first { it.testo("genere") == "foto" }
            assertEquals(null, pacchetto.movimento(ferma.numero("id")!!))
        }
    }

    @Test
    fun `un pezzo qualsiasi combacia col file intero`() {
        apri().use { pacchetto ->
            val riga = pacchetto.scatti().first()
            val quale = riga.numero("id")!!
            val intero = pacchetto.originale(quale)
            for (da in listOf(0, 1, 100, intero.size / 2, intero.size - 10)) {
                val quanti = minOf(64, intero.size - da)
                assertEquals(
                    Blake2b.scritta(intero.copyOfRange(da, da + quanti)),
                    Blake2b.scritta(pacchetto.pezzo(quale, da.toLong(), quanti)),
                    "il pezzo da $da non combacia",
                )
            }
            assertEquals(0, pacchetto.pezzo(quale, intero.size + 10L, 100).size)
        }
    }

    @Test
    fun `i giorni vanno dal piu' recente, e i senza data in fondo`() {
        apri().use { pacchetto ->
            val giorni = pacchetto.giorni()
            assertTrue(giorni.size >= 2)
            assertEquals(null, giorni.last().giorno)
            val conData = giorni.mapNotNull { it.giorno }
            assertEquals(conData.sortedDescending(), conData)
        }
    }

    @Test
    fun `un pacchetto completo lo dice, e i nodi arrivano nell'ordine del PC`() {
        apri().use { pacchetto ->
            assertTrue(pacchetto.completo)
            assertEquals(listOf("cartoline", "gite", "francobolli", "brughiera"),
                pacchetto.nodi().map { it.testo("nome") })
            assertEquals(listOf("Ada", "Bruno"),
                pacchetto.persone().map { it.testo("nome") })
        }
    }

    @Test
    fun `la ricerca tiene i nomi e le parole in due gruppi staccati`() {
        apri().use { pacchetto ->
            val trovato = pacchetto.cerca("bru")
            assertEquals(listOf("Bruno"), trovato.persone.map { it.testo("nome") })
            assertEquals(listOf("brughiera"), trovato.nodi.map { it.testo("nome") })
            assertTrue(trovato.parole.isEmpty())
        }
    }

    private fun quantiFile(): Int = cartella.walkTopDown().count { it.isFile }

    private fun inOrdine(cosa: Any?): String = when (cosa) {
        is JSONObject -> cosa.keys().asSequence().sorted().joinToString(
            separator = ",", prefix = "{", postfix = "}") {
            "\"$it\":" + inOrdine(cosa.get(it))
        }
        is JSONArray -> (0 until cosa.length()).joinToString(
            separator = ",", prefix = "[", postfix = "]") { inOrdine(cosa.get(it)) }
        is Number -> cosa.toString()
        JSONObject.NULL, null -> "null"
        else -> "\"" + cosa.toString() + "\""
    }
}
