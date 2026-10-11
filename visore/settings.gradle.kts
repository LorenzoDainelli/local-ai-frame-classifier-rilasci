// Il Visore: le due app che stanno sul telefono (regole 356-383).
//
// Tutto in Kotlin, perche' in Kotlin e' l'app Android. C'e' il lettore del
// pacchetto, che e' la meta' che l'app non dovra' riscrivere; c'e' quello che
// ogni schermata dice, provato senza telefono; e ci sono le otto schermate
// disegnate, che si compilano dove l'SDK c'e'.
//
//   lettore   il pacchetto: carta d'identita', cifratura, database, verifica.
//             Non dipende da niente: ne' da Android, ne' da un database, ne'
//             dalla rete. Sono le regole del formato, scritte una volta.
//
//   computer  la stessa cosa aperta su un computer invece che su un telefono:
//             il database SQLite via JDBC, e un comando per aprire un
//             pacchetto e dire cosa c'e' dentro.
//
//   telefono  quello che fara' l'app: apre il pacchetto e quello che il
//             telefono possiede, e tiene aperti tutti e due finche' l'app e'
//             aperta. Dipende da «lettore» e **non** da «computer» (regola
//             386): e' cosi' che si sa, guardando le dipendenze e non le
//             intenzioni, che nell'app non entra niente di buono solo per un
//             PC. Non e' ancora un modulo Android, e il perche' e' scritto
//             nel suo build.gradle.kts.

//   app       le schermate vere, disegnate con Compose. E' l'unico modulo
//             che parla di Android, e per questo e' l'unico che chiede
//             l'SDK: entra nel progetto solo dove l'SDK c'e', e come si
//             faccia sta scritto in fondo a questo file.

// Da dove si prendono i plugin. «google()» serve solo al plugin di Android, e
// non c'entra col codice: nell'app non entra nessuna libreria di Google.
pluginManagement {
    repositories {
        google()
        mavenCentral()
        gradlePluginPortal()
    }
}

rootProject.name = "visore"

include("lettore")
include("computer")
include("telefono")

// **Il modulo «app» c'e' solo se c'e' l'SDK di Android.**
//
// Non e' un trucco per far finta che vada: e' la promessa che «gradlew test»
// prova il lettore e le otto schermate su qualsiasi computer, anche uno appena
// acceso, senza scaricare i gigabyte dell'SDK. Chi vuole costruire l'app vera
// installa Android Studio, e da quel momento questa riga trova l'SDK e il
// modulo compare da solo, senza toccare niente.
//
// Dove si guarda, nell'ordine: «local.properties» (che lo scrive Android
// Studio, e che su GitHub non ci va perche' dentro c'e' il nome dell'utente),
// poi le due variabili d'ambiente di sempre.
val doveStaLSdk: String? = run {
    val suo = file("local.properties")
    if (suo.exists()) {
        val righe = java.util.Properties()
        suo.inputStream().use { righe.load(it) }
        val scritto = righe.getProperty("sdk.dir")
        if (!scritto.isNullOrBlank()) {
            return@run scritto
        }
    }
    System.getenv("ANDROID_HOME") ?: System.getenv("ANDROID_SDK_ROOT")
}

if (doveStaLSdk != null && File(doveStaLSdk).isDirectory) {
    include("app")
} else {
    logger.lifecycle(
        "Visore: l'SDK di Android non c'e', e il modulo «app» resta fuori. " +
            "Il lettore e le schermate si provano lo stesso: gradlew test."
    )
}
