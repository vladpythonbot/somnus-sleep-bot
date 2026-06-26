# Somnus Sleep Bot

Free sleep analytics pipeline:

```text
Mi Fitness -> Android Health Connect -> Flutter APK -> Python Telegram bot
```

The Telegram bot receives sleep data from the custom APK and sends a detailed text report directly to the user.

## Backend

Python backend:

- aiogram 3.x
- FastAPI
- uvicorn
- endpoint: `POST /webhook/sleep-apk`
- compatibility alias: `POST /webhook/sleep`

Environment variables:

```env
BOT_TOKEN=your_telegram_bot_token
WEBHOOK_SECRET=change_me
PORT=8000
DB_PATH=sleep_bot.db
```

Run:

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python main.py
```

Railway uses:

```text
python main.py
```

For persistent sleep history on Railway, create a Volume mounted to:

```text
/data
```

Then add this Railway variable:

```env
DB_PATH=/data/sleep_bot.db
```

Without a Volume, sleep statistics can be lost after redeploys.

## APK

Flutter app is in:

```text
flutter_app/
```

Main file:

```text
flutter_app/lib/main.dart
```

The app:

- requests Health Connect sleep permissions
- reads `SleepSession` and `SleepStage`
- lets the user choose a delay after wake-up
- registers a periodic Workmanager background task
- sends the automatic report after wake-up plus the selected delay, once per sleep night
- sends JSON to the backend

Android WorkManager is battery-friendly and does not guarantee exact alarm-like timing. The report is sent after the detected wake-up time when Android allows background work and network access.

Report delivery depends on:

- when Mi Fitness writes sleep data to Health Connect
- the delay selected in the APK after wake-up
- network availability
- Android battery optimization
- whether background activity is allowed for the APK
- WorkManager scheduling decisions

See Android permissions:

```text
flutter_app/ANDROID_SETUP.md
```

## Build APK in GitHub

You do not need Flutter or Android Studio on your PC.

1. Open GitHub repository.
2. Go to `Actions`.
3. Open `Build Flutter APK`.
4. Click `Run workflow`.
5. Wait until the build is green.
6. Download artifact `somnus-sync-apk`.
7. Inside it, install `app-release.apk` on Android.

The same build also runs automatically when files in `flutter_app/` are pushed.

## Backend URL in APK

```text
https://YOUR_DOMAIN.up.railway.app/webhook/sleep-apk
```

If `WEBHOOK_SECRET` is enabled, enter the same secret in the APK field.

## JSON payload

```json
{
  "telegram_id": 123456789,
  "date": "2026-06-24T08:00:00",
  "source": "health_connect_flutter_apk",
  "total_sleep_minutes": 455,
  "deep_sleep_minutes": 92,
  "light_sleep_minutes": 285,
  "rem_sleep_minutes": 78,
  "awake_minutes": 21
}
```

## Notes

The report is not a medical diagnosis. It is practical sleep analytics based on wearable data.
