package visore.telefono

import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertNull
import kotlin.test.assertTrue

class CercaTest {

    private val dove = setOf(Dove.NODI, Dove.PERSONE, Dove.LUOGHI, Dove.DATE, Dove.NOTE)

    @Test
    fun `la riga dice dove si sta cercando davvero`() {
        val schermata = SchermataDiRicerca.componi("nodo_3", dove, nodi = listOf("nodo_3"))
        assertEquals("cerco nodo_3 fra nodi, persone, luoghi, date e note", schermata.riga)
    }

    @Test
    fun `un anno si dice come anno`() {
        val schermata = SchermataDiRicerca.componi("2019", dove)
        assertEquals("cerco 2019 come anno, e fra nodi, persone, luoghi e note",
            schermata.riga)
    }

    @Test
    fun `le paroline che non dicono niente non si cercano`() {
        assertEquals(listOf("cappello", "paglia"),
            SchermataDiRicerca.paroleDi("cappello di paglia"))
        assertEquals(listOf("cappello", "paglia"),
            SchermataDiRicerca.componi("cappello di paglia", setOf(Dove.PAROLE)).parole)
        assertEquals("cerco cappello e paglia fra le parole preparate dal PC",
            SchermataDiRicerca.componi("cappello di paglia", setOf(Dove.PAROLE)).riga)
    }

    @Test
    fun `senza niente scritto non c'e' nessuna riga`() {
        assertNull(SchermataDiRicerca.componi("", dove).riga)
        assertNull(SchermataDiRicerca.componi("   di la   ", dove).riga)
    }

    @Test
    fun `i gruppi hanno un titolo anche quando sono uno solo`() {
        val schermata = SchermataDiRicerca.componi(
            "nodo_3", dove, nodi = listOf("nodo_3"), perSomiglianza = 212)
        assertEquals(listOf("NODI", "PER SOMIGLIANZA, CALCOLATA DAL PC"),
            schermata.gruppi.map { it.titolo })
        assertFalse(schermata.vuota)
    }

    @Test
    fun `il gruppo del PC dichiara da dove viene ed e' staccato`() {
        val schermata = SchermataDiRicerca.componi("mare", setOf(Dove.PAROLE),
            perSomiglianza = 1204)
        val ultimo = schermata.gruppi.last()
        assertTrue(ultimo.dalPc)
        assertEquals("PER SOMIGLIANZA, CALCOLATA DAL PC", ultimo.titolo)
        assertEquals(listOf("1.204 foto"), ultimo.voci)
        assertTrue(schermata.gruppi.filter { it.dalPc }.size == 1)
    }

    @Test
    fun `il vuoto dice perche' e' vuoto`() {
        val schermata = SchermataDiRicerca.componi("cappello di paglia", setOf(Dove.PAROLE))
        assertTrue(schermata.vuota)
        assertEquals(
            "Nessuna foto. Le parole preparate dal PC sono circa duemila, e " +
                "paglia non e' fra quelle.",
            schermata.perche(listOf("paglia")))
        assertEquals(
            "Nessuna foto. Le parole preparate dal PC sono circa duemila, e " +
                "cappello e paglia non sono fra quelle.",
            schermata.perche(listOf("cappello", "paglia")))
    }

    @Test
    fun `un archivio che non ha quella foto si dice in un altro modo`() {
        val schermata = SchermataDiRicerca.componi("nodo_99", dove)
        assertEquals("Nessuna foto.", schermata.perche(emptyList()))
    }

    @Test
    fun `le date e le note sono due gruppi come gli altri`() {
        val schermata = SchermataDiRicerca.componi(
            "2019", dove,
            date = listOf("2019 · 3.902 foto"),
            luoghi = listOf("luogo_4 · 212 foto nel 2019"),
            note = listOf("«...scritta nel 2019 sul PC»"))
        assertEquals(listOf("DATE", "LUOGHI", "NOTE"), schermata.gruppi.map { it.titolo })
        assertEquals("2019 · 3.902 foto", schermata.gruppi.first().voci.first())
        assertFalse(schermata.gruppi.any { it.dalPc })
    }

    @Test
    fun `il gruppo del PC resta l'ultimo anche quando c'e' tutto il resto`() {
        val schermata = SchermataDiRicerca.componi(
            "mare", dove, nodi = listOf("nodo_3"), date = listOf("2019 · 12 foto"),
            note = listOf("«mare»"), perSomiglianza = 8)
        assertTrue(schermata.gruppi.last().dalPc)
    }

    @Test
    fun `una nota corta si legge intera`() {
        assertEquals("«una nota corta»",
            SchermataDiRicerca.pezzoDiNota("una nota corta", "nota"))
        assertEquals("«una nota corta»",
            SchermataDiRicerca.pezzoDiNota("  una   nota\n corta  ", "nota"))
    }

    @Test
    fun `una nota lunga si mostra dove sta la parola`() {
        val lunga = "questa e' una nota molto lunga che ho scritto sul PC " +
            "tanti anni fa, e la parola cercata sta giusto in mezzo, con " +
            "dell'altro testo prima e dell'altro testo dopo di lei"
        val pezzo = SchermataDiRicerca.pezzoDiNota(lunga, "cercata")
        assertTrue(pezzo.contains("cercata"))
        assertTrue(pezzo.startsWith("«..."), pezzo)
        assertTrue(pezzo.endsWith("...»"), pezzo)
        assertTrue(pezzo.length < lunga.length)

        val inFondo = SchermataDiRicerca.pezzoDiNota(lunga, "lei")
        assertTrue(inFondo.endsWith("di lei»"), inFondo)
        assertTrue(inFondo.startsWith("«..."), inFondo)
    }

    @Test
    fun `una nota lunga senza quella parola si taglia in fondo`() {
        val lunga = "una nota lunghissima che parla di tutt'altro e continua " +
            "ancora per un bel pezzo senza mai dire quella cosa"
        val pezzo = SchermataDiRicerca.pezzoDiNota(lunga, "assente")
        assertTrue(pezzo.startsWith("«una nota"))
        assertTrue(pezzo.endsWith("...»"))
    }

    @Test
    fun `dove c'e' qualcosa non si spiega nessun vuoto`() {
        val schermata = SchermataDiRicerca.componi("nodo_3", dove, nodi = listOf("nodo_3"))
        assertNull(schermata.perche(listOf("nodo_3")))
    }
}
