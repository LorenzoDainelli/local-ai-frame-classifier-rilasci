package visore.app

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.aspectRatio
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import visore.telefono.Sezione

@Composable
fun BarraDelleSezioni(qui: Sezione, modifier: Modifier = Modifier) {
    Row(
        modifier = modifier
            .fillMaxWidth()
            .background(Colori.superficie)
            .padding(vertical = 10.dp),
        horizontalArrangement = Arrangement.SpaceEvenly,
    ) {
        for (sezione in Sezione.entries) {
            Text(
                sezione.comeSiChiama,
                color = if (sezione == qui) Colori.ink else Colori.tenue,
                fontSize = 11.sp,
            )
        }
    }
}

@Composable
fun Testa(
    titolo: String,
    modifier: Modifier = Modifier,
    indietro: (() -> Unit)? = null,
    comando: String? = null,
    premuto: (() -> Unit)? = null,
) {
    Row(
        modifier = modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 10.dp),
        horizontalArrangement = Arrangement.SpaceBetween,
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            if (indietro != null) {
                Text(
                    "<",
                    color = Colori.ink,
                    fontSize = 18.sp,
                    modifier = Modifier
                        .clickable(onClick = indietro)
                        .padding(end = 10.dp),
                )
            }
            Text(
                titolo,
                color = Colori.ink,
                fontSize = if (indietro == null) 22.sp else 18.sp,
                fontWeight = FontWeight.SemiBold,
            )
        }
        if (comando != null) {
            Text(
                comando,
                color = Colori.attenuato,
                fontSize = 15.sp,
                modifier = if (premuto == null) Modifier else Modifier.clickable(onClick = premuto),
            )
        }
    }
}

@Composable
fun Miniatura(quante: Int, modifier: Modifier = Modifier) {
    Box(
        modifier
            .fillMaxWidth()
            .aspectRatio(1f)
            .background(if (quante % 2 == 0) Colori.superficieAlta else Colori.superficieChiara),
    )
}

@Composable
fun Pillola(
    scritta: String,
    modifier: Modifier = Modifier,
    accesa: Boolean = false,
    premuta: (() -> Unit)? = null,
) {
    Text(
        text = scritta,
        color = if (accesa) Colori.suFill else Colori.attenuato,
        fontSize = 13.sp,
        modifier = modifier
            .clip(RoundedCornerShape(100.dp))
            .background(if (accesa) Colori.fill else Colori.superficie)
            .then(if (premuta == null) Modifier else Modifier.clickable(onClick = premuta))
            .padding(horizontal = 12.dp, vertical = 7.dp),
    )
}
