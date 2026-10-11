package visore.app

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.grid.GridCells
import androidx.compose.foundation.lazy.grid.GridItemSpan
import androidx.compose.foundation.lazy.grid.LazyVerticalGrid
import androidx.compose.foundation.lazy.grid.items
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import visore.telefono.RigaDellaRaccolta
import visore.telefono.SchermataDeiPreferiti
import visore.telefono.Sezione

@Composable
fun SchermoDeiPreferiti(
    schermata: SchermataDeiPreferiti,
    modifier: Modifier = Modifier,
    torna: () -> Unit = {},
) {
    Column(modifier = modifier.background(Colori.fondo)) {
        Testa(titolo = schermata.titolo, indietro = torna)

        if (schermata.vuota) {
            NienteDiSuo(schermata.frasePerIlVuoto, Modifier.weight(1f))
        } else {
            Contenuto(schermata, Modifier.weight(1f))
        }

        BarraDelleSezioni(Sezione.FOTO)
    }
}

@Composable
private fun Contenuto(schermata: SchermataDeiPreferiti, modifier: Modifier = Modifier) {
    LazyVerticalGrid(
        columns = GridCells.Fixed(schermata.colonne),
        horizontalArrangement = Arrangement.spacedBy(2.dp),
        verticalArrangement = Arrangement.spacedBy(2.dp),
        modifier = modifier,
    ) {
        item(span = { GridItemSpan(maxLineSpan) }) {
            Text(
                schermata.quante,
                color = Colori.attenuato,
                fontSize = 13.sp,
                modifier = Modifier.padding(horizontal = 16.dp, vertical = 8.dp),
            )
        }
        items(schermata.quantiCuori) { quanti -> Miniatura(quanti) }

        schermata.titoloDelleRaccolte?.let { titolo ->
            item(span = { GridItemSpan(maxLineSpan) }) {
                Text(
                    titolo,
                    color = Colori.tenue,
                    fontSize = 11.sp,
                    letterSpacing = 1.sp,
                    modifier = Modifier.padding(start = 16.dp, top = 24.dp, bottom = 6.dp),
                )
            }
            items(schermata.raccolte, span = { GridItemSpan(maxLineSpan) }) { raccolta ->
                RigaDiUnaRaccolta(raccolta)
            }
        }
    }
}

@Composable
private fun RigaDiUnaRaccolta(raccolta: RigaDellaRaccolta) {
    Column {
        Row(
            modifier = Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 12.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Column(Modifier.weight(1f)) {
                Text(raccolta.nome, color = Colori.ink, fontSize = 15.sp)
                Text(raccolta.sottotitolo, color = Colori.tenue, fontSize = 12.sp)
            }
            Text(">", color = Colori.tenue, fontSize = 14.sp)
        }
        Box(Modifier.fillMaxWidth().height(1.dp).background(Colori.linea))
    }
}

@Composable
private fun NienteDiSuo(frase: String, modifier: Modifier = Modifier) {
    Box(modifier.fillMaxWidth(), contentAlignment = Alignment.Center) {
        Text(
            frase,
            color = Colori.attenuato,
            fontSize = 14.sp,
            textAlign = TextAlign.Center,
            modifier = Modifier.padding(horizontal = 40.dp),
        )
    }
}
