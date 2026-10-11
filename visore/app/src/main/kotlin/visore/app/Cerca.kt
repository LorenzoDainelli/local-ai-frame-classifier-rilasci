package visore.app

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.BasicTextField
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.SolidColor
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import visore.telefono.GruppoTrovato
import visore.telefono.SchermataDiRicerca
import visore.telefono.Sezione

@Composable
fun SchermoDiRicerca(
    schermata: SchermataDiRicerca,
    nonNelVocabolario: List<String>,
    modifier: Modifier = Modifier,
    scritto: (String) -> Unit = {},
    apri: (GruppoTrovato, String) -> Unit = { _, _ -> },
) {
    Column(modifier = modifier.background(Colori.fondo)) {
        Testa(titolo = SchermataDiRicerca.SEZIONE)
        Campo(schermata.scritto, scritto)
        schermata.riga?.let { RigaDelCosaCerco(it) }

        val perche = schermata.perche(nonNelVocabolario)
        if (perche != null) {
            IlVuoto(perche, Modifier.weight(1f))
        } else {
            Risultati(schermata.gruppi, apri, Modifier.weight(1f))
        }

        BarraDelleSezioni(Sezione.CERCA)
    }
}

@Composable
private fun Campo(scritto: String, cambiato: (String) -> Unit) {
    Box(
        Modifier
            .fillMaxWidth()
            .padding(horizontal = 16.dp)
            .clip(RoundedCornerShape(8.dp))
            .background(Colori.superficie)
            .padding(horizontal = 14.dp, vertical = 11.dp),
    ) {
        if (scritto.isEmpty()) {
            Text(SchermataDiRicerca.INVITO, color = Colori.tenue, fontSize = 15.sp)
        }
        BasicTextField(
            value = scritto,
            onValueChange = cambiato,
            singleLine = true,
            textStyle = TextStyle(color = Colori.ink, fontSize = 15.sp),
            cursorBrush = SolidColor(Colori.ink),
            modifier = Modifier.fillMaxWidth(),
        )
    }
}

@Composable
private fun RigaDelCosaCerco(riga: String) {
    Text(
        text = riga,
        color = Colori.tenue,
        fontSize = 12.sp,
        modifier = Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 8.dp),
    )
}

@Composable
private fun Risultati(
    gruppi: List<GruppoTrovato>,
    apri: (GruppoTrovato, String) -> Unit,
    modifier: Modifier = Modifier,
) {
    LazyColumn(modifier = modifier) {
        for (gruppo in gruppi) {
            item {
                Text(
                    gruppo.titolo,
                    color = if (gruppo.dalPc) Colori.attenuato else Colori.tenue,
                    fontSize = 11.sp,
                    letterSpacing = 1.sp,
                    modifier = Modifier.padding(start = 16.dp, top = 20.dp, bottom = 6.dp),
                )
            }
            items(gruppo.voci.size) { quante ->
                val voce = gruppo.voci[quante]
                Column(Modifier.clickable { apri(gruppo, voce) }) {
                    Text(
                        voce,
                        color = Colori.ink,
                        fontSize = 15.sp,
                        modifier = Modifier
                            .fillMaxWidth()
                            .padding(horizontal = 16.dp, vertical = 12.dp),
                    )
                    Box(Modifier.fillMaxWidth().height(1.dp).background(Colori.linea))
                }
            }
        }
    }
}

@Composable
private fun IlVuoto(perche: String, modifier: Modifier = Modifier) {
    Box(modifier.fillMaxWidth(), contentAlignment = Alignment.Center) {
        Text(
            perche,
            color = Colori.attenuato,
            fontSize = 14.sp,
            textAlign = TextAlign.Center,
            modifier = Modifier.padding(horizontal = 40.dp),
        )
    }
}
