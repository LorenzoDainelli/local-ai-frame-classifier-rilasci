// La strada del computer.
//
// La regola 387 dice che il posto in cui il database del pacchetto si apre e'
// uno solo, e che dietro quel posto ci sono due strade: questa, e quella del
// telefono che non e' ancora scritta. Qui c'e' SQLite via JDBC, che sa aprire
// un database dai byte e quindi non scrive mai niente in chiaro sul disco.
//
// C'e' anche il comando `apri`, che serve alla prova incrociata: il Python
// costruisce un pacchetto, questo lo apre e dice cosa ci ha trovato.

plugins {
    kotlin("jvm")
    application
}

repositories {
    mavenCentral()
}

dependencies {
    implementation(project(":lettore"))
    implementation("org.json:json:20250517")
    implementation("org.xerial:sqlite-jdbc:3.50.3.0")
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

application {
    mainClass.set("visore.computer.PrincipaleKt")
}

tasks.test {
    useJUnitPlatform()
    testLogging { events("failed") }
}
