package visore.app

import android.os.Bundle
import android.view.WindowManager
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.compose.foundation.layout.WindowInsets
import androidx.compose.foundation.layout.systemBars
import androidx.compose.foundation.layout.windowInsetsPadding
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import visore.lettore.Giorno
import visore.telefono.SchermataDeiGiorni
import visore.telefono.SchermataDiApertura
import visore.telefono.Sistema

class Principale : ComponentActivity() {

    override fun onCreate(salvato: Bundle?) {
        super.onCreate(salvato)
        window.setFlags(WindowManager.LayoutParams.FLAG_SECURE,
            WindowManager.LayoutParams.FLAG_SECURE)
        setContent {
            var dentro by remember { mutableStateOf(false) }
            val bordi = Modifier.windowInsetsPadding(WindowInsets.systemBars)
            if (dentro) {
                GrigliaDeiGiorni(schermata = ARCHIVIO_FINTO, modifier = bordi)
            } else {
                SchermoDiApertura(
                    schermata = APERTURA_FINTA,
                    apri = { parola ->
                        val giusta = parola == PAROLA_FINTA
                        if (giusta) dentro = true
                        giusta
                    },
                    modifier = bordi,
                )
            }
        }
    }
}

private const val PAROLA_FINTA = "prova"

private val APERTURA_FINTA: SchermataDiApertura = SchermataDiApertura.componi(
    quantiScatti = 28740,
    copiatoIl = "2026-03-12",
    firma = null,
)

private val ARCHIVIO_FINTO: SchermataDeiGiorni = SchermataDeiGiorni.componi(
    giorni = listOf(
        Giorno("2026-03-14", 23, listOf("luogo_4")),
        Giorno("2026-03-11", 9, listOf("luogo_1")),
        Giorno("2026-02-28", 6, emptyList()),
        Giorno("2025-12-25", 41, listOf("luogo_2")),
        Giorno("2023-08-03", 12, listOf("luogo_7")),
        Giorno(null, 5, emptyList()),
    ),
    sistema = Sistema.ANDROID,
    nuove = 1204,
    preferitiERaccolte = 212,
)
