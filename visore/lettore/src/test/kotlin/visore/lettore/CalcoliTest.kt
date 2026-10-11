package visore.lettore

import kotlin.test.Test
import kotlin.test.assertEquals

class CalcoliTest {

    @Test
    fun `scrypt da' i numeri del documento`() {
        assertEquals(
            "77d6576238657b203b19ca42c18a0497f16b4844e3074ae8dfdffa3fede21442" +
                "fcd0069ded0948f8326a753a0fc81f17e8d3e0fb2e0d3628cf35e20c38d18906",
            esadecimale(Scrypt.deriva(ByteArray(0), ByteArray(0), 16, 1, 1, 64)),
        )
        assertEquals(
            "fdbabe1c9d3472007856e7190d01e9fe7c6ad7cbc8237830e77376634b373162" +
                "2eaf30d92e22a3886ff109279d9830dac727afb94a83ee6d8360cbdfa2cc0640",
            esadecimale(Scrypt.deriva("password".toByteArray(), "NaCl".toByteArray(),
                1024, 8, 16, 64)),
        )
        assertEquals(
            "7023bdcb3afd7348461c06cd81fd38ebfda8fbba904f8e3ea9b543f6545da1f2" +
                "d5432955613f0fcf62d49705242a9af9e61e85dc0d651e40dfcf017b45575887",
            esadecimale(Scrypt.deriva("pleaseletmein".toByteArray(),
                "SodiumChloride".toByteArray(), 16384, 8, 1, 64)),
        )
    }

    @Test
    fun `scrypt coi parametri del pacchetto e' lento ma non troppo`() {
        val prima = System.nanoTime()
        val chiave = Scrypt.deriva("tre parole che ricordi".toByteArray(),
            ByteArray(16) { it.toByte() }, 32768, 8, 1, 32)
        val secondi = (System.nanoTime() - prima) / 1e9
        assertEquals(32, chiave.size)
        assert(secondi < 5.0) { "scrypt ha messo $secondi secondi" }
    }

    @Test
    fun `blake2b da' i numeri del documento`() {
        assertEquals(
            "ba80a53f981c4d0d6a2797b69f12f6e94c212f14685ac4b74b12bb6fdbffa2d1" +
                "7d87c5392aab792dc252d5de4533cc9518d38aa8dbf1925ab92386edd4009923",
            Blake2b.scritta("abc".toByteArray(), 64),
        )
    }

    @Test
    fun `blake2b a trentadue byte e' quello che scrive il database`() {
        assertEquals(
            "0e5751c026e543b2e8ab2eb06099daa1d1e5df47778f7787faab45cdf12fe3a8",
            Blake2b.scritta(ByteArray(0)),
        )
        assertEquals(
            "bddd813c634239723171ef3fee98579b94964e3bb1cb3e427262c8c068d52319",
            Blake2b.scritta("abc".toByteArray()),
        )
    }

    @Test
    fun `blake2b non sbaglia sui confini dei blocchi`() {
        assertEquals(
            "c3582f71ebb2be66fa5dd750f80baae97554f3b015663c8be377cfcb2488c1d1",
            Blake2b.scritta(ByteArray(128) { it.toByte() }),
        )
        assertEquals(
            "39a7eb9fedc19aabc83425c6755dd90e6f9d0c804964a1f4aaeea3b9fb599835",
            Blake2b.scritta(ByteArray(256) { (it % 256).toByte() }),
        )
        assertEquals(
            "91ccce0ba9e15867934e70e07d8d4af1270ec75748be56a3f48f5bc8b6c3967d",
            Blake2b.scritta(ByteArray(300) { ((it * 7) % 256).toByte() }),
        )
    }

    @Test
    fun `blake2b a pezzi da' lo stesso numero`() {
        val dati = ByteArray(300) { ((it * 7) % 256).toByte() }
        val calcolo = Blake2b.Impronta()
        calcolo.aggiungi(dati, 0, 7)
        calcolo.aggiungi(dati, 7, 128)
        calcolo.aggiungi(dati, 128, 129)
        calcolo.aggiungi(dati, 129, 300)
        assertEquals(Blake2b.scritta(dati), Blake2b.inEsadecimale(calcolo.finisci()))
    }

    private fun esadecimale(byte: ByteArray) = Blake2b.inEsadecimale(byte)
}
