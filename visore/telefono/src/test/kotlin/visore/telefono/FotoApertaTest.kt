package visore.telefono

import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertNull
import kotlin.test.assertTrue

class FotoApertaTest {

    @Test
    fun `sulle live il tocco e' l'assaggio, sulle altre sono i comandi`() {
        val live = FotoAperta(Genere.LIVE, Sistema.IPHONE)
        assertTrue(live.segnoLive)
        assertEquals(CosaFaIlTocco.ASSAGGIO, live.tocco)
        assertTrue(live.comandiSiChiamanoTrascinando)

        for (genere in listOf(Genere.FOTO, Genere.VIDEO)) {
            val altra = FotoAperta(genere, Sistema.IPHONE)
            assertFalse(altra.segnoLive)
            assertEquals(CosaFaIlTocco.COMANDI, altra.tocco)
            assertFalse(altra.comandiSiChiamanoTrascinando)
        }
    }

    @Test
    fun `il segno c'e' esattamente dove il tocco e' l'assaggio`() {
        for (genere in Genere.entries) {
            val foto = FotoAperta(genere, Sistema.ANDROID)
            assertEquals(foto.segnoLive, foto.tocco == CosaFaIlTocco.ASSAGGIO)
        }
    }

    @Test
    fun `sopra la foto non compare mai niente`() {
        for (genere in Genere.entries) {
            for (sistema in Sistema.entries) {
                assertFalse(FotoAperta(genere, sistema).qualcosaSopraLaFoto)
            }
        }
    }

    @Test
    fun `il cuore sta dove lo mette il sistema, e il doppio tocco resta`() {
        val iPhone = FotoAperta(Genere.FOTO, Sistema.IPHONE)
        val redmi = FotoAperta(Genere.FOTO, Sistema.ANDROID)
        assertEquals(DoveIlCuore.BARRA_IN_BASSO, iPhone.cuore)
        assertEquals(DoveIlCuore.IN_ALTO_A_DESTRA, redmi.cuore)
        assertTrue(iPhone.doppioTocco)
        assertTrue(redmi.doppioTocco)
    }

    @Test
    fun `una foto che non si apre lo dice piano`() {
        assertNull(FotoAperta(Genere.FOTO, Sistema.IPHONE).frase)
        assertEquals(
            "Questa foto non si apre.",
            FotoAperta(Genere.FOTO, Sistema.IPHONE, siApre = false).frase)
    }

    @Test
    fun `un genere che non si conosce si guarda come una foto`() {
        assertEquals(Genere.LIVE, Genere.di("live"))
        assertEquals(Genere.VIDEO, Genere.di("video"))
        assertEquals(Genere.FOTO, Genere.di("foto"))
        assertEquals(Genere.FOTO, Genere.di(null))
        assertEquals(Genere.FOTO, Genere.di("qualcosa-di-nuovo"))
    }

    private val informazioni = Informazioni(
        quando = "14 marzo 2019, 18:22",
        luogo = "luogo_4",
        latitudine = 44.4979,
        longitudine = 11.3426,
        nodi = listOf(Etichetta("nodo_3", "utente"), Etichetta("nodo_12", "sistema")),
        persone = listOf(Etichetta("persona_2", "a_mano")),
        nota = "la nota che avevo scritto sul PC",
    )

    @Test
    fun `il luogo porta le coordinate esatte`() {
        assertEquals("luogo_4 · 44.4979, 11.3426", informazioni.riga)
    }

    @Test
    fun `senza luogo restano le coordinate, senza niente non c'e' la riga`() {
        assertEquals(
            "44.4979, 11.3426",
            Informazioni(null, null, 44.4979, 11.3426, emptyList(), emptyList(), null).riga)
        assertNull(
            Informazioni(null, null, null, null, emptyList(), emptyList(), null).riga)
    }

    @Test
    fun `quello che ha detto il programma resta riconoscibile`() {
        assertEquals("nodo_3", informazioni.nodi[0].scritta)
        assertEquals("nodo_12 · dal programma", informazioni.nodi[1].scritta)
        assertEquals("persona_2 · detto da te", informazioni.persone[0].scritta)
        assertEquals("dal programma", Etichetta("persona_9", "volto").segno)
    }

    @Test
    fun `la nota si legge fra virgolette`() {
        assertEquals("«la nota che avevo scritto sul PC»", informazioni.notaScritta)
        assertNull(informazioni.let { Informazioni(null, null, null, null,
            emptyList(), emptyList(), "   ") }.notaScritta)
    }

    @Test
    fun `le coordinate si scrivono con quattro decimali`() {
        assertEquals("44.4979", coordinata(44.4979))
        assertEquals("11.3426", coordinata(11.3426))
        assertEquals("0.0000", coordinata(0.0))
        assertEquals("−11.3426", coordinata(-11.3426))
        assertEquals("9.1000", coordinata(9.1))
    }
}
