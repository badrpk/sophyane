plugins {
    id("com.android.application")
}

android {
    namespace = "com.sophyane.companion"
    compileSdk = 36

    defaultConfig {
        applicationId = "com.sophyane.companion"
        minSdk = 26
        targetSdk = 36
        versionCode = 2
        versionName = "0.2.0"
    }

    buildFeatures {
        buildConfig = true
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
}
