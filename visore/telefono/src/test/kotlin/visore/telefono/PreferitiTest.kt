package visore.telefono

import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertNull
import kotlin.test.assertTrue
import visore.lettore.Raccolta

class PreferitiTest {

    private val raccolte = listOf(
        Raccolta(1, "raccolta_1", "2026-03-02T10:00:00Z", List(38) { "impronta_$it" }),
        Raccolta(2, "raccolta_2", "2026-03-04T18:30:00Z", List(12) { "altra_$it" }),
    )

    @Test
    fun `i preferiti sono una griglia e le raccolte un elenco`() {
        val schermata = SchermataDeiPreferiti.componi(212, raccolte)
        assertEquals("Preferiti", schermata.titolo)
        assertEquals("212 foto", schermata.quante)
        assertEquals(3, schermata.colonne)
        assertEquals("RACCOLTE", schermata.titoloDelleRaccolte)
        assertEquals(listOf("raccolta_1", "raccolta_2"), schermata.raccolte.map { it.nome })
    }

    @Test
    fun `una raccolta dice quante foto ha e che e' stata fatta qui`() {
        val prima = SchermataDeiPreferiti.componi(212, raccolte).raccolte[0]
        assertEquals("38 foto", prima.quante)
        assertEquals("38 foto · fatta qui il 2 marzo", prima.sottotitolo)
    }

    @Test
    fun `senza raccolte non c'e' il titolo delle raccolte`() {
        assertNull(SchermataDeiPreferiti.componi(212, emptyList()).titoloDelleRaccolte)
    }

    @Test
    fun `un telefono nuovo lo dice invece di mostrare due elenchi vuoti`() {
        val vuota = SchermataDeiPreferiti.componi(0, emptyList())
        assertTrue(vuota.vuota)
        assertTrue(vuota.frasePerIlVuoto.contains("cuore"))
        assertFalse(SchermataDeiPreferiti.componi(1, emptyList()).vuota)
    }

    @Test
    fun `in cima si conta quello che si e' scelto`() {
        var scelta = MentreSiSceglie()
        assertEquals("Scegli", scelta.titolo)
        assertFalse(scelta.siPuoFare)

        scelta = scelta.con("a")
        assertEquals("1 scelta", scelta.titolo)
        assertTrue(scelta.siPuoFare)

        scelta = scelta.con("b").con("c").con("d")
        assertEquals("4 scelte", scelta.titolo)
        assertEquals(listOf("Preferiti", "In una raccolta"), scelta.dove)
    }

    @Test
    fun `si toglie quello che si era scelto`() {
        val scelta = MentreSiSceglie().con("a").con("b").senza("a")
        assertEquals("1 scelta", scelta.titolo)
        assertFalse(scelta.scelte.contains("a"))
    }

    @Test
    fun `tutte prende il giorno e ritoccandolo lo lascia`() {
        val giorno = listOf("a", "b", "c")
        val presa = MentreSiSceglie().tutteDelGiorno(giorno)
        assertEquals("3 scelte", presa.titolo)
        assertTrue(presa.tuttoIlGiorno(giorno))

        val lasciata = presa.tutteDelGiorno(giorno)
        assertEquals("Scegli", lasciata.titolo)
        assertFalse(lasciata.tuttoIlGiorno(giorno))
    }

    @Test
    fun `tutte non tocca quello che era scelto in altri giorni`() {
        val scelta = MentreSiSceglie().con("altrove").tutteDelGiorno(listOf("a", "b"))
        assertEquals("3 scelte", scelta.titolo)
        assertTrue(scelta.scelte.contains("altrove"))
        assertFalse(scelta.tuttoIlGiorno(emptyList()))
    }
}
