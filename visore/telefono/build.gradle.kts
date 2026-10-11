// La parte che sta sul telefono Android (regole 356, 386).
//
// **Dipende da `lettore` e non da `computer`, ed e' il punto di questo file.**
// La regola 386 dice che di quello che finira' nell'app ci si deve poter
// fidare guardando le dipendenze e non le intenzioni: se qui dentro comparisse
// `project(":computer")`, o `sqlite-jdbc`, o qualunque altra cosa che su un
// telefono non c'e', si vedrebbe da questa riga e non dopo mesi.
//
// **Perche' non e' ancora un modulo Android.** Il plugin di Android chiede
// l'SDK installato: metterlo oggi vorrebbe dire che `gradle -p visore test`
// smette di girare su ogni macchina che l'SDK non ce l'ha, comprese quelle
// dove girano le prove. Diventa un modulo Android il giorno in cui c'e'
// Android Studio (documentazione/come-si-costruisce-l-app.md), e quel giorno
// cambia questo file e non il codice: qui dentro non c'e' una riga che parli
// di Android.

plugins {
    kotlin("jvm")
    // Serve per poter dire «api» qui sotto: e' il plugin che distingue le
    // dipendenze che un modulo passa a chi lo usa da quelle che tiene per se'.
    `java-library`
}

repositories {
    mavenCentral()
}

dependencies {
    // «api» e non «implementation», e la differenza si vede dall'app.
    //
    // «implementation» vuol dire: mi serve dentro, ma non lo passo a chi
    // dipende da me. «api» vuol dire: fa parte di come mi si parla.
    //
    // Qui e' il secondo caso, e non per comodita': le funzioni pubbliche di
    // questo modulo restituiscono dei «Giorno», che sono roba del lettore. Chi
    // le chiama quel nome lo deve poter scrivere. Con «implementation» l'app
    // si fermava su «Unresolved reference 'lettore'», ed era giusto che si
    // fermasse: chiedeva un tipo che nessuno le aveva passato.
    api(project(":lettore"))
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
