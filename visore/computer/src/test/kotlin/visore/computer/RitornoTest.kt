package visore.computer

import java.io.File
import kotlin.test.AfterTest
import kotlin.test.BeforeTest
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFailsWith
import kotlin.test.assertFalse
import kotlin.test.assertNotNull
import kotlin.test.assertNull
import kotlin.test.assertTrue
import visore.lettore.FIRMA
import visore.lettore.Pacchetto
import visore.lettore.PasswordSbagliata
import visore.lettore.Ritorno
import visore.lettore.dentro

class RitornoTest {

    private lateinit var cartella: File

    @BeforeTest
    fun prima() {
        cartella = PacchettoDiProva.apparecchia()
    }

    @AfterTest
    fun dopo() {
        cartella.deleteRecursively()
    }

    private fun apri(): Pacchetto =
        Pacchetto.apri(cartella, PacchettoDiProva.PAROLA, BancoInMemoria)

    private fun <T> colTelefono(cosa: (Pacchetto, Ritorno) -> T): T =
        apri().use { pacchetto ->
            Ritorno.apri(pacchetto, BancoDaScrivereInMemoria).use { ritorno ->
                cosa(pacchetto, ritorno)
            }
        }

    private fun ilFile(): File = dentro(cartella, "ritorno.db")

    private fun senzaCuore(pacchetto: Pacchetto, ritorno: Ritorno): String =
        pacchetto.scatti().map { it.testo("impronta")!! }
            .first { !ritorno.haIlCuore(it) }

    @Test
    fun `un cuore messo si ritrova riaprendo l'app`() {
        val quale = colTelefono { pacchetto, ritorno ->
            val impronta = senzaCuore(pacchetto, ritorno)
            ritorno.metti(impronta)
            assertTrue(ritorno.haIlCuore(impronta))
            impronta
        }
        colTelefono { _, ritorno ->
            assertTrue(ritorno.haIlCuore(quale), "il cuore doveva restare")
        }
    }

    @Test
    fun `rimettere un cuore non cambia quando era stato messo`() {
        colTelefono { pacchetto, ritorno ->
            val impronta = senzaCuore(pacchetto, ritorno)
            ritorno.metti(impronta, "2021-06-01T08:00:00Z")
            ritorno.metti(impronta, "2026-01-01T08:00:00Z")
            val cuore = ritorno.cuori().first { it.impronta == impronta }
            assertEquals("2021-06-01T08:00:00Z", cuore.messoIl)
        }
    }

    @Test
    fun `toglierlo lo toglie davvero — qui il telefono e' padrone di casa`() {
        val quale = colTelefono { pacchetto, ritorno ->
            val impronta = senzaCuore(pacchetto, ritorno)
            ritorno.metti(impronta)
            ritorno.togli(impronta)
            impronta
        }
        colTelefono { _, ritorno -> assertFalse(ritorno.haIlCuore(quale)) }
    }

    @Test
    fun `quello che il telefono scrive e' cifrato come tutto il resto`() {
        colTelefono { pacchetto, ritorno ->
            ritorno.metti(pacchetto.scatti().first().testo("impronta")!!)
        }
        val byte = ilFile().readBytes()
        assertTrue(byte.copyOf(FIRMA.size).contentEquals(FIRMA),
            "il ritorno deve avere la firma dei file del pacchetto")
        assertFalse(String(byte, Charsets.ISO_8859_1).contains("SQLite format 3"),
            "il database del telefono non deve stare in chiaro sul disco")
    }

    @Test
    fun `nessun file del pacchetto resta in chiaro, nemmeno a meta'`() {
        colTelefono { pacchetto, ritorno ->
            ritorno.metti(pacchetto.scatti().first().testo("impronta")!!)
            ritorno.nuovaRaccolta("una qualunque")
        }
        for (file in cartella.walkTopDown().filter { it.isFile }) {
            assertFalse(file.name.endsWith(".parziale"),
                "«${file.name}» e' rimasto a meta'")
            if (file.name == "visore.json") {
                continue
            }
            val inizio = file.readBytes().copyOf(FIRMA.size)
            assertTrue(inizio.contentEquals(FIRMA), "«${file.name}» non e' cifrato")
        }
    }

    @Test
    fun `con la password sbagliata il ritorno non si apre`() {
        colTelefono { pacchetto, ritorno ->
            ritorno.metti(pacchetto.scatti().first().testo("impronta")!!)
        }
        assertFailsWith<PasswordSbagliata> {
            Pacchetto.apri(cartella, "una password qualunque", BancoInMemoria)
        }
    }

    @Test
    fun `le raccolte si creano, si riempiono e si svuotano`() {
        val impronte = colTelefono { pacchetto, _ ->
            pacchetto.scatti().map { it.testo("impronta")!! }
        }
        val numero = colTelefono { _, ritorno ->
            val quale = ritorno.nuovaRaccolta("il mare del 2021")
            ritorno.mettiNellaRaccolta(quale, impronte[0])
            ritorno.mettiNellaRaccolta(quale, impronte[1])
            ritorno.mettiNellaRaccolta(quale, impronte[1])   // due volte: una sola riga
            quale
        }
        colTelefono { _, ritorno ->
            val raccolta = ritorno.raccolte().first { it.numero == numero }
            assertEquals("il mare del 2021", raccolta.nome)
            assertEquals(2, raccolta.impronte.size)

            ritorno.togliDallaRaccolta(numero, impronte[0])
            ritorno.rinominaRaccolta(numero, "il mare")
        }
        colTelefono { _, ritorno ->
            val raccolta = ritorno.raccolte().first { it.numero == numero }
            assertEquals("il mare", raccolta.nome)
            assertEquals(listOf(impronte[1]), raccolta.impronte)

            ritorno.buttaRaccolta(numero)
        }
        colTelefono { _, ritorno ->
            assertTrue(ritorno.raccolte().none { it.numero == numero })
        }
    }

    @Test
    fun `il diario si aggiunge, e la stessa apertura non raddoppia`() {
        colTelefono { _, ritorno ->
            ritorno.apertura("2026-08-30T21:14:02Z", 1980, 44.4939, 11.3427, 128)
            ritorno.apertura("2026-08-30T21:14:02Z", 9999, null, null, 1)
            ritorno.apertura("2026-08-28T18:03:41Z", 420, null, null, 22)
        }
        colTelefono { _, ritorno ->
            val righe = ritorno.diario()
            assertEquals(2, righe.size)
            assertEquals("2026-08-30T21:14:02Z", righe.first().apertoIl)
            assertEquals(1980L, righe.first().durataS)
            assertNull(righe.last().latitudine)
        }
    }

    @Test
    fun `un telefono senza niente di suo riprende dalla copia di scorta`() {
        assertFalse(ilFile().exists(), "il pacchetto di prova non ha un ritorno")

        colTelefono { pacchetto, ritorno ->
            val scorta = pacchetto.scorta()
            assertTrue(scorta.cuori.isNotEmpty(), "la scorta doveva avere dei cuori")
            assertEquals(scorta.cuori.map { it.impronta }.sorted(),
                ritorno.cuori().map { it.impronta }.sorted())
            assertEquals(scorta.cuori.first().messoIl,
                ritorno.cuori().first { it.impronta == scorta.cuori.first().impronta }
                    .messoIl)
            assertEquals(scorta.raccolte.map { it.nome }, ritorno.raccolte().map { it.nome })
            assertEquals(scorta.raccolte.first().impronte,
                ritorno.raccolte().first().impronte)
        }
        assertTrue(ilFile().isFile, "riprendendo dalla scorta il file si scrive")
    }

    @Test
    fun `i cuori tolti sul computer se ne vanno anche dal telefono`() {
        val tolta = colTelefono { pacchetto, _ ->
            pacchetto.scorta().tolti.first().impronta
        }
        colTelefono { _, ritorno ->
            ritorno.metti(tolta)
            assertTrue(ritorno.haIlCuore(tolta))
        }
        colTelefono { _, ritorno ->
            assertFalse(ritorno.haIlCuore(tolta),
                "il gesto fatto sul monitor grande deve vincere")
        }
    }

    @Test
    fun `un ritorno rovinato riparte dalla scorta e lo dice una volta sola`() {
        colTelefono { _, ritorno -> ritorno.nuovaRaccolta("questa si perde") }

        val byte = ilFile().readBytes()
        byte[byte.size - 1] = (byte[byte.size - 1].toInt() xor 0xff).toByte()
        ilFile().writeBytes(byte)

        colTelefono { pacchetto, ritorno ->
            assertNotNull(ritorno.guaio, "un guaio cosi' si dice")
            assertFalse(ritorno.guaio!!.contains("password"),
                "non e' la password: e' il file")
            assertEquals(pacchetto.scorta().cuori.size, ritorno.cuori().size)
            assertTrue(ritorno.raccolte().none { it.nome == "questa si perde" })
        }
        colTelefono { _, ritorno -> assertNull(ritorno.guaio) }
    }
}
