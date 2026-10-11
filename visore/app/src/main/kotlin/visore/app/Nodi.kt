package visore.app

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.grid.GridCells
import androidx.compose.foundation.lazy.grid.LazyVerticalGrid
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import visore.telefono.Piano
import visore.telefono.RigaDelNodo
import visore.telefono.SchermataDeiGiorni
import visore.telefono.Sezione

@Composable
fun SchermoDeiNodi(
    piano: Piano,
    modifier: Modifier = Modifier,
    scendi: (RigaDelNodo) -> Unit = {},
    torna: () -> Unit = {},
    apriIlMenu: () -> Unit = {},
) {
    Column(modifier = modifier.background(Colori.fondo)) {
        Testa(
            titolo = piano.titolo,
            indietro = if (piano.siTorna) torna else null,
            comando = if (piano.trePuntiVuoto) null else "...",
            premuto = apriIlMenu,
        )

        if (piano.dentro == null) {
            ElencoDeiRami(piano.figli, scendi, Modifier.weight(1f))
        } else {
            PilloleDeiFigli(piano.pillole)
            piano.cosaSiGuarda?.let { CosaSiGuarda(it) }
            MosaicoDelRamo(piano.quante, Modifier.weight(1f))
        }

        BarraDelleSezioni(Sezione.NODI)
    }
}

@Composable
private fun ElencoDeiRami(
    rami: List<RigaDelNodo>,
    scendi: (RigaDelNodo) -> Unit,
    modifier: Modifier = Modifier,
) {
    LazyColumn(modifier = modifier.padding(horizontal = 12.dp)) {
        items(rami) { riga ->
            Column(Modifier.clickable { scendi(riga) }) {
                Row(
                    modifier = Modifier.fillMaxWidth().padding(vertical = 12.dp),
                    verticalAlignment = Alignment.CenterVertically,
                    horizontalArrangement = Arrangement.spacedBy(12.dp),
                ) {
                    Box(
                        Modifier
                            .size(44.dp)
                            .clip(RoundedCornerShape(8.dp))
                            .background(Colori.superficieAlta),
                    )
                    Column(Modifier.weight(1f)) {
                        Text(riga.nome, color = Colori.ink, fontSize = 15.sp)
                        Text(riga.sottotitolo, color = Colori.tenue, fontSize = 12.sp)
                    }
                    if (riga.siScende) {
                        Text(">", color = Colori.tenue, fontSize = 14.sp)
                    }
                }
                Box(Modifier.fillMaxWidth().height(1.dp).background(Colori.linea))
            }
        }
    }
}

@Composable
private fun PilloleDeiFigli(pillole: List<String>) {
    if (pillole.isEmpty()) {
        return
    }
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .horizontalScroll(rememberScrollState())
            .padding(horizontal = 12.dp, vertical = 4.dp),
        horizontalArrangement = Arrangement.spacedBy(8.dp),
    ) {
        for (scritta in pillole) {
            Pillola(scritta)
        }
    }
}

@Composable
private fun CosaSiGuarda(frase: String) {
    Text(
        text = frase,
        color = Colori.attenuato,
        fontSize = 13.sp,
        modifier = Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 8.dp),
    )
}

@Composable
private fun MosaicoDelRamo(quante: Int, modifier: Modifier = Modifier) {
    LazyVerticalGrid(
        columns = GridCells.Fixed(SchermataDeiGiorni.COLONNE),
        horizontalArrangement = Arrangement.spacedBy(2.dp),
        verticalArrangement = Arrangement.spacedBy(2.dp),
        modifier = modifier,
    ) {
        items(quante) { quanti -> Miniatura(quanti) }
    }
}
