package visore.telefono

import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertNull
import kotlin.test.assertTrue

class NodiTest {

    private val tutti = listOf(
        Nodo(1, null, "nodo_1", quantiQui = 612, quantiColRamo = 4812),
        Nodo(2, null, "nodo_2", quantiQui = 100, quantiColRamo = 1190),
        Nodo(7, null, "nodo_7", quantiQui = 318, quantiColRamo = 318),
        Nodo(9, null, "nodo_9", quantiQui = 27, quantiColRamo = 27),
        Nodo(3, 1, "nodo_3", quantiQui = 1204, quantiColRamo = 1204),
        Nodo(4, 1, "nodo_4", quantiQui = 880, quantiColRamo = 880),
        Nodo(11, 1, "nodo_11", quantiQui = 96, quantiColRamo = 96),
        Nodo(5, 2, "nodo_5", quantiQui = 1090, quantiColRamo = 1090),
        Nodo(20, null, "nodo_20", quantiQui = 0, quantiColRamo = 0),
    )

    @Test
    fun `il primo piano e' quello dei nodi senza genitore`() {
        val piano = Piano.componi(tutti)
        assertEquals("Nodi", piano.titolo)
        assertFalse(piano.siTorna)
        assertEquals(listOf("nodo_1", "nodo_2", "nodo_7", "nodo_9"),
            piano.figli.map { it.nome })
    }

    @Test
    fun `i rami senza foto non compaiono`() {
        assertTrue(Piano.componi(tutti).figli.none { it.nome == "nodo_20" })
    }

    @Test
    fun `l'ordine e' quello del PC, non alfabetico e non per quantita'`() {
        val storti = listOf(
            Nodo(9, null, "nodo_9", 27, 27),
            Nodo(1, null, "nodo_1", 612, 4812),
        )
        assertEquals(listOf("nodo_9", "nodo_1"),
            Piano.componi(storti).figli.map { it.nome })
    }

    @Test
    fun `il numero e' quello del ramo intero, coi figli contati`() {
        val righe = Piano.componi(tutti).figli
        assertEquals("4.812 foto · 3 sotto", righe[0].sottotitolo)
        assertTrue(righe[0].siScende)
        assertEquals("318 foto", righe[2].sottotitolo)
        assertFalse(righe[2].siScende)
    }

    @Test
    fun `dentro un nodo ci sono le pillole dei figli e la riga di cosa si guarda`() {
        val piano = Piano.componi(tutti, dentro = 1)
        assertEquals("nodo_1", piano.titolo)
        assertTrue(piano.siTorna)
        assertEquals(listOf("nodo_3 · 1.204", "nodo_4 · 880", "nodo_11 · 96"),
            piano.pillole)
        assertEquals("4.812 foto, coi rami sotto", piano.cosaSiGuarda)
        assertEquals(4812, piano.quante)
    }

    @Test
    fun `solo qui riporta il conto a quelle attaccate al nodo`() {
        val acceso = Piano.componi(tutti, dentro = 1).giraSoloQui()
        assertTrue(acceso.soloQui)
        assertEquals(612, acceso.quante)
        assertEquals("612 foto, solo di qui", acceso.cosaSiGuarda)
        assertEquals(4812, acceso.giraSoloQui().quante)
    }

    @Test
    fun `l'interruttore sta dietro i tre punti, insieme a Ordina`() {
        val dentro = Piano.componi(tutti, dentro = 1)
        assertFalse(dentro.trePuntiVuoto)
        assertEquals(listOf("Solo le foto di qui", "Ordina"), dentro.vociDelMenu)
    }

    @Test
    fun `fuori da un nodo non c'e' ne' il menu ne' la riga`() {
        val primo = Piano.componi(tutti)
        assertTrue(primo.trePuntiVuoto)
        assertEquals(emptyList(), primo.vociDelMenu)
        assertNull(primo.cosaSiGuarda)
    }

    @Test
    fun `una foto sola non si scrive al plurale`() {
        val uno = listOf(Nodo(1, null, "nodo_1", 1, 1))
        assertEquals("1 foto", Piano.componi(uno).figli[0].sottotitolo)
        assertEquals("1 foto, coi rami sotto", Piano.componi(uno, dentro = 1).cosaSiGuarda)
    }
}
