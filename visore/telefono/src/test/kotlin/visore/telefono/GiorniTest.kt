package visore.telefono

import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertNull
import kotlin.test.assertTrue
import visore.lettore.Giorno

class GiorniTest {

    private val giorni = listOf(
        Giorno("2026-03-14", 23, listOf("luogo_4")),
        Giorno("2026-03-11", 9, listOf("luogo_1")),
        Giorno("2023-08-02", 1, emptyList()),
        Giorno(null, 341, emptyList()),
    )

    @Test
    fun `i gruppi restano nell'ordine del lettore, coi senza data in fondo`() {
        val schermata = SchermataDeiGiorni.componi(giorni, Sistema.ANDROID)
        assertEquals(4, schermata.gruppi.size)
        assertEquals("14 marzo", schermata.gruppi[0].intestazione.data)
        assertTrue(schermata.gruppi.last().senzaData)
        assertEquals("Senza data", schermata.gruppi.last().intestazione.data)
        assertEquals(374, schermata.quante)
    }

    @Test
    fun `un pacchetto senza scatti si dice, non mostra una griglia vuota`() {
        assertTrue(SchermataDeiGiorni.componi(emptyList(), Sistema.IPHONE).vuota)
        assertFalse(SchermataDeiGiorni.componi(giorni, Sistema.IPHONE).vuota)
    }

    @Test
    fun `le colonne sono tre, e sono tre su tutti e due i telefoni`() {
        assertEquals(3, SchermataDeiGiorni.componi(giorni, Sistema.IPHONE).colonne)
        assertEquals(3, SchermataDeiGiorni.componi(giorni, Sistema.ANDROID).colonne)
    }

    @Test
    fun `gli anni si contano una volta sola`() {
        val schermata = SchermataDeiGiorni.componi(giorni, Sistema.ANDROID)
        assertEquals(listOf("2026", "2023"), schermata.anni)
    }

    @Test
    fun `su iPhone l'intestazione costa due righe e ha i tre punti`() {
        val prima = SchermataDeiGiorni.componi(giorni, Sistema.IPHONE)
            .gruppi[0].intestazione
        assertEquals(2, prima.righe)
        assertTrue(prima.trePunti)
        assertEquals("14 marzo", prima.sinistra)
        assertEquals("luogo_4 · 23 scatti", prima.secondaria)
    }

    @Test
    fun `sul Redmi l'intestazione e' una riga sola e senza tre punti`() {
        val prima = SchermataDeiGiorni.componi(giorni, Sistema.ANDROID)
            .gruppi[0].intestazione
        assertEquals(1, prima.righe)
        assertFalse(prima.trePunti)
        assertEquals("14 marzo", prima.sinistra)
        assertEquals("luogo_4 · 23", prima.secondaria)
    }

    @Test
    fun `senza luogo resta il numero`() {
        val schermata = SchermataDeiGiorni.componi(giorni, Sistema.IPHONE)
        assertEquals("1 scatto", schermata.gruppi[2].intestazione.secondaria)
        assertEquals("341 scatti", schermata.gruppi[3].intestazione.secondaria)
    }

    @Test
    fun `con zero foto nuove la riga in cima non c'e'`() {
        val schermata = SchermataDeiGiorni.componi(giorni, Sistema.ANDROID)
        assertNull(schermata.cima.frase)
    }

    @Test
    fun `la riga del travaso dice quante e come si scrivono`() {
        val tante = SchermataDeiGiorni.componi(
            giorni, Sistema.ANDROID, nuove = 1204, preferitiERaccolte = 212)
        assertEquals("1.204 foto nuove con l'ultimo travaso", tante.cima.frase)
        assertEquals("Preferiti e raccolte · 212", tante.cima.porta)

        val una = SchermataDeiGiorni.componi(giorni, Sistema.ANDROID, nuove = 1)
        assertEquals("1 foto nuova con l'ultimo travaso", una.cima.frase)
    }

    @Test
    fun `le date diventano giorno e mese`() {
        assertEquals("14 marzo", inItaliano("2026-03-14"))
        assertEquals("1 gennaio", inItaliano("2026-01-01"))
        assertEquals("31 dicembre", inItaliano("2011-12-31"))
    }

    @Test
    fun `una data storta non diventa un'altra data`() {
        for (storta in listOf("2026-13-14", "2026-03", "domani", "")) {
            assertEquals(storta, inItaliano(storta))
        }
    }

    @Test
    fun `le migliaia si scrivono col punto`() {
        assertEquals("0", numero(0))
        assertEquals("23", numero(23))
        assertEquals("341", numero(341))
        assertEquals("1.204", numero(1204))
        assertEquals("12.345", numero(12345))
        assertEquals("1.234.567", numero(1234567))
    }
}
