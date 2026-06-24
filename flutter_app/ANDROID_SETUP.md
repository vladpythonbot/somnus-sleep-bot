# Android setup

Add to `android/app/src/main/AndroidManifest.xml`:

```xml
<uses-permission android:name="android.permission.INTERNET" />
<uses-permission android:name="android.permission.health.READ_SLEEP" />

<queries>
    <package android:name="com.google.android.apps.healthdata" />
</queries>
```

Inside `<activity android:name=".MainActivity">` add:

```xml
<meta-data
    android:name="health_permissions"
    android:resource="@array/health_permissions" />

<intent-filter>
    <action android:name="androidx.health.ACTION_SHOW_PERMISSIONS_RATIONALE" />
</intent-filter>
```

Create `android/app/src/main/res/values/health_permissions.xml`:

```xml
<?xml version="1.0" encoding="utf-8"?>
<resources>
    <array name="health_permissions">
        <item>android.permission.health.READ_SLEEP</item>
    </array>
</resources>
```
