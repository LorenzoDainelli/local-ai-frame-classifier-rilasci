package visore.telefono

import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertNull
import kotlin.test.assertTrue

class PersoneTest {

    private val prima = Persona(1, "persona_1", "volti/1.jpg", 3114, "2011-04-02", "2026-01-09")
    private val seconda = Persona(2, "persona_2", "volti/2.jpg", 2870, "2013-06-01", "2026-02-02")
    private val quinta = Persona(5, "persona_5", "volti/5.jpg", 1402, "2016-01-01", "2022-12-30")

    @Test
    fun `sotto la faccia ci sono il nome e il numero, e basta`() {
        assertEquals(listOf("persona_1", "3.114"), prima.sottoLaFaccia)
        assertEquals(2, prima.sottoLaFaccia.size)
    }

    @Test
    fun `il periodo si legge dentro la persona, non sotto la faccia`() {
        assertEquals("2011−2026", prima.periodo)
        assertEquals("2016−2022", quinta.periodo)
        assertFalse(prima.sottoLaFaccia.any { it.contains("−") })
    }

    @Test
    fun `un anno solo non si scrive due volte, e senza date non c'e' periodo`() {
        assertEquals("2019", Persona(9, "persona_9", null, 4, "2019-01-01", "2019-12-31").periodo)
        assertNull(Persona(9, "persona_9", null, 4, null, null).periodo)
        assertEquals("2019", Persona(9, "persona_9", null, 4, "2019-01-01", null).periodo)
    }

    @Test
    fun `la griglia ha tre colonne e si dice quando e' vuota`() {
        val schermata = SchermataDellePersone(listOf(prima, seconda))
        assertEquals(3, schermata.colonne)
        assertEquals(2, schermata.quante)
        assertFalse(schermata.vuota)
        assertTrue(SchermataDellePersone(emptyList()).vuota)
    }

    private val insieme = listOf(
        InsiemeA(quinta, 1204),
        InsiemeA(prima, 640),
    )

    @Test
    fun `dentro una persona si legge il conto e il periodo`() {
        val dentro = DentroUnaPersona(seconda, insieme)
        assertEquals("persona_2", dentro.titolo)
        assertEquals("2.870 foto · 2013−2026", dentro.sottotitolo)
        assertTrue(dentro.mostraLaRiga)
        assertFalse(dentro.crocetta)
    }

    @Test
    fun `la riga spesso insieme a porta il numero che dice cosa succede`() {
        assertEquals("1.204", insieme[0].sotto)
        assertEquals("640", insieme[1].sotto)
        assertEquals(3, InsiemeA.quante(schermoGrande = false))
        assertEquals(4, InsiemeA.quante(schermoGrande = true))
    }

    @Test
    fun `tutte e due si dice con le due facce, i due nomi e un numero`() {
        val tutteEDue = DentroUnaPersona(seconda, insieme).conAnche(insieme[0])
        assertEquals("persona_2 e persona_5", tutteEDue.titolo)
        assertEquals(listOf("persona_2", "persona_5"), tutteEDue.facce.map { it.nome })
        assertEquals("1.204 foto insieme", tutteEDue.sottotitolo)
        assertTrue(tutteEDue.crocetta)
        assertFalse(tutteEDue.mostraLaRiga)
    }

    @Test
    fun `la crocetta e' il modo di tornare indietro`() {
        val dentro = DentroUnaPersona(seconda, insieme)
        val tornata = dentro.conAnche(insieme[0]).senzaLaltra()
        assertFalse(tornata.crocetta)
        assertEquals("persona_2", tornata.titolo)
        assertEquals("2.870 foto · 2013−2026", tornata.sottotitolo)
    }

    @Test
    fun `senza nessuno insieme la riga non compare`() {
        assertFalse(DentroUnaPersona(seconda, emptyList()).mostraLaRiga)
    }
}
