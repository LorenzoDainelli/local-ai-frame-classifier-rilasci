package visore.telefono

import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertNull
import kotlin.test.assertTrue

class AperturaTest {

    @Test
    fun `in cima si legge cosa si sta per aprire`() {
        val schermata = SchermataDiApertura.componi(28740, "2026-03-12")
        assertEquals("Visore", schermata.titolo)
        assertEquals("28.740 scatti, copiati il 12 marzo", schermata.riga)
    }

    @Test
    fun `senza la data del travaso resta il conto`() {
        assertEquals("28.740 scatti", SchermataDiApertura.componi(28740).riga)
        assertEquals("1 scatto", SchermataDiApertura.componi(1).riga)
    }

    @Test
    fun `la riga della firma c'e' solo dove qualcosa scade`() {
        assertNull(SchermataDiApertura.componi(10).firma)
        assertEquals(
            "Firma valida ancora 4 giorni",
            SchermataDiApertura.componi(10, firma = Firma(4)).firma?.frase)
    }

    @Test
    fun `l'ultimo giorno e il giorno dopo si dicono per intero`() {
        assertEquals("Firma valida ancora 1 giorno", Firma(1).frase)
        assertFalse(Firma(1).scaduta)
        assertEquals("Firma scaduta: va rinnovata dal computer.", Firma(0).frase)
        assertTrue(Firma(0).scaduta)
        assertTrue(Firma(-3).scaduta)
        assertEquals("Firma scaduta: va rinnovata dal computer.", Firma(-3).frase)
    }

    @Test
    fun `all'inizio il tasto e' acceso e dice solo Apri`() {
        val tasto = TastoApri()
        assertTrue(tasto.acceso)
        assertEquals("Apri", tasto.scritta)
        assertNull(tasto.avviso)
    }

    @Test
    fun `l'attesa raddoppia a ogni errore e sta dentro il tasto`() {
        var tasto = TastoApri().sbagliata()
        assertEquals("Password sbagliata.", tasto.avviso)
        assertFalse(tasto.acceso)
        assertEquals("Apri · 1", tasto.scritta)

        tasto = tasto.sbagliata()
        assertEquals("Apri · 2", tasto.scritta)
        tasto = tasto.sbagliata()
        assertEquals("Apri · 4", tasto.scritta)
        tasto = tasto.sbagliata()
        assertEquals("Apri · 8", tasto.scritta)
    }

    @Test
    fun `l'attesa scende un secondo per volta e il tasto torna acceso`() {
        var tasto = TastoApri().sbagliata().sbagliata()
        assertEquals(2, tasto.restano)
        tasto = tasto.unSecondo()
        assertEquals("Apri · 1", tasto.scritta)
        tasto = tasto.unSecondo()
        assertTrue(tasto.acceso)
        assertEquals("Apri", tasto.scritta)
        assertEquals(0, tasto.unSecondo().restano)
        assertEquals("Password sbagliata.", tasto.avviso)
    }

    @Test
    fun `il riempimento va da zero a uno mentre l'attesa scende`() {
        val tasto = TastoApri().sbagliata().sbagliata()
        assertEquals(0.0, tasto.riempimento)
        assertEquals(0.5, tasto.unSecondo().riempimento)
        assertEquals(1.0, tasto.unSecondo().unSecondo().riempimento)
        assertEquals(1.0, TastoApri().riempimento)
    }

    @Test
    fun `i due guai hanno due pesi diversi`() {
        assertEquals("Il pacchetto non si apre", QuandoVaMale.nonSiApre[0])
        assertTrue(QuandoVaMale.nonSiApre[1].contains("col cavo"))
        for (frase in QuandoVaMale.nonSiApre + QuandoVaMale.aMeta) {
            assertFalse(frase.lowercase().contains("riprova"))
        }
        assertTrue(QuandoVaMale.aMeta.contains("Si continua con quello che c'e'."))
    }
}
