package visore.telefono

import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse

class SezioniTest {

    @Test
    fun `le sezioni sono quattro e si aprono da Foto`() {
        assertEquals(4, Sezione.quante)
        assertEquals(listOf("Foto", "Nodi", "Persone", "Cerca"),
            Sezione.entries.map { it.comeSiChiama })
        assertEquals(Sezione.FOTO, Sezione.PRIMA)
    }

    @Test
    fun `preferiti non e' una sezione`() {
        assertFalse(Sezione.entries.any {
            it.comeSiChiama.contains("Preferiti") || it.comeSiChiama.contains("Raccolte")
        })
    }
}
