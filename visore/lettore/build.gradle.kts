// Il lettore del pacchetto. Kotlin e basta.
//
// **Qui dentro non entra nessuna libreria** che non sia gia' dentro Android:
// e' il pezzo che l'app si portera' dietro, e ogni dipendenza in piu' e'
// codice che nessuno di noi ha letto dentro un programma che deve funzionare
// senza rete per vent'anni (regole 1, 358).
//
// Perche' allora `org.json`: su Android quella classe c'e' gia' nel sistema —
// sull'app non aggiunge un byte — e sul computer costa settanta kilobyte. La
// carta d'identita' del pacchetto e' un JSON, e scriversi un lettore di JSON a
// mano sarebbe stato l'unico pezzo davvero inutile di questo file.

plugins {
    kotlin("jvm")
}

repositories {
    mavenCentral()
}

dependencies {
    implementation("org.json:json:20250517")
    testImplementation(kotlin("test"))
}

// Il codice si compila per Java 21, ma **non** si pretende che sul computer
// ci sia proprio il 21 installato: si compila con quel Java che c'e', purche'
// sia il 21 o piu' nuovo. La differenza conta: «jvmToolchain(21)» vuole
// esattamente quel numero e si ferma se non lo trova, e Android Studio si
// porta dietro il 25. Cosi' invece il progetto si apre e si prova dove
// capita, senza scaricare un secondo Java da internet.
kotlin {
    compilerOptions {
        jvmTarget.set(org.jetbrains.kotlin.gradle.dsl.JvmTarget.JVM_21)
    }
}

// La stessa cosa detta anche al Java. Di file «.java» qui non ce n'e' nemmeno
// uno, ma Gradle prepara lo stesso il compilatore Java e controlla che i due
// vadano d'accordo: se il Kotlin punta al 21 e il Java al 25 si ferma e lo
// dice. Quindi lo si dice due volte, una per compilatore.
tasks.withType<JavaCompile>().configureEach {
    sourceCompatibility = "21"
    targetCompatibility = "21"
}

tasks.test {
    useJUnitPlatform()
    testLogging { events("failed") }
}
