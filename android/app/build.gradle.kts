plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.plugin.compose")
}

providers.gradleProperty("setuBuildDirectory").orNull?.let { layout.buildDirectory.set(file(it)) }

android {
    // The .tflite bundle is memory-mapped at load; compressing it in the APK would force a copy to
    // the heap first.
    androidResources { noCompress += "tflite" }
    namespace = "com.setu.navigator"
    // Normally resolved from the SDK by version. `-PsetuNdkPath=<dir>` points at an NDK installed
    // outside the SDK, which is how this workspace builds when the SDK drive is short of space.
    providers.gradleProperty("setuNdkPath").orNull
        ?.let { ndkPath = it }
        ?: run { ndkVersion = "28.2.13676358" }
    compileSdk {
        version = release(37) { minorApiLevel = 0 }
    }
    defaultConfig {
        applicationId = "com.setu.navigator"
        minSdk = 26
        targetSdk = 36
        versionCode = 1
        versionName = "0.1.0"
        testInstrumentationRunner = "androidx.test.runner.AndroidJUnitRunner"
        ndk { abiFilters += listOf("arm64-v8a", "x86_64") }
        externalNativeBuild { cmake { cppFlags += "-O2" } }
    }
    buildFeatures {
        compose = true
        buildConfig = true
    }
    externalNativeBuild {
        cmake {
            path = file("src/main/cpp/CMakeLists.txt")
            version = "3.22.1"
        }
    }
    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
    packaging {
        resources.excludes += "/META-INF/{AL2.0,LGPL2.1}"
    }
    testOptions {
        unitTests.isReturnDefaultValues = true
    }
}

dependencies {
    implementation(platform("androidx.compose:compose-bom:2026.08.00"))
    implementation("androidx.activity:activity-compose:1.12.4")
    implementation("androidx.lifecycle:lifecycle-viewmodel-compose:2.10.0")
    implementation("androidx.lifecycle:lifecycle-runtime-compose:2.10.0")
    implementation("androidx.compose.ui:ui")
    implementation("androidx.compose.ui:ui-tooling-preview")
    implementation("androidx.compose.material3:material3")
    implementation("androidx.compose.material:material-icons-extended:1.7.8")
    implementation("org.maplibre.gl:android-sdk:13.6.0")
    implementation("org.jetbrains.kotlinx:kotlinx-coroutines-android:1.10.2")
    // On-device speed inference. REQ-F9 requires the model to run on the phone: a tunnel has no
    // connectivity, so a remote endpoint cannot be the inference path.
    implementation("org.tensorflow:tensorflow-lite:2.17.0")
    debugImplementation("androidx.compose.ui:ui-tooling")
    debugImplementation("androidx.compose.ui:ui-test-manifest")
    testImplementation("junit:junit:4.13.2")
    // android.jar ships org.json as stubs that return null, so anything touching JSON silently
    // degrades in a JVM unit test rather than failing. A real implementation on the test classpath
    // lets those paths actually be tested.
    testImplementation("org.json:json:20240303")
    androidTestImplementation(platform("androidx.compose:compose-bom:2026.08.00"))
    androidTestImplementation("androidx.compose.ui:ui-test-junit4")
    androidTestImplementation("androidx.test.ext:junit:1.3.0")
    androidTestImplementation("androidx.test:runner:1.7.0")
}
