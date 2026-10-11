// L'app Android vera: **solo i pixel**.
//
// Qui dentro c'e' Compose e nient'altro: come si disegna una schermata, non
// cosa dice. Quello che dice sta in «telefono/», che resta un modulo normale
// senza una riga di Android — e' per questo che le sue prove girano su
// qualsiasi computer, anche dove l'SDK di Android non c'e' (regola 386).
//
// La divisione e' voluta e si legge da questo file: «app» dipende da
// «telefono», mai il contrario. Il giorno in cui qualcuno, per fare in fretta,
// mettesse una decisione dentro un @Composable, quella decisione smetterebbe
// di essere provata — e non se ne accorgerebbe nessuno.
//
// Questo modulo entra nel progetto **solo se l'SDK di Android c'e'**: come, sta
// scritto in settings.gradle.kts.

plugins {
    id("com.android.application")
    kotlin("android")
    id("org.jetbrains.kotlin.plugin.compose")
}

repositories {
    google()
    mavenCentral()
}

android {
    namespace = "visore.app"
    compileSdk = 35

    defaultConfig {
        applicationId = "visore.app"
        // Android 8, di otto anni fa: il Redmi e' molto piu' nuovo, ma non c'e'
        // ragione di tagliar fuori un telefono vecchio se il codice non usa
        // niente che li' manchi.
        minSdk = 26
        targetSdk = 35
        versionCode = 1
        versionName = "0.1"
    }

    buildFeatures {
        compose = true
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_21
        targetCompatibility = JavaVersion.VERSION_21
    }
}

kotlin {
    compilerOptions {
        jvmTarget.set(org.jetbrains.kotlin.gradle.dsl.JvmTarget.JVM_21)
    }
}

dependencies {
    implementation(project(":telefono"))

    implementation(platform("androidx.compose:compose-bom:2025.04.01"))
    implementation("androidx.compose.foundation:foundation")
    implementation("androidx.compose.material3:material3")
    implementation("androidx.compose.ui:ui")
    implementation("androidx.compose.ui:ui-tooling-preview")
    debugImplementation("androidx.compose.ui:ui-tooling")
    implementation("androidx.activity:activity-compose:1.10.1")
    implementation("androidx.core:core-ktx:1.16.0")
}
