package visore.telefono

import java.nio.file.Files
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFailsWith
import kotlin.test.assertFalse
import kotlin.test.assertTrue
import visore.lettore.ErroreVisore

class SessioneTest {

    @Test
    fun `la porta non ancora scelta si ferma dicendolo`() {
        val leggendo = assertFailsWith<ErroreVisore> {
            PortaNonAncoraScelta.perLeggere.apri(ByteArray(8))
        }
        val scrivendo = assertFailsWith<ErroreVisore> {
            PortaNonAncoraScelta.perScrivere.apri(null)
        }
        assertEquals(PortaNonAncoraScelta.CODICE, leggendo.codice)
        assertEquals(PortaNonAncoraScelta.CODICE, scrivendo.codice)
    }

    @Test
    fun `la frase e' intera e non dice niente di troppo`() {
        val frase = PortaNonAncoraScelta.FRASE
        assertTrue(frase.endsWith("."))
        assertTrue(frase.length > 80)
        for (parola in listOf("password", "Exception", "null", "SQLite")) {
            assertFalse(frase.contains(parola), "la frase non deve nominare «$parola»")
        }
    }

    @Test
    fun `una cartella senza pacchetto si ferma prima della porta`() {
        val vuota = Files.createTempDirectory("visore-prova").toFile()
        try {
            val guaio = assertFailsWith<ErroreVisore> {
                Sessione.apri(vuota, "una password qualunque", PortaNonAncoraScelta)
            }
            assertEquals("pacchetto_assente", guaio.codice)
        } finally {
            vuota.delete()
        }
    }
}
