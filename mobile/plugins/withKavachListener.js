// Adds the Kavach accessibility service to the Android build (ios/android folders are generated, never edited by hand).
const fs = require('fs');
const path = require('path');
const { AndroidConfig, withAndroidManifest, withAppBuildGradle, withDangerousMod } = require('expo/config-plugins');

const XML = `<?xml version="1.0" encoding="utf-8"?>
<accessibility-service xmlns:android="http://schemas.android.com/apk/res/android"
    android:accessibilityEventTypes="typeWindowStateChanged"
    android:accessibilityFeedbackType="feedbackGeneric"
    android:notificationTimeout="1000"
    android:canRetrieveWindowContent="false"
    android:description="@string/kavach_accessibility_description" />
`;

module.exports = (config) => {
  config = withAndroidManifest(config, (c) => {
    AndroidConfig.Permissions.addPermission(c.modResults, 'android.permission.MODIFY_AUDIO_SETTINGS');
    const app = AndroidConfig.Manifest.getMainApplicationOrThrow(c.modResults);
    app.service = (app.service || []).filter((s) => s.$['android:name'] !== '.KavachListenerService');
    app.service.push({
      $: { 'android:name': '.KavachListenerService', 'android:exported': 'true',
           'android:permission': 'android.permission.BIND_ACCESSIBILITY_SERVICE', 'android:label': 'Kavach call protection' },
      'intent-filter': [{ action: [{ $: { 'android:name': 'android.accessibilityservice.AccessibilityService' } }] }],
      'meta-data': [{ $: { 'android:name': 'android.accessibilityservice', 'android:resource': '@xml/kavach_accessibility' } }],
    });
    app.provider = (app.provider || []).filter((p) => p.$['android:name'] !== 'rikka.shizuku.ShizukuProvider');
    app.provider.push({
      $: { 'android:name': 'rikka.shizuku.ShizukuProvider', 'android:authorities': '${applicationId}.shizuku', 'android:enabled': 'true',
           'android:exported': 'true', 'android:multiprocess': 'false', 'android:permission': 'android.permission.INTERACT_ACROSS_USERS_FULL' },
    });
    return c;
  });
  config = withAppBuildGradle(config, (c) => {
    if (!c.modResults.contents.includes('okhttp3:okhttp')) {
      c.modResults.contents = c.modResults.contents.replace(/dependencies\s*\{/, "dependencies {\n    implementation 'com.squareup.okhttp3:okhttp:4.12.0'\n    implementation 'dev.rikka.shizuku:api:13.1.5'\n    implementation 'dev.rikka.shizuku:provider:13.1.5'");
    }
    return c;
  });
  return withDangerousMod(config, ['android', (c) => {
    const root = c.modRequest.platformProjectRoot;
    const res = path.join(root, 'app/src/main/res');
    fs.mkdirSync(path.join(res, 'xml'), { recursive: true });
    fs.writeFileSync(path.join(res, 'xml/kavach_accessibility.xml'), XML);
    fs.mkdirSync(path.join(res, 'values'), { recursive: true });
    fs.writeFileSync(path.join(res, 'values/kavach_strings.xml'),
      '<resources><string name="kavach_accessibility_description">Lets Kavach use the microphone during a call on speaker, to warn you about scams, and show its button over the dialer.</string></resources>');
    if (!process.env.EXPO_PUBLIC_KAVACH_SERVER || !process.env.EXPO_PUBLIC_KAVACH_KEY) {
      throw new Error('EXPO_PUBLIC_KAVACH_SERVER and EXPO_PUBLIC_KAVACH_KEY must be set: the app cannot reach the server without them.');
    }
    const src = fs.readFileSync(path.join(c.modRequest.projectRoot, 'plugins/android/KavachListenerService.kt'), 'utf8')
      .replace('__KAVACH_SERVER__', process.env.EXPO_PUBLIC_KAVACH_SERVER || '')
      .replace('__KAVACH_KEY__', process.env.EXPO_PUBLIC_KAVACH_KEY || '');
    const dir = path.join(root, 'app/src/main/java/com/kavach/app');
    fs.mkdirSync(dir, { recursive: true });
    fs.writeFileSync(path.join(dir, 'KavachListenerService.kt'), src);
    fs.copyFileSync(path.join(c.modRequest.projectRoot, 'plugins/android/KavachShell.kt'), path.join(dir, 'KavachShell.kt'));
    // Shizuku starts KavachShell by name in another process, so the shrinker must leave it whole.
    fs.appendFileSync(path.join(root, 'app/proguard-rules.pro'),
      '\n-keep class com.kavach.app.KavachShell { *; }\n-keep class com.kavach.app.KavachShell$* { *; }\n-keep class rikka.shizuku.** { *; }\n-keep class moe.shizuku.** { *; }\n');
    return c;
  }]);
};
