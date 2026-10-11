package visore.app

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.BasicTextField
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.SolidColor
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import kotlinx.coroutines.delay
import visore.telefono.SchermataDiApertura
import visore.telefono.TastoApri

@Composable
fun SchermoDiApertura(
    schermata: SchermataDiApertura,
    apri: (String) -> Boolean,
    modifier: Modifier = Modifier,
) {
    var password by remember { mutableStateOf("") }
    var tasto by remember { mutableStateOf(TastoApri()) }

    LaunchedEffect(tasto.restano) {
        if (tasto.restano > 0) {
            delay(1000)
            tasto = tasto.unSecondo()
        }
    }

    Column(
        modifier = modifier.fillMaxSize().background(Colori.fondo).padding(horizontal = 28.dp),
        verticalArrangement = Arrangement.Center,
    ) {
        Intestazione(schermata)

        Text(SchermataDiApertura.PASSWORD, color = Colori.attenuato, fontSize = 13.sp)
        CampoDellaPassword(
            password = password,
            scritta = { password = it },
            modifier = Modifier.padding(top = 8.dp),
        )

        tasto.avviso?.let {
            Text(
                it,
                color = Colori.attenuato,
                fontSize = 13.sp,
                modifier = Modifier.padding(top = 8.dp),
            )
        }

        TastoDiApertura(
            tasto = tasto,
            premuto = {
                if (!apri(password)) {
                    tasto = tasto.sbagliata()
                }
                password = ""
            },
            modifier = Modifier.padding(top = 16.dp),
        )

        Text(
            schermata.promessa,
            color = Colori.tenue,
            fontSize = 13.sp,
            textAlign = TextAlign.Center,
            modifier = Modifier.fillMaxWidth().padding(top = 24.dp),
        )

        RigaDellaFirma(schermata)
    }
}

@Composable
private fun Intestazione(schermata: SchermataDiApertura) {
    Column(
        modifier = Modifier.fillMaxWidth().padding(bottom = 48.dp),
        horizontalAlignment = Alignment.CenterHorizontally,
    ) {
        Text(
            schermata.titolo,
            color = Colori.ink,
            fontSize = 23.sp,
            fontWeight = FontWeight.SemiBold,
        )
        Text(
            schermata.riga,
            color = Colori.attenuato,
            fontSize = 13.sp,
            modifier = Modifier.padding(top = 8.dp),
        )
    }
}

@Composable
private fun CampoDellaPassword(
    password: String,
    scritta: (String) -> Unit,
    modifier: Modifier = Modifier,
) {
    BasicTextField(
        value = password,
        onValueChange = scritta,
        singleLine = true,
        visualTransformation = PasswordVisualTransformation(),
        keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Password),
        textStyle = TextStyle(color = Colori.ink, fontSize = 16.sp, letterSpacing = 6.sp),
        cursorBrush = SolidColor(Colori.ink),
        modifier = modifier
            .fillMaxWidth()
            .clip(RoundedCornerShape(8.dp))
            .background(Colori.superficie)
            .padding(horizontal = 16.dp, vertical = 13.dp),
    )
}

@Composable
private fun TastoDiApertura(tasto: TastoApri, premuto: () -> Unit, modifier: Modifier = Modifier) {
    Box(
        modifier = modifier
            .fillMaxWidth()
            .clip(RoundedCornerShape(8.dp))
            .background(if (tasto.acceso) Colori.fill else Colori.superficie)
            .clickable(enabled = tasto.acceso, onClick = premuto),
        contentAlignment = Alignment.Center,
    ) {
        if (!tasto.acceso) {
            Box(
                Modifier
                    .fillMaxWidth(tasto.riempimento.toFloat())
                    .fillMaxHeight()
                    .background(Colori.linea)
                    .align(Alignment.CenterStart),
            )
        }
        Text(
            text = tasto.scritta,
            color = if (tasto.acceso) Colori.suFill else Colori.attenuato,
            fontSize = 16.sp,
            fontWeight = FontWeight.SemiBold,
            modifier = Modifier.padding(vertical = 13.dp),
        )
    }
}

@Composable
private fun RigaDellaFirma(schermata: SchermataDiApertura) {
    val firma = schermata.firma ?: return
    Column(
        modifier = Modifier.fillMaxWidth().padding(top = 48.dp),
        horizontalAlignment = Alignment.CenterHorizontally,
    ) {
        Box(Modifier.fillMaxWidth().height(1.dp).background(Colori.linea))
        Text(
            firma.frase,
            color = if (firma.scaduta) Colori.ink else Colori.attenuato,
            fontSize = 13.sp,
            modifier = Modifier.padding(top = 13.dp),
        )
    }
}
