package visore.app

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import visore.telefono.DoveIlCuore
import visore.telefono.Etichetta
import visore.telefono.FotoAperta
import visore.telefono.Informazioni

@Composable
fun SchermoDellaFotoAperta(
    foto: FotoAperta,
    informazioni: Informazioni,
    modifier: Modifier = Modifier,
    toccata: () -> Unit = {},
    chiudi: () -> Unit = {},
) {
    Box(modifier = modifier.fillMaxSize().background(Colori.fondo)) {
        Box(
            Modifier
                .fillMaxSize()
                .clickable(onClick = toccata),
            contentAlignment = Alignment.Center,
        ) {
            foto.frase?.let {

                Text(it, color = Colori.attenuato, fontSize = 14.sp)
            }
        }

        if (foto.segnoLive) {
            Text(
                FotoAperta.SEGNO_LIVE,
                color = Colori.ink,
                fontSize = 11.sp,
                modifier = Modifier
                    .align(Alignment.TopStart)
                    .padding(16.dp)
                    .clip(RoundedCornerShape(4.dp))
                    .background(Colori.superficie)
                    .padding(horizontal = 6.dp, vertical = 3.dp),
            )
        }

        if (foto.comandiAlzati) {
            BarraInCima(
                cuoreQui = foto.cuore == DoveIlCuore.IN_ALTO_A_DESTRA,
                chiudi = chiudi,
                modifier = Modifier.align(Alignment.TopCenter),
            )
            LeInformazioni(
                informazioni = informazioni,
                cuoreQui = foto.cuore == DoveIlCuore.BARRA_IN_BASSO,
                modifier = Modifier.align(Alignment.BottomCenter),
            )
        }
    }
}

@Composable
private fun BarraInCima(cuoreQui: Boolean, chiudi: () -> Unit, modifier: Modifier = Modifier) {
    Row(
        modifier = modifier
            .fillMaxWidth()
            .background(Colori.superficie)
            .padding(horizontal = 16.dp, vertical = 12.dp),
        horizontalArrangement = Arrangement.SpaceBetween,
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Text("<", color = Colori.ink, fontSize = 18.sp, modifier = Modifier.clickable(onClick = chiudi))
        if (cuoreQui) {
            Text(FotoAperta.CUORE, color = Colori.attenuato, fontSize = 13.sp)
        }
    }
}

@Composable
private fun LeInformazioni(
    informazioni: Informazioni,
    cuoreQui: Boolean,
    modifier: Modifier = Modifier,
) {
    Column(
        modifier = modifier
            .fillMaxWidth()
            .background(Colori.superficie)
            .padding(horizontal = 16.dp, vertical = 14.dp),
        verticalArrangement = Arrangement.spacedBy(6.dp),
    ) {
        informazioni.quando?.let { Text(it, color = Colori.ink, fontSize = 15.sp) }
        informazioni.riga?.let { Text(it, color = Colori.attenuato, fontSize = 12.sp) }

        Pillole(informazioni.nodi)
        Pillole(informazioni.persone)

        informazioni.notaScritta?.let {
            Text(it, color = Colori.attenuato, fontSize = 13.sp)
        }

        if (cuoreQui) {
            Text(
                FotoAperta.CUORE,
                color = Colori.attenuato,
                fontSize = 13.sp,
                modifier = Modifier.padding(top = 4.dp),
            )
        }
    }
}

@OptIn(ExperimentalLayoutApi::class)
@Composable
private fun Pillole(etichette: List<Etichetta>) {
    if (etichette.isEmpty()) {
        return
    }
    FlowRow(
        horizontalArrangement = Arrangement.spacedBy(6.dp),
        verticalArrangement = Arrangement.spacedBy(6.dp),
    ) {
        for (etichetta in etichette) {
            Pillola(etichetta.scritta)
        }
    }
}
