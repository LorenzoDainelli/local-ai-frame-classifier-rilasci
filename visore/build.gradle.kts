// Il file di cima del progetto. **Qui non si costruisce niente**: qui si dice
// una volta sola quale versione hanno gli arnesi, e poi ogni modulo li chiama
// per nome senza ripetere il numero.
//
// Perche' serve. Gradle si lamentava cosi': «The Kotlin Gradle plugin was
// loaded multiple times in different subprojects, which is not supported and
// may break the build». Succedeva perche' «app», «computer», «lettore» e
// «telefono» scrivevano ognuno la propria versione, e quattro copie dello
// stesso arnese nella stessa costruzione sono quattro occasioni di litigare.
// Peggio: il giorno in cui una delle quattro righe viene aggiornata e le altre
// tre no, il progetto smette di costruirsi per una ragione che non si legge da
// nessuna parte.
//
// «apply false» vuol dire: scarica l'arnese e tienilo pronto, ma qui in cima
// non applicarlo a niente. Di codice, in cima, non ce n'e'.

plugins {
    id("com.android.application") version "8.13.0" apply false
    kotlin("android") version "2.2.0" apply false
    kotlin("jvm") version "2.2.0" apply false
    id("org.jetbrains.kotlin.plugin.compose") version "2.2.0" apply false
}
