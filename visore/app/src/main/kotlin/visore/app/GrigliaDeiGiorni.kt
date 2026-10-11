package visore.app

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.grid.GridCells
import androidx.compose.foundation.lazy.grid.GridItemSpan
import androidx.compose.foundation.lazy.grid.LazyVerticalGrid
import androidx.compose.foundation.lazy.grid.items
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import visore.telefono.Gruppo
import visore.telefono.MentreSiSceglie
import visore.telefono.SchermataDeiGiorni
import visore.telefono.Sezione

@Composable
fun GrigliaDeiGiorni(schermata: SchermataDeiGiorni, modifier: Modifier = Modifier) {
    Column(modifier = modifier.fillMaxSize().background(Colori.fondo)) {
        Testa(titolo = Sezione.FOTO.comeSiChiama, comando = MentreSiSceglie().titolo)
        schermata.cima.frase?.let { RigaAvviso(it) }
        RigaAvviso(schermata.cima.porta)

        if (schermata.vuota) {
            NienteAncora(schermata.frasePerIlVuoto, Modifier.weight(1f))
        } else {
            Box(Modifier.weight(1f)) {
                Mosaico(schermata)
                BarraDegliAnni(schermata.anni, Modifier.align(Alignment.CenterEnd))
            }
        }

        BarraDelleSezioni(Sezione.FOTO)
    }
}

@Composable
private fun RigaAvviso(frase: String) {
    Text(
        text = frase,
        color = Colori.attenuato,
        fontSize = 13.sp,
        modifier = Modifier
            .fillMaxWidth()
            .background(Colori.superficie)
            .padding(horizontal = 16.dp, vertical = 9.dp),
    )
}

@Composable
private fun Mosaico(schermata: SchermataDeiGiorni) {
    LazyVerticalGrid(
        columns = GridCells.Fixed(schermata.colonne),
        horizontalArrangement = Arrangement.spacedBy(2.dp),
        verticalArrangement = Arrangement.spacedBy(2.dp),
    ) {
        for (gruppo in schermata.gruppi) {
            item(span = { GridItemSpan(maxLineSpan) }) {
                IntestazioneDelGiorno(gruppo)
            }
            items(gruppo.quanti) { quante ->
                Miniatura(quante)
            }
        }
    }
}

@Composable
private fun IntestazioneDelGiorno(gruppo: Gruppo) {
    val intestazione = gruppo.intestazione
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .background(Colori.fondo)
            .padding(start = 16.dp, end = 16.dp, top = 18.dp, bottom = 8.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        if (intestazione.righe == 2) {
            Column(Modifier.weight(1f)) {
                Text(
                    intestazione.sinistra,
                    color = Colori.ink,
                    fontSize = 20.sp,
                    fontWeight = FontWeight.SemiBold,
                )
                Text(intestazione.secondaria, color = Colori.attenuato, fontSize = 12.sp)
            }
        } else {
            Text(
                intestazione.sinistra,
                color = Colori.ink,
                fontSize = 15.sp,
                fontWeight = FontWeight.Medium,
                modifier = Modifier.weight(1f),
            )
            Text(intestazione.secondaria, color = Colori.attenuato, fontSize = 12.sp)
        }
        if (intestazione.trePunti) {
            Text("...", color = Colori.attenuato, fontSize = 15.sp)
        }
    }
}

@Composable
private fun BarraDegliAnni(anni: List<String>, modifier: Modifier = Modifier) {
    Column(
        modifier = modifier.padding(end = 3.dp),
        horizontalAlignment = Alignment.End,
        verticalArrangement = Arrangement.spacedBy(10.dp),
    ) {
        for (anno in anni) {
            Text(anno, color = Colori.tenue, fontSize = 10.sp)
        }
    }
}

@Composable
private fun NienteAncora(frase: String, modifier: Modifier = Modifier) {
    Box(modifier.fillMaxWidth(), contentAlignment = Alignment.Center) {
        Text(
            frase,
            color = Colori.attenuato,
            fontSize = 14.sp,
            modifier = Modifier.padding(horizontal = 40.dp),
        )
    }
}
