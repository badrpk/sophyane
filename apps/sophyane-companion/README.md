# Sophyane Companion

Native Android alarm companion for Sophyane.

## Capabilities

- Exact Android wake-up alarms
- Alarm ringtone and vibration
- Lock-screen/full-screen alarm screen
- Alarm restoration after reboot or app update
- Deep-link alarm creation

## Deep-link example

    sophyane://alarm/create?hour=7&minute=0&label=Wake%20up

## Build

Open this directory in Android Studio and build the `app` module.

With Android SDK and Gradle installed:

    gradle wrapper --gradle-version 8.13
    ./gradlew assembleDebug

Expected APK:

    app/build/outputs/apk/debug/app-debug.apk

## Required permissions

After installation:

1. Allow notifications.
2. Allow Alarms & reminders.
3. Allow full-screen alarm notifications where available.
4. On Samsung, prevent Sophyane Companion from entering deep sleep.
