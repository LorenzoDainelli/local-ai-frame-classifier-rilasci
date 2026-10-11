package visore.app

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.aspectRatio
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.lazy.grid.GridCells
import androidx.compose.foundation.lazy.grid.LazyVerticalGrid
import androidx.compose.foundation.lazy.grid.items
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import visore.telefono.DentroUnaPersona
import visore.telefono.InsiemeA
import visore.telefono.Persona
import visore.telefono.SchermataDeiGiorni
import visore.telefono.SchermataDellePersone
import visore.telefono.Sezione

@Composable
fun SchermoDellePersone(
    schermata: SchermataDellePersone,
    modifier: Modifier = Modifier,
    apri: (Persona) -> Unit = {},
) {
    Column(modifier = modifier.background(Colori.fondo)) {
        Testa(titolo = SchermataDellePersone.SEZIONE)

        if (schermata.vuota) {
            NessunNome(schermata.frasePerIlVuoto, Modifier.weight(1f))
        } else {
            LazyVerticalGrid(
                columns = GridCells.Fixed(schermata.colonne),
                horizontalArrangement = Arrangement.spacedBy(10.dp),
                verticalArrangement = Arrangement.spacedBy(16.dp),
                modifier = Modifier.weight(1f).padding(horizontal = 12.dp),
            ) {
                items(schermata.persone) { persona ->
                    Faccia(persona, Modifier.clickable { apri(persona) })
                }
            }
        }

        BarraDelleSezioni(Sezione.PERSONE)
    }
}

@Composable
private fun Faccia(persona: Persona, modifier: Modifier = Modifier) {
    Column(modifier = modifier, horizontalAlignment = Alignment.CenterHorizontally) {
        Box(
            Modifier
                .fillMaxWidth()
                .aspectRatio(1f)
                .clip(RoundedCornerShape(12.dp))
                .background(Colori.superficieAlta),
        )
        for ((quante, riga) in persona.sottoLaFaccia.withIndex()) {
            Text(
                riga,
                color = if (quante == 0) Colori.ink else Colori.tenue,
                fontSize = if (quante == 0) 13.sp else 11.sp,
                textAlign = TextAlign.Center,
                modifier = Modifier.padding(top = if (quante == 0) 6.dp else 1.dp),
            )
        }
    }
}

@Composable
fun SchermoDiUnaPersona(
    dentro: DentroUnaPersona,
    modifier: Modifier = Modifier,
    torna: () -> Unit = {},
    stringiA: (InsiemeA) -> Unit = {},
    allarga: () -> Unit = {},
) {
    Column(modifier = modifier.background(Colori.fondo)) {
        Row(
            modifier = Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 10.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Text(
                "<",
                color = Colori.ink,
                fontSize = 18.sp,
                modifier = Modifier.clickable(onClick = torna).padding(end = 10.dp),
            )

            repeat(dentro.facce.size) {
                Box(
                    Modifier
                        .padding(end = 6.dp)
                        .size(30.dp)
                        .clip(CircleShape)
                        .background(Colori.superficieAlta),
                )
            }
            Column(Modifier.weight(1f).padding(start = 10.dp)) {
                Text(dentro.titolo, color = Colori.ink, fontSize = 17.sp)
                Text(dentro.sottotitolo, color = Colori.tenue, fontSize = 12.sp)
            }
            if (dentro.crocetta) {
                Text(
                    "×",
                    color = Colori.attenuato,
                    fontSize = 20.sp,
                    modifier = Modifier.clickable(onClick = allarga).padding(start = 10.dp),
                )
            }
        }

        if (dentro.mostraLaRiga) {
            SpessoInsiemeA(dentro.insieme, stringiA)
        }

        LazyVerticalGrid(
            columns = GridCells.Fixed(SchermataDeiGiorni.COLONNE),
            horizontalArrangement = Arrangement.spacedBy(2.dp),
            verticalArrangement = Arrangement.spacedBy(2.dp),
            modifier = Modifier.weight(1f),
        ) {
            items(dentro.quante) { quanti -> Miniatura(quanti) }
        }

        BarraDelleSezioni(Sezione.PERSONE)
    }
}

@Composable
private fun SpessoInsiemeA(insieme: List<InsiemeA>, stringiA: (InsiemeA) -> Unit) {
    Column(Modifier.padding(horizontal = 16.dp, vertical = 4.dp)) {
        Text(InsiemeA.TITOLO, color = Colori.tenue, fontSize = 11.sp)
        Row(
            modifier = Modifier.fillMaxWidth().padding(top = 8.dp, bottom = 8.dp),
            horizontalArrangement = Arrangement.spacedBy(14.dp),
        ) {
            for (altra in insieme) {
                Column(
                    modifier = Modifier.clickable { stringiA(altra) },
                    horizontalAlignment = Alignment.CenterHorizontally,
                ) {
                    Box(
                        Modifier
                            .size(44.dp)
                            .clip(CircleShape)
                            .background(Colori.superficieAlta),
                    )
                    Text(
                        altra.persona.nome,
                        color = Colori.attenuato,
                        fontSize = 11.sp,
                        modifier = Modifier.padding(top = 4.dp),
                    )
                    Text(altra.sotto, color = Colori.tenue, fontSize = 10.sp)
                }
            }
        }
    }
}

@Composable
private fun NessunNome(frase: String, modifier: Modifier = Modifier) {
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
